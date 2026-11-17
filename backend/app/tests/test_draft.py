"""Modo Draft (§31 do Prompt Master V2)."""

import statistics
from pathlib import Path

import pytest

from app.domain.catalog import load_catalog
from app.domain.draft import (
    BENCH_SIZE,
    Draft,
    DraftError,
    DraftSquad,
    DraftState,
    feasibility,
    fits,
)
from app.domain.squad import formation_slots

CATALOG = list(load_catalog(Path(__file__).resolve().parents[3] / "data" / "catalogs" / "players.json").players)


def new_draft(clubs=("FLA", "PAL"), mode="ELEVEN_A_SIDE", min_overall=0, room="draft-room"):
    state = DraftState(room, mode, "BRASILEIRAO", min_overall, {c: DraftSquad(c) for c in clubs})
    return Draft(state, CATALOG)


def test_formation_three_compatible_distinct_cards_and_no_reroll():
    draft = new_draft()
    draft.set_formation("FLA", "4-4-2")
    assert set(draft.state.clubs["FLA"].slots) == {s.id for s in formation_slots("ELEVEN_A_SIDE", "4-4-2")}  # 1
    for slot in formation_slots("ELEVEN_A_SIDE", "4-4-2"):
        cards = draft.offer("FLA", slot.id)
        assert len(cards) == 3  # 2
        assert all(fits(c, slot.position) for c in cards)  # 3
        assert len({c.id for c in cards}) == 3  # 4
        assert [c.id for c in draft.offer("FLA", slot.id)] == [c.id for c in cards]  # asking again: same cards


def test_starters_then_free_bench_and_warnings():
    draft = new_draft()
    draft.set_formation("FLA", "4-3-3")
    with pytest.raises(DraftError):
        draft.offer("FLA", "bench-1")  # starters first
    for slot in formation_slots("ELEVEN_A_SIDE", "4-3-3"):
        draft.pick("FLA", slot.id, draft.offer("FLA", slot.id)[0].id)  # 5
    positions = set()
    for index in range(1, BENCH_SIZE["ELEVEN_A_SIDE"] + 1):
        cards = draft.offer("FLA", f"bench-{index}")
        positions |= {c.position for c in cards}
        draft.pick("FLA", f"bench-{index}", cards[0].id)  # 6
    assert len(positions) > 1  # bench offers mix positions
    assert draft.state.is_complete("FLA")
    with pytest.raises(DraftError):
        draft.offer("FLA", "bench-6")


def test_balanced_draw_gives_every_manager_comparable_chances():
    clubs = tuple(f"C{i:02d}" for i in range(20))
    draft = new_draft(clubs=clubs)
    best_per_club = {}
    for club in clubs:
        draft.set_formation(club, "4-3-3")
        best = []
        for slot in formation_slots("ELEVEN_A_SIDE", "4-3-3"):
            cards = draft.offer(club, slot.id)
            best.append(max(c.overall for c in cards))
            draft.pick(club, slot.id, cards[0].id)
        best_per_club[club] = statistics.mean(best)
    spread = max(best_per_club.values()) - min(best_per_club.values())
    assert spread <= 3.5  # 7: every manager sees a top-tier card in every offer
    assert min(best_per_club.values()) >= statistics.mean(c.overall for c in CATALOG)


def test_minimum_overall_filters_everyone_and_infeasible_is_refused():
    draft = new_draft(min_overall=75)
    draft.set_formation("FLA", "4-3-3")
    for slot in formation_slots("ELEVEN_A_SIDE", "4-3-3"):
        assert all(c.overall >= 75 for c in draft.offer("FLA", slot.id))  # 8
    assert feasibility(CATALOG, "ELEVEN_A_SIDE", 0) == []
    assert feasibility(CATALOG, "ELEVEN_A_SIDE", 99)  # 9
    original = {p.id: p.overall for p in CATALOG}
    new_draft(min_overall=80)
    assert {p.id: p.overall for p in CATALOG} == original  # ratings never changed


def test_same_athlete_in_two_squads_as_independent_instances():
    draft = new_draft()
    for club in ("FLA", "PAL"):
        draft.set_formation(club, "4-3-3")
    # Force both managers to be offered the same keeper and pick him.
    keeper = next(p for p in CATALOG if p.position == "GK")
    for club in ("FLA", "PAL"):
        draft.state.clubs[club].offers["gk"] = [keeper.id, *[p.id for p in CATALOG if p.position == "GK" and p.id != keeper.id][:2]]
        draft.pick(club, "gk", keeper.id)  # 10
    fla, pal = draft.state.clubs["FLA"].slots["gk"], draft.state.clubs["PAL"].slots["gk"]
    assert fla != pal and draft.state.instances[fla]["catalog_id"] == draft.state.instances[pal]["catalog_id"]  # 11
    draft.state.instances[fla]["card"]["overall"] = 1  # mutating one instance never touches the other
    assert draft.state.instances[pal]["card"]["overall"] == keeper.overall
    # Same athlete twice in one squad is refused.
    draft.state.clubs["FLA"].offers["df-0-0"] = [keeper.id, "x", "y"]
    with pytest.raises(DraftError):
        draft.pick("FLA", "df-0-0", keeper.id)


def test_cards_outside_the_offer_and_confirmed_picks_are_refused():
    draft = new_draft()
    draft.set_formation("FLA", "4-3-3")
    cards = draft.offer("FLA", "gk")
    outsider = next(p for p in CATALOG if p.position == "GK" and p.id not in {c.id for c in cards})
    with pytest.raises(DraftError):
        draft.pick("FLA", "gk", outsider.id)  # 16
    draft.pick("FLA", "gk", cards[0].id)
    with pytest.raises(DraftError):
        draft.pick("FLA", "gk", cards[1].id)  # 17
    with pytest.raises(DraftError):
        draft.set_formation("FLA", "4-4-2")  # formation is fixed after the first pick


def test_bots_and_absent_managers_complete_their_squads():
    draft = new_draft(clubs=("FLA", "PAL", "BOT"))
    for difficulty, club in (("LEGENDARY", "BOT"), ("CASUAL", "PAL"), ("COMPETITIVE", "FLA")):
        draft.auto_complete(club, difficulty)  # 12, 13
        assert draft.state.is_complete(club)
        players = draft.roster_players(club)
        assert len(players) == 11 + 5 and len({p.source_ids["catalog_id"] for p in players}) == 16
        assert all(p.source_ids["draft_owner"] == club for p in players)


def test_five_a_side_draft():
    draft = new_draft(mode="FIVE_A_SIDE")
    draft.auto_complete("FLA")
    assert len(draft.roster_players("FLA")) == 5 + 3


def test_draft_state_survives_a_snapshot():  # 14: reconnection / restart keeps picks and open offers
    draft = new_draft()
    draft.set_formation("FLA", "4-3-3")
    draft.pick("FLA", "gk", draft.offer("FLA", "gk")[0].id)
    open_cards = [c.id for c in draft.offer("FLA", "df-0-0")]
    restored = DraftState.from_dict(draft.state.to_dict())
    assert restored.clubs["FLA"].offers["df-0-0"] == open_cards
    assert restored.clubs["FLA"].slots["gk"] == draft.state.clubs["FLA"].slots["gk"]


def test_draft_rooms_start_the_competition_and_keep_traditional_rules_apart(monkeypatch):
    """18, 19, 20: the finished draft becomes the room's market and season; cohesion works on instances."""
    import asyncio

    from app.services import draft_service as module
    from app.services.draft_service import DraftService
    from app.services.market_service import MarketService
    from app.services.season_service import SeasonService
    from app.services.squad_service import SquadService

    monkeypatch.setattr(module, "draft_catalog", lambda name: CATALOG)
    monkeypatch.setattr(module, "market_service", MarketService())
    squads = SquadService()
    monkeypatch.setattr(module, "squad_service", squads)
    service = DraftService()
    clubs = [f"C{i:02d}" for i in range(20)]

    async def run():
        service.start("room-d", "ELEVEN_A_SIDE", "BRASILEIRAO", 0, clubs, set(clubs[1:]), "COMPETITIVE", 300, 10_000_000_000)
        assert not service.complete_due("room-d")  # the human has not finished and time remains
        assert service.complete_due("room-d", force=True)
    asyncio.run(run())
    market = module.market_service.sessions["room-d"].market
    assert market.selection_complete and all(len(t.roster) == 16 for t in market.teams.values())
    ids = [pid for t in market.teams.values() for pid in t.roster]
    assert len(ids) == len(set(ids))  # instance ids are unique even when athletes repeat
    catalog_ids = [market.catalog[pid].source_ids["catalog_id"] for pid in ids]
    assert len(set(catalog_ids)) < len(catalog_ids)  # 20 squads from one catalog: athletes repeat
    assert squads.lineup_for("room-d", "C00")["formation_code"] == "4-3-3"
    seasons = SeasonService()
    seasons.create("room-d", market, rules={"game_mode": "DRAFT"})
    import app.services.squad_service as squad_module
    monkeypatch.setattr(squad_module, "squad_service", squads)
    report = seasons.cohesion_view("room-d", market, "C00")
    assert 0 <= report["compatibility"] <= 100 and -1 <= report["factor"] <= 1


def test_draft_http_flow_from_lobby_to_season():
    """Room → Draft → picks → automatic completion → squad management with a season."""
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.services.season_service import season_service
    from app.tests.test_lobby import guest, room_payload

    app = create_app()
    with TestClient(app) as host, TestClient(app) as friend:
        guest(host)
        bad = host.post("/api/v1/rooms", json={**room_payload(), "game_mode": "DRAFT", "draft_min_overall": 80})
        assert bad.status_code == 422 and "viável" in bad.json()["detail"]
        room = host.post("/api/v1/rooms", json={**room_payload(), "game_mode": "DRAFT", "draft_min_overall": 70}).json()["data"]
        base = f"/api/v1/rooms/{room['id']}"
        guest(friend)
        assert friend.post(f"{base}/join").status_code == 200
        assert host.put(f"{base}/participants/me/club", json={"club_code": "FLA"}).status_code == 200
        assert friend.put(f"{base}/participants/me/club", json={"club_code": "PAL"}).status_code == 200
        started = host.post(f"{base}/start")
        assert started.status_code == 200 and started.json()["data"]["phase"] == "DRAFT"
        assert host.put(f"{base}/draft/formation", json={"formation_code": "2-1-1"}).status_code == 200
        offer = host.post(f"{base}/draft/offer", json={"slot_id": "gk"}).json()["data"]
        assert len(offer["cards"]) == 3 and all(card["overall"] >= 70 for card in offer["cards"])
        again = host.post(f"{base}/draft/offer", json={"slot_id": "gk"}).json()["data"]
        assert [c["id"] for c in again["cards"]] == [c["id"] for c in offer["cards"]]
        wrong = host.post(f"{base}/draft/pick", json={"slot_id": "gk", "catalog_id": "nobody"})
        assert wrong.status_code == 409
        picked = host.post(f"{base}/draft/pick", json={"slot_id": "gk", "catalog_id": offer["cards"][0]["id"]})
        assert picked.status_code == 200 and picked.json()["data"]["slots"]["gk"]["catalog_id"] == offer["cards"][0]["id"]
        progress = friend.get(f"{base}/draft").json()["data"]["progress"]
        assert progress["FLA"]["picks"] == 1 and all(v["picks"] == 8 for c, v in progress.items() if v["bot"])
        assert friend.post(f"{base}/draft/complete").status_code == 403
        assert host.post(f"{base}/draft/complete").status_code == 200
        from app.domain.rooms import room_manager
        assert room_manager._room(room["id"]).phase == "SQUAD_MANAGEMENT"
        assert room["id"] in season_service._seasons
        squad = host.get(f"{base}/squad").json()["data"]
        assert len(squad["players"]) == 8 and squad["lineup"]["formation_code"] == "2-1-1"
        assert squad["cohesion"] is not None
