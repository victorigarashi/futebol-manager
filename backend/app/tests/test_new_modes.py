"""Draft Eliminatório / Pack & Play (knockout tournament), Último Sobrevivente and the packs."""

from __future__ import annotations

import collections
from pathlib import Path

import pytest

from app.domain.catalog import load_catalog
from app.domain.draft import eligible_pool
from app.domain.market import InitialMarket
from app.domain.packs import (
    COMPOSITION,
    PackCollection,
    PackError,
    Packs,
    PackState,
    open_packs,
    tier_of,
)
from app.domain.rooms import mode_error
from app.domain.tournaments import (
    SurvivorState,
    first_round_pairs,
    survivor_eliminations,
    survivor_schedule,
    tournament_stages,
)
from app.services.market_service import MarketError
from app.services.season_service import SeasonService
from app.tests.fixtures.clock import play_knockouts
from app.tests.fixtures.market_catalog import complete_test_market, synthetic_catalog

CATALOG = Path(__file__).resolve().parents[3] / "data" / "catalogs" / "players.json"


def short_season(game_mode: str, size: int, room: str = "short", extra: dict | None = None):
    clubs = tuple(f"C{index:02}" for index in range(size))
    market = InitialMarket(synthetic_catalog("FIVE_A_SIDE", teams=20), "FIVE_A_SIDE", dict.fromkeys(clubs, 1_000_000_000))
    complete_test_market(market, room)
    service = SeasonService()
    service.create(room, market, rules={"game_mode": game_mode, **(extra or {})})
    return service, market, clubs


# ---------------------------------------------------------------------- rules of the room
def test_each_mode_only_starts_with_the_sizes_its_competition_supports():
    assert mode_error("DRAFT_KNOCKOUT", 8, "TRADITIONAL") is None and mode_error("PACK", 16, "TRADITIONAL") is None
    assert mode_error("DRAFT_KNOCKOUT", 6, "TRADITIONAL") and mode_error("PACK", 20, "TRADITIONAL")
    assert mode_error("SURVIVOR", 12, "TRADITIONAL") is None and mode_error("SURVIVOR", 4, "TRADITIONAL")
    assert mode_error("PACK", 8, "COINS")  # no initial market in these modes
    assert mode_error("TRADITIONAL", 6, "COINS") is None


# ---------------------------------------------------------------------- knockout tournament
def test_tournament_bracket_is_drawn_once_stronger_half_against_weaker_half():
    assert tournament_stages(4) == ("SF", "FINAL") and tournament_stages(16)[0] == "R16"
    ordered = [f"T{i}" for i in range(8)]
    pairs, draw = first_round_pairs("room:tournament:QF", ordered)
    assert pairs == first_round_pairs("room:tournament:QF", ordered)[0]
    assert [a for a, _ in pairs] == ordered[:4] and sorted(b for _, b in pairs) == ordered[4:]
    assert draw["kind"] == "POTS"


@pytest.mark.parametrize(("size", "ties_won"), ((4, 2), (8, 3), (16, 4)))
def test_draft_knockout_goes_straight_to_a_live_bracket_and_crowns_a_champion(size: int, ties_won: int):
    service, market, clubs = short_season("DRAFT_KNOCKOUT", size, room=f"ko{size}")
    season = service._season(f"ko{size}")
    assert season.state.fixtures == []  # no league: the knockout starts at once
    budgets = {club: market.teams[club].budget_cents for club in clubs}
    view = play_knockouts(service, f"ko{size}", market, limit=8)
    champion = view["champion"]
    assert champion in clubs
    ties = [t for t in season.knockout.ties.values() if t.competition == "TOURNAMENT"]
    assert len(ties) == size - 1 and all(t.complete for t in ties)
    assert sum(1 for t in ties if t.winner == champion) == ties_won
    # Penalties decide level ties; every match is a real engine match.
    for tie in ties:
        high, low = tie.aggregate()
        assert (high != low) or tie.penalties is not None
        assert season.matches[tie.match_id(1)]["status"] == "FINISHED"
    # No career prize money in a tournament.
    assert {club: market.teams[club].budget_cents for club in clubs} == budgets
    with pytest.raises(MarketError):
        service.create_next_season(f"ko{size}", market)


def test_tournament_survives_a_snapshot_restore_mid_way():
    service, market, _clubs = short_season("PACK", 8, room="snap")
    service.advance("snap", market, set())
    from app.tests.fixtures.clock import finish_round
    finish_round(service, "snap")
    exported = service.export_room("snap")
    restored = SeasonService()
    restored.restore_room("snap", exported)
    season = restored._season("snap")
    assert season.knockout.stage_ties("TOURNAMENT", "SF")  # the next stage is already drawn
    assert season.knockout.view() == service._season("snap").knockout.view()


# ---------------------------------------------------------------------- último sobrevivente
def test_survivor_path_keeps_an_even_field_down_to_a_final():
    assert survivor_schedule(8, 0) == [8, 6, 4, 2]
    assert survivor_schedule(20, 0) == [20, 16, 12, 8, 6, 4, 2]
    assert survivor_schedule(12, 4) == [12, 8, 4, 2]
    for size in (8, 12, 16, 20):
        for configured in (0, 2, 4):
            assert all(n % 2 == 0 for n in survivor_schedule(size, configured))
    assert survivor_eliminations(4, 4) == 2  # never below the two finalists


def test_survivor_ranks_by_points_goal_difference_goals_then_a_fixed_draw():
    state = SurvivorState("seed", [f"S{i}" for i in range(8)])
    round_ = state.draw_round()
    assert state.draw_round() is round_  # drawing again returns the same pairs
    results = [(3, 0), (1, 0), (2, 2), (0, 0)]
    for (home, away), (hg, ag) in zip(round_.pairs, results, strict=True):
        state.record(home, away, hg, ag)
    out = state.complete_round()
    table = [row["club_code"] for row in round_.table]
    assert table[0] == round_.pairs[0][0]                    # 3 points, +3
    assert table[1] == round_.pairs[1][0]                    # 3 points, +1
    assert set(table[2:4]) == set(round_.pairs[2])           # 1 point, 2 goals
    assert set(out) == {round_.pairs[0][1], round_.pairs[1][1]}  # the two defeats go out
    assert len(state.active) == 6 and state.complete_round() == out  # idempotent


def test_last_survivor_is_played_live_and_eliminated_clubs_no_longer_play():
    service, market, clubs = short_season("SURVIVOR", 8, room="sv")
    season = service._season("sv")
    humans = {clubs[0], clubs[1]}
    seen_rounds = 0
    for _ in range(10):
        if season.survivor.champion:
            break
        active = set(season.survivor.active)
        required = service.required_ready("sv", humans)
        assert required == humans & active  # an eliminated coach is never waited for
        for club in required:
            service.ready("sv", club)
        view = service.advance("sv", market, humans)
        from app.tests.fixtures.clock import finish_round
        playing = {m for mid in view["live_round"]["match_ids"] for m in (season.matches[mid]["home"], season.matches[mid]["away"])}
        assert playing == active
        finish_round(service, "sv")
        seen_rounds += 1
    survivor = season.survivor
    assert survivor.champion in clubs and seen_rounds == 4
    assert len(survivor.eliminated) == 7 and survivor.eliminated[-1]["club"] == survivor.runner_up
    assert service.view("sv")["champion"] == survivor.champion
    # The snapshot keeps every elimination exactly.
    restored = SeasonService()
    restored.restore_room("sv", service.export_room("sv"))
    assert restored._season("sv").survivor.to_dict() == survivor.to_dict()


# ---------------------------------------------------------------------- pack & play
@pytest.fixture(scope="module")
def real_catalog():
    return load_catalog(CATALOG).players


def test_packs_guarantee_positions_and_never_repeat_an_athlete_in_a_collection(real_catalog):
    for mode in ("ELEVEN_A_SIDE", "FIVE_A_SIDE"):
        shape = COMPOSITION[mode]
        packs = open_packs("room:FLA:packs", mode, real_catalog)
        assert packs == open_packs("room:FLA:packs", mode, real_catalog)  # reopening shows the same cards
        cards = [cid for pack in packs for cid in pack]
        assert len(packs) == shape["packs"] and len(cards) == sum(shape["positions"].values())
        assert len(set(cards)) == len(cards)
        by_id = {p.id: p for p in real_catalog}
        counts = collections.Counter(by_id[c].position for c in cards)
        for position, minimum in shape["positions"].items():
            if position != "ANY":
                assert counts[position] >= minimum
        assert by_id[packs[0][0]].position == "GK" or any(by_id[c].position == "GK" for c in packs[0])


def test_balanced_packs_give_everyone_the_same_quality_mix_and_luck_varies(real_catalog):
    tiers = tier_of(eligible_pool(real_catalog, 0))
    mixes = set()
    for club in ("FLA", "PAL", "COR", "SAO"):
        cards = [c for pack in open_packs(f"room:{club}:packs", "ELEVEN_A_SIDE", real_catalog) for c in pack]
        mixes.add(tuple(sorted(collections.Counter(tiers[c] for c in cards).items())))
    assert len(mixes) == 1 and dict(next(iter(mixes))) == {"OURO": 4, "PRATA": 8, "BRONZE": 12}
    lucky = {tuple(sorted(collections.Counter(tiers[c] for p in open_packs(f"r:{i}", "ELEVEN_A_SIDE", real_catalog, "LUCK") for c in p).items()))
             for i in range(8)}
    assert len(lucky) > 1
    # Repeats across managers are allowed (independent instances), never inside one.
    first = {c for p in open_packs("room:FLA:packs", "FIVE_A_SIDE", real_catalog) for c in p}
    assert any(first & {c for p in open_packs(f"room:X{i}:packs", "FIVE_A_SIDE", real_catalog) for c in p} for i in range(30))


def test_a_squad_is_built_only_from_opened_cards_of_the_own_collection(real_catalog):
    packs_ = open_packs("room:FLA:packs", "FIVE_A_SIDE", real_catalog)
    state = PackState("room", "FIVE_A_SIDE", "BRASILEIRAO", "BALANCED", {"FLA": PackCollection("FLA", packs_)})
    rules = Packs(state, real_catalog)
    rules.set_formation("FLA", rules.collection_view("FLA")["formations"][0]["code"])
    slot = next(iter(state.clubs["FLA"].slots))
    with pytest.raises(PackError):
        rules.place("FLA", slot, packs_[0][0])  # packs still closed
    for _ in packs_:
        rules.open_next("FLA")
    with pytest.raises(PackError):
        rules.place("FLA", slot, "not-mine")
    with pytest.raises(PackError):
        rules.confirm("FLA")  # incomplete squad
    rules.auto_complete("FLA")
    collection = state.clubs["FLA"]
    assert collection.confirmed and all(collection.slots.values()) and len(collection.bench) == 3
    assert set(filter(None, collection.slots.values())) | set(collection.bench) <= set(collection.cards)


# ---------------------------------------------------------------------- HTTP flows
def _room(client, **rules):
    from app.tests.test_lobby import guest, room_payload

    guest(client)
    response = client.post("/api/v1/rooms", json={**room_payload(), **rules})
    assert response.status_code == 201, response.text
    return response.json()["data"]


def test_pack_and_play_http_flow_from_lobby_to_the_tournament():
    from fastapi.testclient import TestClient

    from app.domain.rooms import room_manager
    from app.main import create_app
    from app.services.market_service import market_service
    from app.services.season_service import season_service

    with TestClient(create_app()) as host:
        from app.tests.test_lobby import guest, room_payload
        guest(host)
        bad = host.post("/api/v1/rooms", json={**room_payload(), "game_mode": "PACK", "team_count": 6, "max_human_participants": 2})
        assert bad.status_code == 422
        room = _room(host, game_mode="PACK", team_count=4, max_human_participants=2, mode="FIVE_A_SIDE")
        base = f"/api/v1/rooms/{room['id']}"
        assert host.put(f"{base}/participants/me/club", json={"club_code": "FLA"}).status_code == 200
        started = host.post(f"{base}/start")
        assert started.status_code == 200 and started.json()["data"]["phase"] == "PACK"
        view = host.get(f"{base}/pack").json()["data"]
        assert view["opened"] == 0 and view["packs"] == []
        for _ in range(view["packs_total"]):
            view = host.post(f"{base}/pack/open").json()["data"]
        assert view["opened"] == view["packs_total"] and sum(len(p) for p in view["packs"]) == 12
        assert host.post(f"{base}/pack/confirm").status_code == 409  # squad still empty
        assert host.post(f"{base}/pack/complete").status_code == 200
        assert room_manager._room(room["id"]).phase == "SQUAD_MANAGEMENT"
        market = market_service._session(room["id"]).market
        assert all(pid.startswith("PCK-") for team in market.teams.values() for pid in team.roster)
        season = season_service._season(room["id"])
        assert season.state.fixtures == [] and season.knockout.stage_ties("TOURNAMENT", "SF")


def test_last_survivor_http_flow_uses_the_real_squads():
    from fastapi.testclient import TestClient

    from app.domain.rooms import room_manager
    from app.main import create_app
    from app.services.market_service import market_service
    from app.services.season_service import season_service

    with TestClient(create_app()) as host:
        room = _room(host, game_mode="SURVIVOR", team_count=8, max_human_participants=2, survivor_eliminations=2)
        base = f"/api/v1/rooms/{room['id']}"
        assert host.put(f"{base}/participants/me/club", json={"club_code": "PAL"}).status_code == 200
        started = host.post(f"{base}/start")
        assert started.status_code == 200 and started.json()["data"]["phase"] == "SQUAD_MANAGEMENT"
        assert room_manager._room(room["id"]).phase == "SQUAD_MANAGEMENT"
        market = market_service._session(room["id"]).market
        assert len(market.teams) == 8 and all(len(team.roster) == 16 for team in market.teams.values())
        assert all(market.catalog[pid].club_code == club for club, team in market.teams.items() for pid in team.roster)
        view = host.get(f"{base}/season").json()["data"]
        assert view["game_mode"] == "SURVIVOR" and view["survivor"]["path"] == [8, 6, 4, 2]
        assert season_service._season(room["id"]).survivor.current.number == 1
