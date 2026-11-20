"""Knockouts never get stuck: every competition is played the way the interface plays it.

Regression for the beta reports "eliminatórios travam / partidas não aparecem / o
sorteio trava". Root cause: the preparation deadline stopped after the last league
round, so a knockout (or survival) round in which no human played could never start
— those coaches only see "your club is not playing" and nobody could confirm.

The driver below behaves like the UI: a coach presses "Pronto" only when the
pre-match screen shows him a match, and otherwise only time passes (the server's
preparation timer). No hidden host button is ever pressed.
"""

from __future__ import annotations

import pytest

from app.domain.market import InitialMarket
from app.services.season_service import SeasonService
from app.tests.fixtures.market_catalog import complete_test_market, synthetic_catalog

PREP = 300


def new_competition(game_mode: str, size: int, rules: dict | None = None, room: str = "flow"):
    clubs = tuple(f"C{i:02}" for i in range(size))
    market = InitialMarket(synthetic_catalog("FIVE_A_SIDE", teams=20), "FIVE_A_SIDE", dict.fromkeys(clubs, 1_000_000_000))
    complete_test_market(market, room)
    now = [1_000.0]
    service = SeasonService(clock=lambda: now[0])
    service.create(room, market, double_round_robin=False, rules={"game_mode": game_mode, **(rules or {})})
    return service, market, clubs, now


def play_like_the_ui(service, market, room, humans, now, confirm=True, max_steps=400):
    """Returns the champion; fails if the competition stops making progress."""
    season = service._season(room)
    season.human_clubs = set(humans)
    last, idle = None, 0
    for _ in range(max_steps):
        season = service._season(room)
        if season.playoffs and season.playoffs.champion:
            return season.playoffs.champion
        progress = (len(season.matches), bool(season.live_round), len(season.knockout.ties), season.transfer_window_open)
        idle = idle + 1 if progress == last else 0
        last = progress
        assert idle <= 4, f"competição parada: {service.view(room)['next_round']} prontos={sorted(season.ready_clubs)}"
        if season.live_round:
            now[0] = float(season.live_round["ends_at"]) + 0.1
            service.finish_due(room)
            continue
        if season.transfer_window_open:
            service.close_transfer_window(room)
            continue
        if confirm:
            for club in sorted(humans):
                if service.preview(room, market, club).get("fixture") and club not in season.ready_clubs:
                    service.ready(room, club)
                    if not season.live_round and service.required_ready(room, humans).issubset(season.ready_clubs):
                        service.advance(room, market, humans, 60)
            if season.live_round:
                continue
        now[0] += PREP + 1
        service.start_if_preparation_expired(room, market, humans, PREP, 60)
    raise AssertionError("A competição não terminou.")


MATRIX = [
    ("TRADITIONAL", 8, {"playoff_format": "SINGLE"}),
    ("TRADITIONAL", 8, {"playoff_format": "TWO_LEGS"}),
    ("TRADITIONAL", 20, {"copa_enabled": True}),
    ("DRAFT_KNOCKOUT", 8, {}),
    ("DRAFT_KNOCKOUT", 16, {}),
    ("PACK", 4, {}),
    ("SURVIVOR", 8, {}),
    ("SURVIVOR", 12, {"survivor_eliminations": 4}),
]


@pytest.mark.parametrize(("game_mode", "size", "rules"), MATRIX)
@pytest.mark.parametrize("scenario", ("strong humans", "weak humans", "humans never confirm"))
def test_every_competition_reaches_a_champion_without_any_manual_unlock(game_mode, size, rules, scenario):
    service, market, clubs, now = new_competition(game_mode, size, rules, room=f"{game_mode}-{size}-{scenario}")
    room = f"{game_mode}-{size}-{scenario}"
    humans = set(clubs[:2]) if scenario == "strong humans" else set(clubs[-2:])
    champion = play_like_the_ui(service, market, room, humans, now, confirm=scenario != "humans never confirm")
    assert champion in clubs
    season = service._season(room)
    if game_mode == "TRADITIONAL":
        assert all(t.complete for t in season.knockout.ties.values())
        if rules.get("copa_enabled"):
            assert season.knockout.cup_champion in clubs


def test_the_playoff_draw_is_made_once_by_the_server_and_survives_a_restart():
    service, market, clubs, now = new_competition("TRADITIONAL", 8, {"playoff_format": "TWO_LEGS"}, room="draw")
    season = service._season("draw")
    while service.current_round("draw") <= service._regular_round_count(season):
        if season.transfer_window_open:
            service.close_transfer_window("draw")
        service.advance("draw", market, set(), 60)
        now[0] = float(season.live_round["ends_at"]) + 0.1
        service.finish_due("draw")
    # The last league round already produced the draw: nobody had to click anything.
    draw = [d for d in season.knockout.draws if d["competition"] == "PLAYOFF"]
    assert len(draw) == 1 and draw[0]["kind"] == "POTS"
    qualifiers = draw[0]["pot1"] + draw[0]["pot2"]
    assert len(set(qualifiers)) == 8 and sorted(c for pair in draw[0]["pairs"] for c in pair) == sorted(qualifiers)
    assert all(a in draw[0]["pot1"] and b in draw[0]["pot2"] for a, b in draw[0]["pairs"])
    # Repeated settling (refresh, two clients, a retried request) changes nothing.
    snapshot = season.knockout.view()
    for _ in range(3):
        service._settle_knockout("draw", market, season)
        service.advance("draw", market, set(), 60) if not season.live_round else None
    assert [d for d in season.knockout.draws if d["competition"] == "PLAYOFF"] == draw
    restored = SeasonService(clock=lambda: now[0])
    restored.restore_room("draw", service.export_room("draw"))
    assert restored._season("draw").knockout.draws == season.knockout.draws
    assert snapshot["draws"] == season.knockout.view()["draws"]


def test_a_coach_out_of_the_knockout_watches_a_live_match_without_seeing_tactics():
    service, market, clubs, now = new_competition("DRAFT_KNOCKOUT", 4, room="watch")
    season = service._season("watch")
    human = clubs[-1]  # weakest seed: plays the first semi-final
    season.human_clubs = {human}
    service.ready("watch", human)
    service.advance("watch", market, {human}, 60)
    now[0] = float(season.live_round["ends_at"]) + 0.1
    service.finish_due("watch")
    tie = next(t for t in season.knockout.ties.values() if human in (t.high, t.low))
    if tie.winner == human:
        pytest.skip("o humano venceu a semifinal nesta semente")
    # The final has no human: it starts by itself after the spectator pause…
    now[0] += service.SPECTATOR_PAUSE_SECONDS + 1
    assert service.start_if_preparation_expired("watch", market, {human}, PREP, 60)
    final_id = season.live_round["match_ids"][0]
    assert season.matches[final_id].get("featured")
    now[0] = float(season.live_round["started_at"]) + 20
    service.sync_live("watch", now[0])  # what the round task does every slice
    view = service.live_view("watch", human)
    assert view["match"]["id"] == final_id and view["match"]["you"] is None
    assert view["match"]["tactics"] == {"home": None, "away": None}
    assert service.live_frames("watch", human, -1)["frames"]  # a real 2D broadcast to watch


def test_playoff_prizes_are_paid_once_and_the_next_season_starts():
    service, market, clubs, now = new_competition("TRADITIONAL", 8, {"playoff_format": "SINGLE"}, room="prizes")
    champion = play_like_the_ui(service, market, "prizes", {clubs[0]}, now)
    budgets = {club: market.teams[club].budget_cents for club in clubs}
    season = service._season("prizes")
    for _ in range(3):
        service._settle_knockout("prizes", market, season)
    assert {club: market.teams[club].budget_cents for club in clubs} == budgets
    assert champion in clubs
    service.create_next_season("prizes", market)
    service.close_transfer_window("prizes")
    service._season("prizes").human_clubs = {clubs[0]}
    service.ready("prizes", clubs[0])
    view = service.advance("prizes", market, {clubs[0]}, 60)
    assert view["live_round"] and view["season_number"] == 2
