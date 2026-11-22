"""Football Engine V7 (app.domain.football): physics, keeper, AI, contract and integration.

These are verifiable properties (no teleport, physical limits, determinism, a keeper
that never saves the impossible...). They do NOT prove the game is fun — that needs the
owner's playtest (docs/v7/RELATORIO_FINAL.md).
"""

from __future__ import annotations

import math
import random

import pytest

from app.domain import football
from app.domain.football.play import Play
from app.domain.football.world import (
    DT,
    MAX_ACCEL,
    Athlete,
    BallState,
    ball_step,
    move,
    pass_reach,
    solve_loft,
)
from app.domain.highlights import HL_PITCH, HighlightMatch
from app.domain.market import InitialMarket
from app.services.season_service import SeasonService, team_input_view
from app.tests.fixtures.market_catalog import complete_test_market, synthetic_catalog

CFG = HL_PITCH["ELEVEN_A_SIDE"]


def _fixtures(mode: str = "ELEVEN_A_SIDE", n: int = 4):
    clubs = tuple(f"C{i:02}" for i in range(8))
    market = InitialMarket(synthetic_catalog(mode, teams=20), mode, dict.fromkeys(clubs, 1_000_000_000))
    complete_test_market(market, "v7")
    service = SeasonService(clock=lambda: 1000.0)
    service.create("v7", market, double_round_robin=True, rules={"game_mode": "TRADITIONAL"})
    season = service._season("v7")
    out = []
    for fixture in season.state.fixtures[:n]:
        home, away, seed, _ = service._fixture_inputs("v7", market, fixture, set())
        out.append((fixture.id, home, away, seed))
    return out


def _match(index: int = 0, humans: tuple[int, ...] = (), mode: str = "ELEVEN_A_SIDE", engine: str = "v7") -> HighlightMatch:
    mid, home, away, seed = _fixtures(mode)[index]
    clubs = [home.club_code, away.club_code]
    return HighlightMatch.create(mid, mode, home, away, team_input_view(home), team_input_view(away),
                                 [clubs[i] for i in humans], seed, "TRADITIONAL", 10, False, 0.0, engine=engine)


def _steps(match: HighlightMatch):
    seen = []
    original = match._resolve

    def spy(choice, by, at):
        step = original(choice, by, at)
        seen.append((dict(match.opportunity), step))
        return step

    match._resolve = spy
    match.advance(1e6)
    assert match.finished
    return seen


def _athlete(i, team, role, x, y, pace=75, keeping=20):
    return Athlete(f"{team}{i}", f"{team}{i}", i, team, role, x, y, pace, 70, 70, 70, 60, 70, keeping)


# ------------------------------------------------------------------ locomotion
def test_locomotion_respects_acceleration_turning_and_top_speed():
    body = _athlete(1, "A", "MF", 0.0, 30.0, pace=90)
    body.tx, body.ty, body.intensity = 40.0, 30.0, 1.0
    prev = (0.0, 0.0)
    t = 0.0
    for k in range(400):
        t += DT
        if k == 120:
            body.tx, body.ty = body.x, 5.0     # sharp change of mind at full speed
        move(body, t)
        accel = math.hypot(body.vx - prev[0], body.vy - prev[1]) / DT
        assert accel <= MAX_ACCEL + 1e-6, f"step {k}: {accel:.2f} m/s²"
        assert body.speed <= body.top_speed + 1e-6
        prev = (body.vx, body.vy)


def test_arrive_stops_on_target_without_overshooting():
    body = _athlete(1, "A", "MF", 0.0, 0.0)
    body.tx, body.ty, body.intensity = 12.0, 0.0, 1.0
    for k in range(240):
        move(body, k * DT)
    assert abs(body.x - 12.0) < 0.35 and body.speed < 0.3


# ------------------------------------------------------------------ ball
def test_ball_rolls_slows_and_stops_with_the_documented_physics():
    assert 10 < pass_reach(8.0) < 12 and 60 < pass_reach(26.0) < 66
    ball = BallState(0.0, 0.0, 0.0, 15.0, 0.0, 0.0)
    xs = []
    for _ in range(400):
        ball_step(ball)
        xs.append(ball.x)
    assert all(b >= a for a, b in zip(xs, xs[1:], strict=False))   # never goes backwards
    assert ball.ground_speed < 0.06


def test_lofted_ball_lands_where_the_solver_says():
    for distance, angle in ((15.0, 0.9), (30.0, 0.7), (50.0, 0.62)):
        v0 = solve_loft(distance, angle)
        ball = BallState(0.0, 0.0, 0.0, v0 * math.cos(angle), 0.0, v0 * math.sin(angle))
        landed = None
        for _ in range(600):
            vz = ball.vz
            ball_step(ball)
            if ball.z == 0.0 and vz < 0:
                landed = ball.x
                break
        assert landed is not None and abs(landed - distance) < 0.6


# ------------------------------------------------------------------ actions on a real match
def test_v7_frames_have_facing_and_action_state_and_no_teleport():
    match = _match()
    steps = _steps(match)
    assert steps
    L, W = CFG["length"], CFG["width"]
    for opp, step in steps:
        assert step["layout"] == "v7"
        n = len(opp["bodies"])
        for row in step["frames"]:
            assert len(row) == 4 + 4 * n
        for a, b in zip(step["frames"], step["frames"][1:], strict=False):
            dt = b[0] - a[0]
            assert 0.0 < dt <= 0.1 + 1e-6
            ball_v = math.hypot((b[1] - a[1]) * L, (b[2] - a[2]) * W) / dt
            assert ball_v < 40, f"ball jumped {ball_v:.1f} m/s"
            for i in range(n):
                o = 4 + 4 * i
                v = math.hypot((b[o] - a[o]) * L, (b[o + 1] - a[o + 1]) * W) / dt
                assert v < 11.5, f"athlete jumped {v:.1f} m/s"


def test_kick_has_a_windup_before_the_ball_leaves():
    match = _match()
    steps = _steps(match)
    kicks = [c for _, s in steps for c in s["cues"] if c["kind"] == "KICK"]
    assert kicks and all(c["t"] >= 0.12 for c in kicks)


def test_reception_keeps_the_receiver_moving():
    """A completed pass ends with the receiver in control AND still moving (no freeze on contact)."""
    match = _match()
    moving = []
    for opp, step in _steps(match):
        if step["type"] == "PASS" and step["outcome"] == "CONTROLLED":
            body = next(b for b in opp["bodies"] if b["id"] == step["receiver"])
            moving.append(math.hypot(body["vx"], body["vy"]))
    assert moving and sum(1 for v in moving if v > 1.0) / len(moving) > 0.5


def test_same_seed_same_match_and_snapshot_round_trip():
    a, b = _match(1), _match(1)
    a.advance(1e6)
    b.advance(1e6)
    assert a.score == b.score and a.action_log == b.action_log
    c = _match(2)
    c.advance(40.0)
    restored = HighlightMatch.from_dict(c.to_dict())
    assert restored.engine == "v7"
    c.advance(1e6)
    restored.advance(1e6)
    assert c.score == restored.score and c.events == restored.events


def test_v6_matches_still_use_v6():
    match = _match(engine="v6")
    steps = _steps(match)
    assert steps and all(s.get("layout") == "v6" for _, s in steps)


@pytest.mark.parametrize("mode", ["ELEVEN_A_SIDE", "FIVE_A_SIDE"])
def test_v7_full_matches_finish_with_coherent_stats(mode):
    for i in range(3):
        match = _match(i, mode=mode)
        match.advance(1e6)
        assert match.finished
        for club in match.clubs:
            st = match.stats[club]
            assert st["shots_on_target"] <= st["shots"]
            assert st["passes_completed"] <= st["passes"]
        goals = [e for e in match.events if e["kind"] == "GOAL"]
        assert len(goals) == sum(match.score)


# ------------------------------------------------------------------ human control on V7
def test_human_gesture_is_executed_once_and_duplicates_are_ignored():
    # The human home side reaches its first decision (connected, polling).
    match = _match(humans=(0,))
    now = 0.0
    while match.state != "DECISION" and now < 400:
        now += 0.5
        match.seen(match.clubs[0], now)
        match.advance(now)
    assert match.state == "DECISION"
    opp = match.opportunity
    carrier = next(b for b in opp["bodies"] if b["id"] == opp["carrier"])
    right = bool(opp["right"])
    x, y = HighlightMatch.to_world(min(1.0, (carrier["x"] + 12) / CFG["length"]), carrier["y"] / CFG["width"], right)
    payload = {"action_id": "act-000001", "opportunity_id": opp["id"], "revision": match.revision, "type": "PASS", "x": x, "y": y, "power": 0.4}
    first = match.submit(match.clubs[0], payload, now)
    again = match.submit(match.clubs[0], payload, now)
    assert first["status"] == "ACCEPTED" and again["status"] == "DUPLICATE"
    assert len(match.action_log) == 1 and match.action_log[0]["by"] == "HUMAN"


# ------------------------------------------------------------------ goalkeeper battery
def _shot(distance, offset, aim, power, keeping, seed):
    L, W = CFG["length"], CFG["width"]
    shooter = _athlete(9, "A", "ST", L - distance, W / 2 + offset)
    keeper = _athlete(1, "D", "GK", L - 1.0, W / 2, pace=50, keeping=keeping)
    keeper.facing = math.pi
    for b in (shooter, keeper):
        b.ax, b.ay = b.x, b.y
    return Play([shooter, keeper], BallState(shooter.x + 0.4, shooter.y), CFG, random.Random(seed)).run(shooter.id, "SHOT", L, W / 2 + aim, power)


def _saves(result) -> bool:
    return any(c["kind"] in ("SAVE", "CLAIM") for c in result.cues)


def test_keeper_saves_reachable_shots_and_never_the_impossible():
    reachable = sum(_saves(_shot(15, 0, 0.3, 0.25, 75, s)) for s in range(30))
    impossible = sum(_saves(_shot(9, 0, -3.45, 0.95, 90, s)) for s in range(30))
    assert reachable >= 26
    assert impossible == 0


def test_keeper_quality_matters_on_corner_shots():
    weak = sum(_shot(16, 0, -3.0, 0.75, 55, s).outcome == "GOAL" for s in range(40))
    strong = sum(_shot(16, 0, -3.0, 0.75, 90, s).outcome == "GOAL" for s in range(40))
    assert weak > strong


def test_keeper_dive_is_a_real_displacement():
    result = _shot(16, 0, 3.0, 0.75, 75, 3)
    dives = [c for c in result.cues if c["kind"] == "DIVE"]
    assert dives
    gk = 1   # roster: shooter, keeper
    ys = [row[5 + 4 * gk] * CFG["width"] for row in result.frames]
    assert max(ys) - min(ys) > 1.0   # he really flew sideways (metres), not a pose only


# ------------------------------------------------------------------ lab
def test_lab_drill_and_full_match_sessions():
    from app.domain.catalog import PlayerCatalog
    from app.services.lab_service import LabService
    from app.tests.fixtures.market_catalog import synthetic_catalog as cat

    lab = LabService(clock=lambda: 100.0)
    base = cat("ELEVEN_A_SIDE", teams=2)
    players = list(base.players) + [p.model_copy(update={"id": f"pal-{p.id}", "club_code": "PAL"}) for p in base.players]
    catalog = PlayerCatalog(catalog_version="test", source="test-fixture", source_version="1", players=players)
    clubs = sorted({p.club_code for p in catalog.players})
    drill = lab.create("u", catalog, "ELEVEN_A_SIDE", "DRILL_1V_GK", clubs[0], clubs[1], 3, engine="v7")
    roster = drill["match"]["opportunity"]["roster"] if drill["match"]["opportunity"] else None
    session = lab.sessions[drill["id"]].match
    assert session.engine == "v7" and len(session.timeline) == 1
    full = lab.create("u", catalog, "ELEVEN_A_SIDE", "MATCH", clubs[0], clubs[1], 3)
    assert len(lab.sessions[full["id"]].match.timeline) >= 2
    with pytest.raises(ValueError):
        lab.create("u", catalog, "ELEVEN_A_SIDE", "DRILL_2V1", clubs[0], clubs[1], 3, engine="v6")
    assert roster is None or len(roster) <= 3


def test_opening_drill_keeps_only_the_drill_players():
    _, home, away, _ = _fixtures()[0]
    from dataclasses import asdict

    from app.domain.highlights import build_scenario
    bodies, _, carrier = build_scenario("BUILDUP", home, away, "ELEVEN_A_SIDE", random.Random(1))
    kept, carrier = football.opening([asdict(b) for b in bodies], carrier, "DRILL_3V2", CFG, random.Random(1))
    teams = [b["team"] for b in kept]
    assert teams.count("A") == 3 and teams.count("D") == 3   # 2 defenders + keeper
