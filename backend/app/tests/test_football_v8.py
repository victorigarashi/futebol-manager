"""Football V8 (app.domain.football with profile "v8"): integrated behaviours.

Verifiable properties only (no "it is fun" claims): physics of the curled shot, the
keeper's low dive, the tactical contract producing different behaviour, set pieces,
determinism, snapshots and every competition mode finishing.
"""

from __future__ import annotations

import math
import random

import pytest

from app.core.config import get_settings
from app.domain.football.play import Play
from app.domain.football.world import Athlete, BallState
from app.domain.highlights import HL_PITCH, HighlightMatch
from app.tests.test_competition_flow import new_competition
from app.tests.test_football_v7 import _match, _steps
from app.tests.test_football_v7_competitions import MODES, _play

CFG = HL_PITCH["ELEVEN_A_SIDE"]
L, W = CFG["length"], CFG["width"]


def _a(i, team, role, x, y, pace=75, keeping=20, shooting=75, defending=60, physical=70):
    return Athlete(f"{team}{i}", f"{team}{i}", i, team, role, x, y, pace, 70, shooting, 70, defending, physical, keeping)


def _shot(profile, distance, offset, aim, power, keeping=75, seed=0, mate=False):
    shooter = _a(9, "A", "ST", L - distance, W / 2 + offset, shooting=85)
    keeper = _a(1, "D", "GK", L - 1.0, W / 2, pace=50, keeping=keeping)
    keeper.facing = math.pi
    bodies = [shooter, keeper] + ([_a(5, "D", "DF", L - 30, 8)] if mate else [])
    for b in bodies:
        b.ax, b.ay = b.x, b.y
    play = Play(bodies, BallState(shooter.x + 0.4, shooter.y), CFG, random.Random(seed), profile=profile)
    return play, play.run(shooter.id, "SHOT", L, W / 2 + aim, power)


# ------------------------------------------------------------------ engine & contract
def test_v8_matches_use_v8_frames_and_never_teleport():
    match = _match(engine="v8")
    steps = _steps(match)
    assert steps and all(s["layout"] == "v8" for _, s in steps)
    for opp, step in steps:
        n = len(opp["bodies"])
        for a, b in zip(step["frames"], step["frames"][1:], strict=False):
            dt = b[0] - a[0]
            assert math.hypot((b[1] - a[1]) * L, (b[2] - a[2]) * W) / dt < 40
            for i in range(n):
                o = 4 + 4 * i
                assert math.hypot((b[o] - a[o]) * L, (b[o + 1] - a[o + 1]) * W) / dt < 11.5


def test_v8_opportunity_carries_the_tactical_contract():
    match = _match(engine="v8")
    match.advance(60.0)
    opp = match.opportunity or {}
    tactics = opp.get("tactics") or {}
    for key in ("style", "def_mentality", "def_pressure", "att_mentality", "roles", "instructions", "att_cohesion"):
        assert key in tactics
    assert set(tactics["roles"].values()) <= {"GK", "CB", "FB", "MF", "ST"}


def test_v8_is_deterministic_and_survives_a_snapshot():
    a, b = _match(1, engine="v8"), _match(1, engine="v8")
    a.advance(1e6)
    b.advance(1e6)
    assert a.score == b.score and a.action_log == b.action_log
    c = _match(2, engine="v8")
    c.advance(40.0)
    restored = HighlightMatch.from_dict(c.to_dict())
    c.advance(1e6)
    restored.advance(1e6)
    assert restored.engine == "v8" and c.events == restored.events


# ------------------------------------------------------------------ physics
def test_placed_shot_curls_and_finishes_near_the_aim():
    play, result = _shot("v8", 20, 0, 3.0, 0.6, keeping=10)
    kick = next(c for c in result.cues if c["kind"] == "KICK")
    assert kick
    ys = [row[2] * W for row in result.frames if row[0] > kick["t"]]
    assert len(ys) > 4
    # The ball starts outside the line to the far side and bends back (non-monotonic lateral speed).
    lateral = [b - a for a, b in zip(ys, ys[1:], strict=False)]
    assert max(lateral) * min(lateral) < 0 or abs(lateral[0] - lateral[-1]) > 0.05
    _, straight = _shot("v7", 20, 0, 3.0, 0.6, keeping=10)
    assert result.frames != straight.frames


def test_keeper_low_corner_is_harder_in_v8_never_easier():
    def saves(profile):
        return sum(any(c["kind"] == "SAVE" for c in _shot(profile, 14, -4, 3.2, 0.5, 75, s)[1].cues) for s in range(30))
    assert saves("v8") <= saves("v7")


def test_keeper_v8_never_saves_out_of_reach():
    assert sum(any(c["kind"] in ("SAVE", "CLAIM") for c in _shot("v8", 9, 0, -3.45, 0.95, 90, s)[1].cues) for s in range(30)) == 0


# ------------------------------------------------------------------ tactics change behaviour
def _wide_attack(code: str):
    carrier = _a(7, "A", "MF", 70, 6)
    fb = _a(2, "A", "DF", 55, 5)
    st = _a(9, "A", "ST", 88, 30)
    d1, d2 = _a(4, "D", "DF", 92, 12, defending=70), _a(5, "D", "DF", 92, 34, defending=70)
    gk = _a(1, "D", "GK", L - 1, W / 2, keeping=70)
    bodies = [carrier, fb, st, d1, d2, gk]
    for b in bodies:
        b.ax, b.ay = b.x, b.y
    tactics = {"style": "WIDE", "def_mentality": "BALANCED", "def_pressure": "MEDIUM", "roles": {fb.id: "FB"}, "instructions": {fb.id: code}}
    play = Play(bodies, BallState(carrier.x + 0.4, carrier.y), CFG, random.Random(4), tactics=tactics, profile="v8")
    play.run(carrier.id, "CARRY", 82, 6, 0.6)
    return fb.x


def test_fullback_instruction_changes_the_run():
    assert _wide_attack("OVERLAP") > _wide_attack("STAY_BACK") + 5


def _defence_line(pressure: str) -> float:
    att = [_a(i, "A", "MF" if i < 4 else "ST", 40 + i * 6, 15 + i * 7) for i in range(6)]
    dfn = [_a(10 + i, "D", "DF" if i < 4 else "MF", 70 + (i % 2) * 6, 10 + i * 9) for i in range(6)]
    gk = _a(1, "D", "GK", L - 1, W / 2, keeping=70)
    bodies = att + dfn + [gk]
    for b in bodies:
        b.ax, b.ay = b.x, b.y
    tactics = {"style": "POSSESSION", "def_mentality": "BALANCED", "def_pressure": pressure, "roles": {}, "instructions": {}}
    play = Play(bodies, BallState(att[0].x + 0.4, att[0].y), CFG, random.Random(2), tactics=tactics, profile="v8")
    play.run(att[0].id, "CARRY", att[0].x + 6, att[0].y, 0.3)
    backs = [d for d in dfn if d.role == "DF"]
    return sum(L - d.x for d in backs) / len(backs)      # distance of the back line from its own goal


def test_pressure_moves_the_defensive_block():
    assert _defence_line("HIGH") > _defence_line("LOW") + 3


# ------------------------------------------------------------------ set pieces and keeper restart
def test_free_kick_wall_holds_until_the_kick():
    taker = _a(10, "A", "MF", L - 22, W / 2, shooting=85)
    wall = [_a(20 + i, "D", "DF", L - 22 + 9.15, W / 2 - 1.5 + i * 0.75) for i in range(4)]
    gk = _a(1, "D", "GK", L - 1, W / 2, keeping=70)
    bodies = [taker, *wall, gk]
    for b in bodies:
        b.ax, b.ay = b.x, b.y
    start = [(b.x, b.y) for b in wall]
    play = Play(bodies, BallState(taker.x + 0.4, taker.y), CFG, random.Random(1),
                tactics={"style": "POSSESSION", "def_mentality": "BALANCED", "def_pressure": "MEDIUM", "kind": "FREE_KICK"}, profile="v8")
    assert play.wall == {b.id for b in wall}
    result = play.run(taker.id, "SHOT", L, W / 2 + 2.5, 0.65)
    kick_t = next(c["t"] for c in result.cues if c["kind"] == "KICK")
    before = [row for row in result.frames if row[0] <= kick_t]
    for i, (x0, y0) in enumerate(start):
        o = 4 + 4 * (1 + i)
        assert all(math.hypot(r[o] * L - x0, r[o + 1] * W - y0) < 0.4 for r in before)


def test_keeper_rolls_the_ball_out_after_a_catch():
    for seed in range(40):
        play, result = _shot("v8", 22, 0, 0.2, 0.35, keeping=90, seed=seed, mate=True)
        if result.outcome == "SAVED_HELD":
            assert any(c["kind"] == "THROW" for c in result.cues)
            return
    pytest.fail("no held save in 40 weak central shots")


# ------------------------------------------------------------------ competitions
@pytest.mark.parametrize(("game_mode", "size", "rules"), MODES)
def test_every_mode_finishes_with_v8(monkeypatch, game_mode, size, rules):
    monkeypatch.setattr(get_settings(), "gameplay_engine", "v8")
    room = f"v8-{game_mode}-{size}"
    service, market, clubs, now = new_competition(game_mode, size, {**rules, "execution_mode": "INTERACTIVE", "decision_seconds": 5}, room=room)
    champion, engines = _play(service, market, room, set(clubs[:2]), now, True)
    assert champion in clubs and engines == {"v8"}


def test_every_v8_view_and_snapshot_is_json_serialisable():
    """Regression (found while measuring payloads): a cue carried an Athlete object instead
    of its id, which made the API view and the snapshot of a match with a keeper catch fail."""
    import json
    throws = 0
    for index in range(8):
        match = _match(index % 4, engine="v8")
        match.seed += index * 7919
        original = match._resolve

        def spy(choice, by, at, original=original):
            step = original(choice, by, at)
            json.dumps(step)
            return step
        match._resolve = spy
        now = 0.0
        while not match.finished and now < 3000:
            now += 0.7
            match.advance(now)
            text = json.dumps(match.view(match.clubs[0], now))
            throws += '"THROW"' in text
        json.dumps(match.to_dict())
        throws += '"THROW"' in json.dumps(match.to_dict())
        assert match.finished
    assert throws > 0, "no keeper restart happened: the regression was not exercised"


def test_final_whistle_is_shown_before_the_round_is_recorded(monkeypatch):
    """Regression (found in the 2-browser runs): the round used to be recorded in the same
    tick the match finished, so no screen ever showed the final whistle. Now every client
    sees FINISHED for FINAL_WHISTLE_SECONDS, then the result is recorded (unchanged)."""
    monkeypatch.setattr(get_settings(), "gameplay_engine", "v8")
    room = "whistle"
    service, market, clubs, now = new_competition("DRAFT_KNOCKOUT", 4, {"execution_mode": "INTERACTIVE", "decision_seconds": 5}, room=room)
    humans = set(clubs[:2])
    season = service._season(room)
    season.human_clubs = humans
    for club in sorted(humans):
        if service.preview(room, market, club).get("fixture"):
            service.ready(room, club)
    while not season.live_round:
        service.advance(room, market, humans, 60)
        if not season.live_round:
            now[0] += 301
            service.start_if_preparation_expired(room, market, humans, 300, 60)
    sessions = list(season.highlights.values())
    assert sessions
    for _ in range(40000):
        now[0] += 0.5
        service.advance_highlights(season, now[0])
        if all(x.finished for x in sessions):
            break
    assert all(x.finished for x in sessions)
    whistle = max(float(x.finished_at) for x in sessions)
    session = max(sessions, key=lambda x: float(x.finished_at))
    club = next(c for c in session.clubs if c in humans)
    now[0] = max(whistle + 1.0, float(season.live_round["ends_at"]) + 0.1)
    if now[0] < whistle + service.FINAL_WHISTLE_SECONDS:
        assert service.finish_due(room) is False
        assert service.interactive_view(room, club)["state"] == "FINISHED"
    now[0] = max(whistle + service.FINAL_WHISTLE_SECONDS + 0.5, float(season.live_round["ends_at"]) + 0.1)
    assert service.finish_due(room) is True
    assert all(x.match_id in season.matches and x.match_id not in season.highlights for x in sessions)
