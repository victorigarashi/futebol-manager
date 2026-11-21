"""Every game mode reaches a champion with the Modo Jogável on the V7 engine.

Interactive matches block the round until they finish; here the human coaches are away
(the 30 s grace, then the AI takes their attacks) or play every decision with a simple
gesture, and the clock is advanced the way the server's timer task would.
"""

from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.tests.test_competition_flow import new_competition

MODES = [
    ("TRADITIONAL", 8, {"playoff_format": "SINGLE"}),
    ("DRAFT_KNOCKOUT", 8, {}),
    ("PACK", 4, {}),
    ("SURVIVOR", 8, {}),
]


def _play(service, market, room, humans, now, gestures: bool, max_steps: int = 6000):
    season = service._season(room)
    season.human_clubs = set(humans)
    engines: set[str] = set()
    for _ in range(max_steps):
        season = service._season(room)
        if season.playoffs and season.playoffs.champion:
            return season.playoffs.champion, engines
        if season.live_round:
            for session in season.highlights.values():
                engines.add(session.engine)
                if gestures and session.state == "DECISION" and session.opportunity:
                    club = str(session.opportunity["attacking"])
                    opp = session.opportunity
                    session.seen(club, now[0])
                    payload = {"action_id": f"g-{opp['id']}-{opp['actions']}-{session.revision}", "opportunity_id": opp["id"],
                               "revision": session.revision, "type": "SHOT", "x": 1.0 if opp["right"] else 0.0, "y": 0.5, "power": 0.7}
                    try:
                        session.submit(club, payload, now[0])
                    except ValueError:
                        pass
            now[0] += 2.0
            service.finish_due(room)
            continue
        if season.transfer_window_open:
            service.close_transfer_window(room)
            continue
        for club in sorted(humans):
            if service.preview(room, market, club).get("fixture") and club not in season.ready_clubs:
                service.ready(room, club)
        if not season.live_round and service.required_ready(room, humans).issubset(season.ready_clubs):
            service.advance(room, market, humans, 60)
        if not season.live_round:
            now[0] += 301
            service.start_if_preparation_expired(room, market, humans, 300, 60)
    raise AssertionError("A competição não terminou.")


@pytest.mark.parametrize(("game_mode", "size", "rules"), MODES)
@pytest.mark.parametrize("gestures", (True, False), ids=("coaches play", "coaches away"))
def test_every_mode_finishes_with_interactive_v7_matches(monkeypatch, game_mode, size, rules, gestures):
    monkeypatch.setattr(get_settings(), "gameplay_engine", "v7")
    room = f"v7-{game_mode}-{size}-{gestures}"
    service, market, clubs, now = new_competition(game_mode, size, {**rules, "execution_mode": "INTERACTIVE", "decision_seconds": 5}, room=room)
    humans = set(clubs[:2])
    champion, engines = _play(service, market, room, humans, now, gestures)
    assert champion in clubs
    assert engines == {"v7"}
    season = service._season(room)
    assert not season.highlights           # every interactive match was recorded and released
