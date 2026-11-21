"""Modo Jogável engine (app.domain.highlights): directions, goals, physics and the state machine."""

from __future__ import annotations

import math
import random

import pytest

from app.domain import highlights as H
from app.domain.highlights import Ball, Body, HighlightMatch, Pitch
from app.domain.market import InitialMarket
from app.services.season_service import SeasonService, team_input_view
from app.tests.fixtures.market_catalog import complete_test_market, synthetic_catalog


def _fixtures(mode: str = "ELEVEN_A_SIDE", n: int = 6):
    clubs = tuple(f"C{i:02}" for i in range(8))
    market = InitialMarket(synthetic_catalog(mode, teams=20), mode, dict.fromkeys(clubs, 1_000_000_000))
    complete_test_market(market, "hl")
    service = SeasonService(clock=lambda: 1000.0)
    service.create("hl", market, double_round_robin=True, rules={"game_mode": "TRADITIONAL"})
    season = service._season("hl")
    out = []
    for fixture in season.state.fixtures[:n]:
        home, away, seed, _ = service._fixture_inputs("hl", market, fixture, set())
        out.append((fixture.id, home, away, seed))
    return out


def _match(index: int = 0, humans: tuple[int, ...] = (), mode: str = "ELEVEN_A_SIDE", seconds: int = 10) -> HighlightMatch:
    mid, home, away, seed = _fixtures(mode)[index]
    clubs = [home.club_code, away.club_code]
    return HighlightMatch.create(mid, mode, home, away, team_input_view(home), team_input_view(away),
                                 [clubs[i] for i in humans], seed, "TRADITIONAL", seconds, False, 0.0)


def _steps(match: HighlightMatch):
    """Every executed action of a full bot match, with the opportunity it belongs to."""
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


# ------------------------------------------------------------------ 1. directions
def test_home_attacks_right_then_left_and_away_the_opposite():
    match = _match()
    home, away = match.clubs
    assert match.attacks_right(0, second_half=False) is True
    assert match.attacks_right(1, second_half=False) is False
    assert match.attacks_right(0, second_half=True) is False
    assert match.attacks_right(1, second_half=True) is True
    view = match.view(None, 0.0)
    assert view["attacks_right"] == {home: True, away: False} and view["half"] == 1


@pytest.mark.parametrize("index", range(4))
def test_every_attack_goes_to_the_rival_goal_and_keepers_stay_in_their_own(index):
    match = _match(index)
    steps = _steps(match)
    halves = {(opp["attacking"], opp["minute"] >= 45) for opp, _ in steps}
    assert len({club for club, _ in halves}) == 2, "both clubs attacked"
    for opp, step in steps:
        side = match.side_of(opp["attacking"])
        right = opp["right"]
        assert right == ((side == 0) != (opp["minute"] >= 45)), "direction follows the club and the half"
        roster = opp["bodies"]
        frame = step["frames"][0]
        for i, body in enumerate(roster):
            if body["role"] != "GK":
                continue
            x = frame[4 + i * 2]
            attackers_keeper = body["team"] == "A"
            # The attacking keeper guards the end the attack comes from; the defending one the end it goes to.
            own_end_right = (not right) if attackers_keeper else right
            assert (x > 0.5) == own_end_right, (opp["id"], body["name"], x, right)
        if step["outcome"] == "GOAL":
            ball_x = step["frames"][-1][1]
            assert (ball_x > 1.0) if right else (ball_x < 0.0), "the goal is scored in the rival's net"


def test_world_conversion_is_applied_once_and_is_its_own_inverse():
    for right in (True, False):
        x, y = HighlightMatch.to_world(0.8, 0.3, right)
        assert HighlightMatch.to_world(x, y, right) == pytest.approx((0.8, 0.3))
    assert HighlightMatch.to_world(0.8, 0.3, False) == pytest.approx((0.2, 0.7))


def _to_decision(match: HighlightMatch, club: str, horizon: float = 400.0) -> float:
    now = 0.0
    while now < horizon:
        now += 0.25
        match.seen(club, now)
        match.advance(now)
        if match.state == "DECISION" and match.opportunity["attacking"] == club:
            return now
    raise AssertionError("no decision for the human club")


@pytest.mark.parametrize("human", [0, 1])
def test_a_human_gesture_is_read_on_the_real_pitch(human):
    """A shot drawn towards the rival goal (on screen) is a shot at the rival goal, whichever
    the side and the half; the same drawn towards the own goal goes away from the rival goal."""
    match = _match(humans=(human,), seconds=20)
    club = match.clubs[human]
    now = _to_decision(match, club)
    opp = match.opportunity
    right = opp["right"]
    carrier_index = next(i for i, b in enumerate(opp["bodies"]) if b["id"] == opp["carrier"])
    cx, cy = match.view(club, now)["opportunity"]["positions"][carrier_index]
    rival_goal_x = 1.0 if right else 0.0
    result = match.submit(club, {"action_id": "test-action-1", "opportunity_id": opp["id"], "revision": match.revision,
                                 "type": "SHOT", "x": rival_goal_x, "y": 0.5, "power": 0.8}, now)
    assert result["status"] == "ACCEPTED"
    frames = match.opportunity["last"]["frames"]
    assert (frames[-1][1] - cx) * (1 if right else -1) > 0, "the ball travelled towards the rival goal"
    # Same gesture again (idempotency): not applied twice.
    assert match.submit(club, {"action_id": "test-action-1"}, now)["status"] == "DUPLICATE"


def test_a_shot_at_the_own_goal_never_scores_for_the_attacker():
    match = _match(humans=(0,), seconds=20)
    club = match.clubs[0]
    now = _to_decision(match, club)
    opp = match.opportunity
    own_goal_x = 0.0 if opp["right"] else 1.0
    before = list(match.score)
    match.submit(club, {"action_id": "own-goal-try", "opportunity_id": opp["id"], "revision": match.revision,
                        "type": "SHOT", "x": own_goal_x, "y": 0.5, "power": 1.0}, now)
    assert match.score == before


# ------------------------------------------------------------------ 2. goal and keeper
def _body(id_: str, team: str, role: str, x: float, y: float, **attrs: float) -> Body:
    base = dict(pace=70, passing=70, shooting=70, dribbling=70, defending=70, physical=70, keeping=70)
    base.update(attrs)
    return Body(id_, id_, 9, team, role, x, y, **base)


def _pitch(bodies, ball, seed=1):
    return Pitch(bodies, ball, "ELEVEN_A_SIDE", random.Random(seed))


GOAL = H.HL_PITCH["ELEVEN_A_SIDE"]["goal"]
BAR = H.HL_PITCH["ELEVEN_A_SIDE"]["goal_height"]


def test_regulation_dimensions_are_the_drawn_dimensions():
    view = _match().view(None, 0.0)
    assert view["pitch"]["length"] == 105 and view["pitch"]["width"] == 68
    assert view["pitch"]["goal"] == 7.32 and view["pitch"]["goal_height"] == 2.44
    five = _match(mode="FIVE_A_SIDE").view(None, 0.0)
    assert (five["pitch"]["length"], five["pitch"]["width"], five["pitch"]["goal"], five["pitch"]["goal_height"]) == (50, 32, 4.0, 2.0)


def _shot(target_y: float, power: float, seed: int, shooting: float = 99, keeper_y: float = 2.0, distance: float = 12):
    L, W = 105.0, 68.0
    shooter = _body("s", "A", "ST", L - distance, W / 2, shooting=shooting)
    keeper = _body("k", "D", "GK", L - 1, keeper_y, keeping=1)
    pitch = _pitch([shooter, keeper], Ball(shooter.x + 0.4, shooter.y), seed)
    return pitch.execute(shooter, "SHOT", L, target_y, power, None)


def test_a_low_shot_inside_the_mouth_scores_and_outside_misses():
    W = 68.0
    inside = sum(_shot(W / 2 + GOAL / 2 - 0.9, 0.4, seed).outcome == "GOAL" for seed in range(12))
    outside = sum(_shot(W / 2 + GOAL / 2 + 1.5, 0.4, seed).outcome == "GOAL" for seed in range(12))
    assert inside >= 9 and outside == 0


def test_hard_shots_can_go_over_the_bar_or_hit_it():
    results = [_shot(68 / 2, 1.0, seed, shooting=40, distance=24) for seed in range(40)]
    over = sum(r.detail == "Por cima do gol" for r in results)
    bar = sum(any(c["kind"] == "BAR" for c in r.cues) for r in results)
    assert over + bar >= 3
    # A goal is never given for a ball that crossed the line above the bar.
    for r in results:
        if r.outcome == "GOAL":
            assert r.frames[-1][3] <= BAR


def test_the_post_sends_the_ball_back_into_play():
    L, W = 105.0, 68.0
    post_y = W / 2 + GOAL / 2 + 0.05
    hits = 0
    for seed in range(20):
        shooter = _body("s", "A", "ST", L - 6, post_y, shooting=99)
        mate = _body("m", "A", "MF", L - 14, W / 2 - 4)
        keeper = _body("k", "D", "GK", L - 1, 4.0, keeping=1)
        pitch = _pitch([shooter, mate, keeper], Ball(shooter.x + 0.4, shooter.y), seed)
        result = pitch.execute(shooter, "SHOT", L, post_y, 0.3, None)
        if result.post:
            hits += 1
            assert any(c["kind"] in ("POST", "BAR") for c in result.cues)
    assert hits >= 3


def test_the_keeper_is_physical_and_saves_a_central_shot():
    L, W = 105.0, 68.0
    saves = 0
    for seed in range(20):
        shooter = _body("s", "A", "ST", L - 20, W / 2)
        keeper = _body("k", "D", "GK", L - 1.2, W / 2, keeping=85)
        pitch = _pitch([shooter, keeper], Ball(shooter.x + 0.4, shooter.y), seed)
        result = pitch.execute(shooter, "SHOT", L, W / 2, 0.3, None)
        saves += result.outcome != "GOAL"
    assert saves >= 15


# ------------------------------------------------------------------ 3. carrying
def _carry_distance(pace: float, dribbling: float, seconds_cap: float = 1.5) -> float:
    carrier = _body("c", "A", "MF", 40, 34, pace=pace, dribbling=dribbling)
    keeper = _body("k", "D", "GK", 104, 34)
    pitch = _pitch([carrier, keeper], Ball(40.4, 34))
    result = pitch.execute(carrier, "CARRY", 80, 34, 1.0, None)
    t_index = min(len(result.frames) - 1, int(seconds_cap / H.DT))
    return (result.frames[t_index][4] - result.frames[0][4]) * 105


def test_fast_players_carry_faster_and_carrying_is_quick():
    slow, fast = _carry_distance(40, 70), _carry_distance(95, 70)
    assert fast > slow * 1.12
    assert slow > 6.0, "1.5 s of carrying covers real ground"


def test_good_dribblers_keep_the_ball_closer():
    def max_gap(dribbling):
        carrier = _body("c", "A", "MF", 40, 34, dribbling=dribbling)
        pitch = _pitch([carrier, _body("k", "D", "GK", 104, 34)], Ball(40.4, 34))
        result = pitch.execute(carrier, "CARRY", 52, 34, 1.0, None)
        return max(abs(f[1] - f[4]) * 105 for f in result.frames[1:])
    assert max_gap(95) < max_gap(30)


def test_no_loss_of_the_ball_without_contact():
    carrier = _body("c", "A", "MF", 40, 34, dribbling=20)
    far = _body("d", "D", "DF", 40, 4)
    pitch = _pitch([carrier, far, _body("k", "D", "GK", 104, 34)], Ball(40.4, 34))
    result = pitch.execute(carrier, "CARRY", 52, 34, 1.0, None)
    assert result.outcome == "CONTROLLED"


# ------------------------------------------------------------------ 4. passing, crosses, rebounds
def test_pass_assistance_finds_the_team_mate_near_the_line():
    received = 0
    for seed in range(12):
        passer = _body("p", "A", "MF", 40, 34, passing=80)
        mate = _body("m", "A", "MF", 55, 37.5)
        keeper = _body("k", "D", "GK", 104, 34)
        pitch = _pitch([passer, mate, keeper], Ball(40.4, 34), seed)
        # Drawn ~13 degrees off the team-mate.
        result = pitch.execute(passer, "PASS", 55, 34, 0.45, None)
        received += result.receiver == "m"
    assert received >= 10


def test_crosses_can_be_headed():
    headers = 0
    for seed in range(30):
        crosser = _body("c", "A", "MF", 95, 6, passing=85)
        striker = _body("s", "A", "ST", 96, 34, physical=90)
        defender = _body("d", "D", "DF", 99, 37, physical=60)
        keeper = _body("k", "D", "GK", 104, 34)
        pitch = _pitch([crosser, striker, defender, keeper], Ball(95.4, 6), seed)
        result = pitch.execute(crosser, "LOFT", 96, 34, 0.35, None)
        headers += any(c["kind"] == "HEADER" for c in result.cues)
    assert headers >= 8


def test_a_parried_shot_can_stay_with_the_attack():
    kept = 0
    for seed in range(60):
        shooter = _body("s", "A", "ST", 92, 34)
        follow = _body("f", "A", "ST", 96, 31, pace=95)
        keeper = _body("k", "D", "GK", 103.8, 34, keeping=99)
        pitch = _pitch([shooter, follow, keeper], Ball(92.4, 34), seed)
        result = pitch.execute(shooter, "SHOT", 105, 34.5, 0.5, None)
        kept += result.outcome == "CONTROLLED" and result.shot
    assert kept >= 1


# ------------------------------------------------------------------ 5. state machine, determinism, snapshot
def test_same_seed_same_match_and_snapshot_round_trip():
    a, b = _match(2), _match(2)
    a.advance(1e6)
    b.advance(1e6)
    assert a.score == b.score and a.action_log == b.action_log
    c = _match(3)
    c.advance(40.0)
    restored = HighlightMatch.from_dict(c.to_dict())
    c.advance(1e6)
    restored.advance(1e6)
    assert restored.score == c.score and restored.action_log == c.action_log


def test_disconnected_coach_gets_grace_then_the_ai_plays():
    match = _match(humans=(0,), seconds=10)
    club = match.clubs[0]
    now = _to_decision(match, club)
    # The coach stops polling: frozen decision, 30 s grace, then the AI.
    match.advance(now + H.CONNECTED_WINDOW + 1)
    assert match.grace_until is not None and match.deadline is None
    match.advance(match.grace_until + 0.1)
    assert club in match.ai_control
    match.advance(1e6)
    assert match.finished


@pytest.mark.parametrize("mode", ["ELEVEN_A_SIDE", "FIVE_A_SIDE"])
def test_ai_vs_ai_scores_are_football_like(mode):
    goals = []
    for index in range(6):
        match = _match(index, mode=mode)
        match.advance(1e6)
        goals.append(sum(match.score))
    assert 0.5 <= sum(goals) / len(goals) <= 5.0
    assert all(g <= 10 for g in goals)


def test_view_coordinates_are_on_the_real_pitch():
    match = _match(humans=(1,), seconds=20)
    club = match.clubs[1]
    now = _to_decision(match, club)
    view = match.view(club, now)
    opp = view["opportunity"]
    assert opp["right"] == match.attacks_right(1)
    i = next(i for i, p in enumerate(opp["roster"]) if p["role"] == "GK" and p["team"] == "D")
    keeper_x = opp["positions"][i][0]
    assert (keeper_x > 0.5) == opp["right"], "the defending keeper is in the goal being attacked"
    assert math.isclose(view["pitch"]["goal"], 7.32, abs_tol=1e-3)
    kits = view["kits"]
    assert {"home", "away", "home_gk", "away_gk"} <= set(kits)


# ------------------------------------------------------------------ 6. gameplay lab (isolated scenarios)
@pytest.mark.parametrize("kind", ["BUILDUP", "CROSS", "FREE_KICK", "PENALTY", "ONE_ON_ONE", "REBOUND"])
def test_lab_scenarios_reach_a_decision_and_play_on_the_same_engine(kind):
    from app.domain.demo_catalog import create_demo_catalog
    from app.services.lab_service import LabService

    clock = [1000.0]
    lab = LabService(clock=lambda: clock[0])
    catalog = create_demo_catalog()
    created = lab.create("u1", catalog, "ELEVEN_A_SIDE", kind, "", "", 3)
    sid = created["id"]
    view = lab.view("u1", sid, None)
    for _ in range(40):
        if view["state"] == "DECISION":
            break
        clock[0] += 0.25
        view = lab.view("u1", sid, None)
    assert view["state"] == "DECISION" and view["your_turn"]
    opp = view["opportunity"]
    assert opp["kind"] == kind and opp["right"] is True
    result = lab.act("u1", sid, {"action_id": f"lab-{kind}", "opportunity_id": opp["id"], "revision": view["revision"],
                                 "type": "SHOT", "x": 1.0, "y": 0.5, "power": 0.7})
    assert result["status"] == "ACCEPTED"
    with pytest.raises(KeyError):
        lab.view("someone-else", sid, None)


# ------------------------------------------------------------------ 7. kits (official selection, shared by 2D and 3D)
from app.domain import kits as K  # noqa: E402


@pytest.mark.parametrize("home,away", [("COR", "SAN"), ("FLA", "CAP"), ("CRU", "REM"), ("PAL", "CFC"), ("PAL", "CHA"),
                                       ("BOT", "VAS"), ("SAO", "RBB"), ("INT", "VIT"), ("XXX", "YYY"), ("FLA", "FLA")])
def test_kits_never_clash(home, away):
    chosen = K.select_kits(home, away)
    h, a = K.Kit(**chosen["home"]), K.Kit(**chosen["away"])
    assert not K.clash(h, a)
    assert K.delta_e(h.shirt, a.shirt) >= K.SHIRT_MIN
    shirts = [h.shirt, a.shirt]
    for gk in ("home_gk", "away_gk"):
        assert min(K.delta_e(chosen[gk]["shirt"], x) for x in shirts) >= K.KEEPER_MIN - 3
    assert K.delta_e(chosen["home_gk"]["shirt"], chosen["away_gk"]["shirt"]) >= 15


def test_every_club_pair_gets_distinguishable_kits():
    clubs = list(K.CLUB_COLORS)
    for h in clubs:
        for a in clubs:
            if h != a:
                chosen = K.select_kits(h, a)
                assert not K.clash(K.Kit(**chosen["home"]), K.Kit(**chosen["away"])), (h, a)


def test_alternative_kits_are_labelled_generic_and_white_vs_white_changes():
    chosen = K.select_kits("COR", "SAN")      # both white home shirts
    assert chosen["away"]["id"] != "HOME" and chosen["away"]["generic"] is True
    assert K.delta_e("#FFFFFF", "#F4F4F4") < 5    # sanity: perceptual distance, not hex


def test_the_match_carries_one_official_kit_selection():
    match = _match()
    restored = HighlightMatch.from_dict(match.to_dict())
    assert match.view(None, 0.0)["kits"] == restored.view(None, 0.0)["kits"] == K.select_kits(*match.clubs)


def test_lab_second_half_flips_the_direction_and_kits_follow_the_clubs():
    from app.domain.demo_catalog import create_demo_catalog
    from app.services.lab_service import LabService

    clock = [1000.0]
    lab = LabService(clock=lambda: clock[0])
    catalog = create_demo_catalog()
    clubs = sorted({p.club_code for p in catalog.players})
    created = lab.create("u1", catalog, "FIVE_A_SIDE", "BUILDUP", clubs[0], clubs[1], 3, second_half=True)
    view = lab.view("u1", created["id"], None)
    for _ in range(40):
        if view["state"] == "DECISION":
            break
        clock[0] += 0.25
        view = lab.view("u1", created["id"], None)
    assert view["state"] == "DECISION" and view["half"] == 2
    assert view["opportunity"]["right"] is False                  # home attacks to the left after the break
    assert view["kits"] == K.select_kits(clubs[0], clubs[1])
    assert view["pitch"]["length"] == 50


# ------------------------------------------------------------------ 8. movement realism (V6)
def test_fast_players_accelerate_faster():
    def after(pace: float) -> float:
        body = _body("r", "A", "MF", 30, 34, pace=pace)
        pitch = _pitch([body, _body("k", "D", "GK", 104, 34)], Ball(10, 10))
        for _ in range(8):
            pitch._steer(body, 80, 34)
        return body.x - 30
    assert after(95) > after(40) * 1.15


def test_the_passer_goes_again_after_a_pass():
    passer = _body("p", "A", "MF", 50, 34)
    mate = _body("m", "A", "MF", 60, 34)
    defender = _body("d", "D", "DF", 56, 40)
    bodies = [passer, mate, defender, _body("k", "D", "GK", 104, 34)]
    for body in bodies:
        body.ax, body.ay = body.x, body.y
    pitch = _pitch(bodies, Ball(50.4, 34), 3)
    result = pitch.execute(passer, "PASS", 60, 34, 0.4, None)
    assert result.receiver == "m"
    assert passer.x - 50 > 1.0, "the passer kept running forward (give-and-go)"


def test_tactics_change_the_runs():
    def striker_x(style: str) -> float:
        st = _body("s", "A", "ST", 70, 34)
        mf = _body("c", "A", "MF", 55, 30)
        dfs = [_body(f"d{i}", "D", "DF", 88, 20 + i * 10) for i in range(3)]
        bodies = [st, mf, *dfs, _body("k", "D", "GK", 104, 34)]
        for body in bodies:
            body.ax, body.ay = body.x, body.y
        pitch = Pitch(bodies, Ball(55.4, 30), "ELEVEN_A_SIDE", random.Random(1), 0.0, {"style": style})
        for step in range(40):
            pitch.move_players(step * 0.1 + 0.1, mf, None, set(), {})
        return st.x
    assert striker_x("COUNTER") > striker_x("POSSESSION") + 1.0
