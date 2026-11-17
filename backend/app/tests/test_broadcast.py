"""Condensed live broadcast: duration setting, timeline, motion and multiplayer rules."""

import copy
import math

import pytest
from fastapi.testclient import TestClient

from app.api import routes
from app.domain.bot_coach import advance_with_bots
from app.domain.broadcast import DURATIONS, MIN_BUILD, PROFILES, Director
from app.domain.clubs import CLUBS
from app.domain.market import InitialMarket, MarketError
from app.domain.match_engine import (
    FULL_TIME_TICK,
    TICKS_PER_HALF,
    MatchEngine,
    PlayerInput,
    TeamInput,
)
from app.domain.tactics import Tactics
from app.main import create_app
from app.services.auth import SESSION_COOKIE, issue_guest_token
from app.services.season_service import SeasonService
from app.tests.fixtures.market_catalog import complete_test_market, synthetic_catalog

T0 = 1_900_000_000.0
TOLERANCE = 0.05  # seconds: the final whistle is planned exactly on the deadline


def team(code: str, mode: str, strength: int) -> TeamInput:
    eleven = mode == "ELEVEN_A_SIDE"
    roles = ["GK", "DF", "DF", "DF", "DF", "MF", "MF", "MF", "ST", "ST", "ST"] if eleven else ["GK", "DF", "MF", "ST", "ST"]
    xs = [50, 15, 38, 62, 85, 25, 50, 75, 20, 50, 80] if eleven else [50, 30, 50, 30, 70]
    ys = [92, 72, 75, 75, 72, 50, 52, 50, 22, 18, 22] if eleven else [92, 70, 50, 22, 22]
    attributes = {"pace": strength, "shooting": strength - 5, "passing": strength, "dribbling": strength, "defending": strength, "physical": strength}
    starters = tuple(PlayerInput(f"{code}{i}", f"{code} {i}", role, role, xs[i], ys[i], strength, attributes, i + 1) for i, role in enumerate(roles))
    bench = tuple(PlayerInput(f"{code}b{i}", f"{code} reserva {i}", role, role, 50, 50, strength - 3, attributes, 12 + i) for i, role in enumerate(["DF", "MF", "ST", "MF", "GK"][: 5 if eleven else 3]))
    return TeamInput(code, "4-3-3" if eleven else "2-1-1", starters, bench, Tactics())


def run_broadcast(duration: int, mode: str = "ELEVEN_A_SIDE", seed: int = 7, step: float = 0.25, strengths=(72, 66)):
    engine = MatchEngine("m", mode, team("AAA", mode, strengths[0]), team("BBB", mode, strengths[1]), seed)
    engine.enable_snapshots()
    director = Director(T0, duration)
    base = (engine.inputs[0].tactics, engine.inputs[1].tactics)
    now = T0
    observed = []
    engine.all_frames = {}  # the engine keeps only recent frames; the test keeps them all
    while not director.complete:
        director.plan(engine, lambda tick: advance_with_bots(engine, tick, (0, 1), base), now)
        for row in engine.frames_between(max(engine.all_frames, default=-1), engine.tick):
            engine.all_frames[row["t"]] = row
        shown = director.shown_tick(now)
        observed.append((now, shown, engine.tick))
        engine.prune_snapshots(shown - 30)
        now += step
        assert now < T0 + duration + 5, "the broadcast must end by its deadline"
    return engine, director, observed


@pytest.mark.parametrize("duration", DURATIONS)
@pytest.mark.parametrize("mode", ["ELEVEN_A_SIDE", "FIVE_A_SIDE"])
def test_each_duration_ends_on_time_and_shows_every_goal(duration, mode):
    engine, director, observed = run_broadcast(duration, mode)
    segments = director.segments
    # 1–3, 8: real length = the configured duration, within a documented tolerance.
    assert abs(segments[-1]["r1"] - (T0 + duration)) <= TOLERANCE
    assert segments[0]["r0"] == T0 and segments[-1]["t1"] == FULL_TIME_TICK and engine.finished
    # The timeline is contiguous and never runs backwards (one clock for everyone).
    for previous, current in zip(segments, segments[1:], strict=False):
        assert current["r0"] == pytest.approx(previous["r1"]) and current["t0"] == previous["t1"]
        assert current["r1"] >= current["r0"] and current["t1"] >= current["t0"]
    # 9: virtual clock — 90 minutes are covered, half time is a real break with the clock stopped.
    half = next(s for s in segments if s["label"] == "HALF_TIME")
    assert half["k"] == "BREAK" and half["t0"] == half["t1"] == TICKS_PER_HALF
    assert half["r1"] - half["r0"] == pytest.approx(PROFILES[duration].halftime)
    shown = [tick for _, tick, _ in observed]
    assert shown == sorted(shown)
    # The engine is never behind the screen, and stays well within its 1200-frame history.
    assert all(frontier >= tick and frontier - tick <= 1000 for _, tick, frontier in observed)
    # Every goal is shown as football, not skipped in a cut.
    goals = [e for e in engine.events if e["kind"] == "GOAL"]
    for goal in goals:
        assert any(s["k"] == "PLAY" and s["t0"] <= goal["tick"] <= s["t1"] for s in segments), goal
    # 4 (presentation): highlights play near real speed, not 30–60× as before.
    play = [s for s in segments if s["k"] == "PLAY" and s["r1"] > s["r0"]]
    speed = sum(s["t1"] - s["t0"] for s in play) / sum(s["r1"] - s["r0"] for s in play)
    assert 1.0 <= speed <= (3.0 if mode == "ELEVEN_A_SIDE" else 4.0)


def test_longer_matches_show_more_football():
    shown = {}
    for duration in DURATIONS:
        _, director, _ = run_broadcast(duration, seed=11)
        shown[duration] = sum(s["t1"] - s["t0"] for s in director.segments if s["k"] == "PLAY")
    assert shown[90] < shown[120] < shown[180]


def teammates_on_ball(frames: dict, home_count: int, side: int, first: int, last: int) -> set[int]:
    return {frames[t]["b"][2] for t in range(first, last + 1)
            if t in frames and frames[t]["b"][2] >= 0 and (frames[t]["b"][2] < home_count) == (side == 0)}


def test_goal_highlights_show_the_build_up_and_the_ball_moving_between_teammates():
    built, buildups, total = 0, 0, 0
    for seed in range(1, 7):
        engine, director, _ = run_broadcast(120, seed=seed)
        frames = engine.all_frames
        home_count = len(engine.team_agents[0])
        segments = director.segments
        for shot in (e for e in engine.events if e["kind"] == "SHOT" and e["outcome"] == "GOAL"):
            index = next(i for i, s in enumerate(segments) if s["k"] == "PLAY" and s["t0"] <= shot["tick"] <= s["t1"])
            while index > 0 and segments[index - 1]["k"] == "PLAY":
                index -= 1  # start of the continuous stretch of football that ends in the goal
            start = segments[index]["t0"]
            total += 1
            # 14: never out of nowhere — at least MIN_BUILD ticks of real play lead to the goal…
            assert shot["tick"] - start >= min(MIN_BUILD, shot["tick"] - (TICKS_PER_HALF if shot["tick"] > TICKS_PER_HALF else 0))
            # …and the attack is shown from where it began (up to the profile's build-up length).
            wanted = max(int(shot["possession_since"]) - 2, shot["tick"] - PROFILES[120].max_build)
            assert start <= max(wanted, segments[index - 1]["t1"] if index else 0)
            side = 0 if shot["team"] == engine.clubs[0] else 1
            if len(teammates_on_ball(frames, home_count, side, int(shot["possession_since"]), shot["tick"])) >= 2:
                buildups += 1
                built += len(teammates_on_ball(frames, home_count, side, start, shot["tick"])) >= 2  # the passes are on screen
    assert total >= 6 and buildups >= 3
    assert built == buildups


def test_no_visual_teleports_inside_highlights():
    engine, director, _ = run_broadcast(180, seed=5)
    by_tick = engine.all_frames
    L = engine.L
    worst_player, worst_live_ball = 0.0, 0.0
    for segment in director.segments:
        if segment["k"] != "PLAY":
            continue
        for t in range(segment["t0"] + 1, segment["t1"] + 1):
            a, b = by_tick.get(t - 1), by_tick.get(t)
            if not a or not b or t - 1 == TICKS_PER_HALF:
                continue
            for i in range(0, len(a["p"]), 2):
                if a["p"][i] >= 0 and b["p"][i] >= 0:
                    worst_player = max(worst_player, math.hypot((b["p"][i] - a["p"][i]) * L, (b["p"][i + 1] - a["p"][i + 1]) * engine.W))
            if a["b"][3] != 1 and b["b"][3] != 1:  # dead-ball placements fade on the client
                worst_live_ball = max(worst_live_ball, math.hypot((b["b"][0] - a["b"][0]) * L, (b["b"][1] - a["b"][1]) * engine.W))
    # 12: a sprinting player covers < 9 m per game second; a struck ball < 45 m.
    assert worst_player < 9.0
    assert worst_live_ball < 45.0


def test_restart_resumes_the_exact_same_broadcast():
    engine, director, _ = run_broadcast(90, seed=3)
    reference = copy.deepcopy(director.segments)
    # Rebuild from scratch halfway and continue: the plan must be identical.
    engine2 = MatchEngine("m", "ELEVEN_A_SIDE", team("AAA", "ELEVEN_A_SIDE", 72), team("BBB", "ELEVEN_A_SIDE", 66), 3)
    engine2.enable_snapshots()
    director2 = Director(T0, 90)
    base = (engine2.inputs[0].tactics, engine2.inputs[1].tactics)
    now = T0
    while now < T0 + 45:
        director2.plan(engine2, lambda tick: advance_with_bots(engine2, tick, (0, 1), base), now)
        now += 0.25
    from app.domain.match_engine import replay_engine
    restored_engine = replay_engine("m", "ELEVEN_A_SIDE", engine2.inputs[0], engine2.inputs[1], 3, engine2.command_log, engine2.tick, snapshots=True)
    restored = Director.from_dict(copy.deepcopy(director2.to_dict()))
    while not restored.complete:
        restored.plan(restored_engine, lambda tick: advance_with_bots(restored_engine, tick, (0, 1), base), now)
        now += 0.25
    assert restored.segments == reference
    assert restored_engine.score == engine.score


# ---------------------------------------------------------------------- season / multiplayer

@pytest.fixture
def season():
    now = [T0]
    service = SeasonService(clock=lambda: now[0])
    clubs = tuple(c.code for c in CLUBS)
    market = InitialMarket(synthetic_catalog("ELEVEN_A_SIDE", teams=20), "ELEVEN_A_SIDE", dict.fromkeys(clubs, 10_000_000_000))
    complete_test_market(market, "broadcast-fixture")
    service.create("room", market)
    return service, market, now


@pytest.mark.parametrize("duration", DURATIONS)
def test_round_uses_the_room_duration_for_all_ten_matches_and_bots(season, duration):
    service, market, now = season
    service.ready("room", "FLA")
    state = service.advance("room", market, {"FLA"}, duration)
    live = state["live_round"]
    assert live["match_seconds"] == duration and live["ends_at"] - live["started_at"] == duration
    room = service._season("room")
    assert {d.duration for d in room.directors.values()} == {duration}  # bots' matches too
    now[0] = T0 + duration - 0.01
    assert not service.finish_due("room")
    now[0] = T0 + duration
    assert service.finish_due("room")
    assert len(room.state.results) == 10


def test_default_duration_is_sixty_seconds(season):
    service, market, now = season
    service.ready("room", "FLA")
    assert service.advance("room", market, {"FLA"})["live_round"]["match_seconds"] == 60
    with pytest.raises(ValueError):
        SeasonService(match_seconds=75)


def test_invalid_duration_is_refused(season):
    service, market, _ = season
    service.ready("room", "FLA")
    with pytest.raises(MarketError, match="Duração"):
        service.advance("room", market, {"FLA"}, 150)


def test_events_scoreboard_and_stats_agree_at_every_moment(season):
    service, market, now = season
    service.ready("room", "FLA")
    service.advance("room", market, {"FLA"}, 120)
    seen: dict[str, int] = {}
    last_tick = -1
    for step in range(0, 480):
        now[0] = T0 + step * 0.25
        view = service.live_view("room", "FLA")
        match = view["match"]
        # 10: events arrive in chronological order and never change once released.
        ticks = [e["tick"] for e in match["events"]]
        assert ticks == sorted(ticks) and match["tick"] >= last_tick
        last_tick = match["tick"]
        for event in match["events"]:
            assert seen.setdefault(event["event_id"], event["tick"]) == event["tick"]
        # 11: scoreboard = goal events = team statistics = player statistics.
        goals = [e for e in match["events"] if e["kind"] == "GOAL"]
        assert match["home_goals"] == sum(g["team"] == match["home"] for g in goals) == match["statistics"][match["home"]]["goals"]
        assert match["away_goals"] == sum(g["team"] == match["away"] for g in goals) == match["statistics"][match["away"]]["goals"]
    now[0] = T0 + 120
    assert service.finish_due("room")
    final = service.live_view("room", "FLA")["match"]
    # The official record keeps every event that was shown live, unchanged.
    assert {e["event_id"]: e["tick"] for e in final["events"] if e["event_id"] in seen} == seen
    assert final["home_goals"] == sum(1 for e in final["events"] if e["kind"] == "GOAL" and e["team"] == final["home"])


def test_substitution_half_time_window_and_feedback(season):
    service, market, now = season
    fixture = service._season("room").state.fixtures[0]
    service.ready("room", fixture.home)
    service.advance("room", market, {fixture.home}, 90)
    room = service._season("room")
    director = room.directors[fixture.id]
    # 15: a substitution during the half-time break is a genuine half-time change.
    for step in range(0, 400):
        now[0] = T0 + step * 0.25
        service.sync_live("room")
        if service.live_view("room", fixture.home)["clock"]["phase"] == "HALF_TIME":
            break
    assert room.engines[fixture.id].phase == "HALF_TIME"
    lineup = service.live_view("room", fixture.home)["match"]["lineups"]["home"]
    out = next(p for p in lineup if p["on_pitch"] and p["role"] != "GK")
    bench = next(p for p in lineup if p["available"])
    result = service.command("room", fixture.home, {"kind": "SUBSTITUTION", "out_player_id": out["id"], "in_player_id": bench["id"], "idempotency_key": "half-time-sub"})
    assert result["command"]["status"] == "APPLIED"
    assert room.engines[fixture.id].windows_used[0] == 0
    while not director.complete:
        now[0] += 0.5
        service.sync_live("room")
    events = [e for e in service.live_view("room", fixture.home)["match"]["events"] if e["kind"] == "SUBSTITUTION"]
    assert any(e["player_id"] == bench["id"] and e["tick"] == TICKS_PER_HALF for e in events)


def test_lookahead_never_leaks_to_any_client(season):
    service, market, now = season
    service.ready("room", "FLA")
    service.advance("room", market, {"FLA"}, 90)
    room = service._season("room")
    for step in range(0, 360):
        now[0] = T0 + step * 0.25
        view = service.live_view("room", "FLA")
        for score in view["scores"]:
            shown = service.shown_tick(room, score["id"], now[0])
            engine = room.engines[score["id"]]
            visible = [e for e in engine.events if e["kind"] == "GOAL" and e["tick"] <= shown]
            assert score["home_goals"] + score["away_goals"] == len(visible)
        frames = service.live_frames("room", "FLA", -1, sync=False)
        assert all(f["t"] <= frames["tick"] for f in frames["frames"])
        assert all(s["r0"] <= now[0] for s in frames["broadcast"])  # no future timeline either


# ---------------------------------------------------------------------- room setting (HTTP)

def test_room_duration_setting_host_only_synced_and_locked_during_a_round(monkeypatch):
    now = [T0]
    service = SeasonService(clock=lambda: now[0])
    monkeypatch.setattr(routes, "season_service", service)
    _, host_token = issue_guest_token()
    _, guest_token = issue_guest_token()
    host = {"cookie": f"{SESSION_COOKIE}={host_token}"}
    guest = {"cookie": f"{SESSION_COOKIE}={guest_token}"}
    with TestClient(create_app()) as client:
        created = client.post("/api/v1/rooms", headers=host, json={
            "name": "Duração teste", "mode": "FIVE_A_SIDE", "initial_budget_cents": 5_000_000_000,
            "max_human_participants": 3, "privacy": "PRIVATE"}).json()["data"]
        room_id = created["id"]
        base = f"/api/v1/rooms/{room_id}"
        try:
            assert created["match_duration_seconds"] == 60  # 4: default 1:00 (V2)
            assert client.post(f"{base}/join", headers=guest).status_code == 200
            with client.websocket_connect(f"/api/v1/ws/rooms/{room_id}", headers=guest) as ws:
                # 5: only the host may change it.
                assert client.put(f"{base}/match-settings", headers=guest, json={"match_duration_seconds": 180}).status_code == 403
                # 6: invalid values are refused by the contract.
                assert client.put(f"{base}/match-settings", headers=host, json={"match_duration_seconds": 150}).status_code == 422
                changed = client.put(f"{base}/match-settings", headers=host, json={"match_duration_seconds": 120})
                assert changed.status_code == 200 and changed.json()["data"]["match_duration_seconds"] == 120
                # Participants are told (feedback) and see the authoritative value.
                for _ in range(10):
                    message = ws.receive_json()
                    if message["type"] == "room.match_settings":
                        break
                assert message["match_duration_seconds"] == 120
                assert client.get(f"{base}/state", headers=guest).json()["data"]["match_duration_seconds"] == 120
            # Editing the rest of the league without the field keeps the chosen duration.
            update = {"name": "Duração teste 2", "mode": "FIVE_A_SIDE", "initial_budget_cents": 5_000_000_000,
                      "max_human_participants": 3, "privacy": "PRIVATE"}
            assert client.put(base, headers=host, json=update).json()["data"]["match_duration_seconds"] == 120
            # 9: a coach who joins later receives the setting.
            _, late_token = issue_guest_token()
            late = {"cookie": f"{SESSION_COOKIE}={late_token}"}
            assert client.post(f"{base}/join", headers=late).json()["data"]["match_duration_seconds"] == 120
            # 7: a round in progress keeps its duration: changes are refused until the whistle.
            clubs = tuple(c.code for c in CLUBS)
            market = InitialMarket(synthetic_catalog("FIVE_A_SIDE", teams=20), "FIVE_A_SIDE", dict.fromkeys(clubs, 5_000_000_000))
            complete_test_market(market, "duration-http")
            service.create(room_id, market)
            service.ready(room_id, "FLA")
            service.advance(room_id, market, {"FLA"}, 120)
            locked = client.put(f"{base}/match-settings", headers=host, json={"match_duration_seconds": 90})
            assert locked.status_code == 409
            assert service._season(room_id).live_round["match_seconds"] == 120
            now[0] += 120
            assert service.finish_due(room_id)
            assert client.put(f"{base}/match-settings", headers=host, json={"match_duration_seconds": 180}).json()["data"]["match_duration_seconds"] == 180
        finally:
            routes.room_manager._rooms.pop(room_id, None)
            routes.room_manager._locks.pop(room_id, None)
            service._seasons.pop(room_id, None)


def test_room_snapshot_keeps_the_duration():
    from app.domain.rooms import RoomManager
    manager = RoomManager()
    payload = {"id": "r1", "code": "ABC123", "name": "Sala", "mode": "ELEVEN_A_SIDE", "initial_budget_cents": 5_000_000_000,
               "max_human_participants": 2, "privacy": "PRIVATE", "host_user_id": "u1", "match_duration_seconds": 180,
               "participants": [{"user_id": "u1", "display_name": "Host", "role": "HOST", "selected_club_code": None}]}
    manager.restore(payload)
    assert manager._room("r1").match_duration_seconds == 180
    legacy = {**payload, "id": "r2", "code": "ABC124"}
    legacy.pop("match_duration_seconds")
    manager.restore(legacy)
    assert manager._room("r2").match_duration_seconds == 90  # legacy snapshots keep 1:30
    with pytest.raises(ValueError):
        manager.restore({**payload, "id": "r3", "code": "ABC125", "match_duration_seconds": 45})
