"""Every goal belongs to the team that scored it, in the goal it attacks, and the score
always matches the events (measured, not assumed: see docs/AUDITORIA_CARREIRA.md)."""

from __future__ import annotations

import pytest

from app.domain.bot_coach import advance_with_bots
from app.domain.clubs import CLUBS
from app.domain.market import InitialMarket
from app.domain.match_engine import FULL_TIME_TICK, MatchEngine
from app.services.season_service import SeasonService
from app.tests.fixtures.market_catalog import complete_test_market, synthetic_catalog


@pytest.mark.parametrize("mode,rounds", [("ELEVEN_A_SIDE", 2), ("FIVE_A_SIDE", 2)])
def test_goal_attribution_direction_and_score_are_consistent(mode: str, rounds: int):
    service = SeasonService(clock=lambda: 1_000.0)
    market = InitialMarket(synthetic_catalog(mode, teams=20), mode, dict.fromkeys((c.code for c in CLUBS), 10**10))
    complete_test_market(market, f"goals-{mode}")
    service.create("room", market)
    fixtures = [f for f in service._season("room").state.fixtures if f.round_number <= rounds]
    goals = 0
    for fixture in fixtures:
        home, away, seed, _bots = service._fixture_inputs("room", market, fixture, set())
        engine = MatchEngine(fixture.id, mode, home, away, seed)
        advance_with_bots(engine, FULL_TIME_TICK, (0, 1), (home.tactics, away.tactics))
        squads = [{p.id for p in team.starters + team.bench} for team in (home, away)]
        frames = {frame[0]: frame for frame in engine.frames}
        for index, event in enumerate(engine.events):
            if event["kind"] != "GOAL":
                continue
            goals += 1
            side = 0 if event["team"] == engine.clubs[0] else 1
            assert event["player_id"] in squads[side]
            if event.get("secondary_player_id"):
                assert event["secondary_player_id"] in squads[side]
            shot = engine.events[index - 1]
            assert shot["kind"] == "SHOT" and shot["team"] == event["team"] and shot["player_id"] == event["player_id"]
            assert (event["x"] > 0.5) == (side == 0)  # the goal the scoring team attacks
            frame = frames.get(event["tick"])
            if frame is not None:
                assert (frame[1] / engine.L > 0.5) == (side == 0)  # the 2D ball is in that goal too
        score = [sum(1 for e in engine.events if e["kind"] == "GOAL" and e["team"] == engine.clubs[s]) for s in (0, 1)]
        assert score == list(engine.score)
    assert goals > 10
