"""Live round on the incremental engine: shared clock, authority, commands, sync and recovery."""

import copy
import time

import pytest
from fastapi.testclient import TestClient

from app.api import routes
from app.domain.clubs import CLUBS
from app.domain.market import InitialMarket, MarketError
from app.main import create_app
from app.services.auth import SESSION_COOKIE, issue_guest_token
from app.services.market_service import MarketSession
from app.services.season_service import SeasonService
from app.tests.fixtures.market_catalog import complete_test_market, synthetic_catalog

T0 = 1_900_000_000.0


def service_for(now: list[float]) -> SeasonService:
    # Default room setting: every match is a 1:30 condensed broadcast.
    return SeasonService(clock=lambda: now[0])


@pytest.fixture
def live():
    now = [T0]
    service = service_for(now)
    clubs = tuple(c.code for c in CLUBS)
    market = InitialMarket(synthetic_catalog("ELEVEN_A_SIDE", teams=20), "ELEVEN_A_SIDE",
                           dict.fromkeys(clubs, 10_000_000_000))
    complete_test_market(market, "live-fixture")
    service.create("room", market)
    return service, market, now


def start(service, market, humans=frozenset({"FLA"})):
    for club in humans:
        service.ready("room", club)
    return service.advance("room", market, set(humans))


def test_ten_engines_share_clock_and_only_commit_at_the_deadline(live):
    service, market, now = live
    state = start(service, market)
    assert state["current_round"] == 1
    assert state["match_count"] == len(state["live_round"]["match_ids"]) == 10
    assert not service._season("room").state.results
    assert all(row["played"] == 0 for row in state["table"])
    assert service.advance("room", market, {"FLA"})["live_round"] == state["live_round"]
    now[0] += state["live_round"]["match_seconds"] - 0.001
    assert not service.finish_due("room")
    assert not service._season("room").state.results
    now[0] += .001
    assert service.finish_due("room")
    assert len(service._season("room").state.results) == 10
    assert not service.finish_due("room")
    assert service.view("room")["current_round"] == 2
    assert all(row["played"] == 1 for row in service.view("room")["table"])


def test_nothing_beyond_the_broadcast_is_released_and_stats_reconcile(live):
    service, market, now = live
    start(service, market)
    season = service._season("room")
    checkpoints = []
    for elapsed in (0, 7.3, 21, 45, 61, 89.9):
        now[0] = T0 + elapsed
        view = service.live_view("room", "FLA")
        match = view["match"]
        engine = season.engines[match["id"]]
        # The engine simulates a little ahead (lookahead), but only the tick on screen is sent.
        assert match["tick"] == service.shown_tick(season, match["id"], now[0]) <= engine.tick
        assert all(e["tick"] <= match["tick"] for e in match["events"])
        goals = [e for e in match["events"] if e["kind"] == "GOAL"]
        assert match["home_goals"] == sum(e["team"] == match["home"] for e in goals)
        assert match["away_goals"] == sum(e["team"] == match["away"] for e in goals)
        assert match["statistics"][match["home"]]["goals"] == match["home_goals"]
        assert match["statistics"][match["away"]]["goals"] == match["away_goals"]
        assert sum(p["stats"]["goals"] for p in match["lineups"]["home"]) == match["home_goals"]
        own_score = next(score for score in view["scores"] if score["id"] == match["id"])
        assert (own_score["home_goals"], own_score["away_goals"]) == (match["home_goals"], match["away_goals"])
        assert service.view("room")["top_scorers"] == []
        assert "probabilities" not in match and "inputs" not in match and "command_log" not in match
        assert len(view["scores"]) == 10 and all("events" not in other for other in view["scores"])
        checkpoints.append(copy.deepcopy(match["events"]))
    now[0] = T0 + 90
    service.finish_due("room")
    final = service.live_view("room", "FLA")["match"]
    assert final["status"] == "FINISHED"
    for released in checkpoints:  # the official record extends what was shown live
        assert final["events"][:len(released)] == released


def test_goal_updates_provisional_table_without_persisting(live):
    service, market, now = live
    start(service, market)
    season = service._season("room")
    for step in range(1, 91):
        now[0] = T0 + step
        service.sync_live("room")
        scores = [service._score(season, key) for key in season.engines]
        if any(s["home_goals"] + s["away_goals"] for s in scores):
            break
    scored = next(s for s in scores if s["home_goals"] + s["away_goals"])
    table = {row["club_code"]: row for row in service.live_table("room")}
    assert table[scored["home"]]["goals_for"] == scored["home_goals"] and table[scored["away"]]["goals_for"] == scored["away_goals"]
    assert all(row["played"] == 1 for row in table.values())
    assert not season.state.results


def test_two_coaches_share_state_commands_and_recovery_replays_exactly(live):
    service, market, now = live
    fixture = service._season("room").state.fixtures[0]
    start(service, market, {fixture.home, fixture.away, "PAL"})
    now[0] = T0 + 18
    ordered = service.command("room", fixture.home, {"kind": "TACTICS", "mentality": "ATTACKING", "idempotency_key": "home-press-01"})
    applied_tick = ordered["command"]["applied_tick"]
    # The order reaches the pitch at the simulation frontier, slightly after what is on
    # screen; the coach sees it at once, the broadcast only once that moment is shown.
    assert ordered["match"]["ordered_tactics"]["mentality"] == "ATTACKING"
    assert ordered["match"]["tick"] <= applied_tick
    season = service._season("room")
    for _ in range(200):
        service.sync_live("room")
        if service.shown_tick(season, fixture.id, now[0]) >= applied_tick:
            break
        now[0] += 0.25
    assert now[0] < T0 + 35  # at most one planned segment behind the order
    first = service.live_view("room", fixture.home)
    rival = service.live_view("room", fixture.away)
    different = service.live_view("room", "PAL")
    # Same events for both coaches; only the content of the rival's tactical change is masked.
    assert [(e["event_id"], e["kind"], e["tick"]) for e in first["match"]["events"]] == [(e["event_id"], e["kind"], e["tick"]) for e in rival["match"]["events"]]
    masked = [e for e in rival["match"]["events"] if e["kind"] == "TACTICS" and e["team"] == fixture.home]
    assert masked and all(e["tactics"] is None and e["outcome"] == "CHANGED" for e in masked)
    assert first["match"]["home_goals"] == rival["match"]["home_goals"] and first["match"]["tick"] == rival["match"]["tick"]
    assert first["match"]["id"] != different["match"]["id"]
    assert first["table"] == rival["table"] == different["table"]
    # Each coach sees only his own plan.
    assert first["match"]["tactics"]["home"]["mentality"] == "ATTACKING" and first["match"]["tactics"]["away"] is None
    assert rival["match"]["tactics"]["home"] is None
    assert [c["command_id"] for c in first["match"]["commands"]] == [f"{fixture.home}:home-press-01"]
    assert rival["match"].get("commands") == []
    # Server restart: the snapshot holds inputs, seeds and command logs; replay is exact.
    snapshot = copy.deepcopy(service.export_room("room"))
    recovered = service_for(now)
    recovered.restore_room("room", snapshot)
    # Engines are rebuilt in slices by the round task; until then the view says so.
    recovering = recovered.live_view("room", fixture.home)
    assert recovering["recovering"] is True and recovering["match"] is None and recovering["round_state"] == "RECOVERING"
    with pytest.raises(MarketError, match="recuperada"):
        recovered.command("room", fixture.home, {"kind": "TACTICS", "mentality": "DEFENSIVE", "idempotency_key": "during-recovery"})
    slices = 0
    while recovered._season("room").recovering:
        urgent, _more = recovered.simulate_slice("room", now[0])
        assert urgent
        slices += 1
    assert slices > 1  # rebuilt in several bounded steps, never in one long call
    assert recovered.live_view("room", fixture.home)["match"] == first["match"]
    for moment in (40, 47.5, 61, 75):
        now[0] = T0 + moment
        # Requests never simulate: the round task (here: sync_live) advances the engines.
        recovered.sync_live("room")
        service.sync_live("room")
        assert recovered.live_view("room", fixture.home)["match"] == service.live_view("room", fixture.home)["match"]
    assert recovered._season("room").directors[fixture.id].segments == service._season("room").directors[fixture.id].segments
    now[0] = T0 + 90
    assert recovered.finish_due("room") and service.finish_due("room")
    assert recovered._season("room").state.results == service._season("room").state.results


def test_commands_are_validated_idempotent_and_limited_to_the_own_match(live):
    service, market, now = live
    fixture = service._season("room").state.fixtures[0]
    start(service, market, {fixture.home})
    now[0] = T0 + 10
    with pytest.raises(MarketError, match="chave"):
        service.command("room", fixture.home, {"kind": "TACTICS", "pressure": "HIGH", "idempotency_key": "x"})
    first = service.command("room", fixture.home, {"kind": "TACTICS", "pressure": "HIGH", "idempotency_key": "press-high-1"})
    again = service.command("room", fixture.home, {"kind": "TACTICS", "pressure": "LOW", "idempotency_key": "press-high-1"})
    assert again["command"] == first["command"]
    engine = service._season("room").engines[fixture.id]
    assert engine.tactics[0].pressure == "HIGH"
    with pytest.raises(MarketError):
        service.command("room", fixture.home, {"kind": "TACTICS", "pressure": "MAXIMUM", "idempotency_key": "bad-value-01"})
    lineup = first["match"]["lineups"]["home"]
    out = next(p for p in lineup if p["on_pitch"] and p["role"] == "MF")
    bench = next(p for p in lineup if p["available"])
    other_team = first["match"]["lineups"]["away"][0]
    with pytest.raises(MarketError, match="não pertence"):
        service.command("room", fixture.home, {"kind": "SUBSTITUTION", "out_player_id": other_team["id"], "in_player_id": bench["id"], "idempotency_key": "steal-player"})
    with pytest.raises(MarketError, match="não pertence"):
        service.command("room", fixture.home, {"kind": "SUBSTITUTION", "out_player_id": "ghost", "in_player_id": bench["id"], "idempotency_key": "ghost-player"})
    sub = service.command("room", fixture.home, {"kind": "SUBSTITUTION", "out_player_id": out["id"], "in_player_id": bench["id"], "idempotency_key": "first-sub-01"})
    assert sub["command"]["status"] in {"PENDING", "APPLIED"}
    with pytest.raises(MarketError):
        service.command("room", fixture.home, {"kind": "SUBSTITUTION", "out_player_id": out["id"], "in_player_id": bench["id"], "idempotency_key": "first-sub-02"})
    now[0] = T0 + 60
    service.sync_live("room")  # the round task's job; requests never simulate
    applied = service.live_view("room", fixture.home)["match"]
    assert any(e["kind"] == "SUBSTITUTION" and e["player_id"] == bench["id"] for e in applied["events"])
    status = next(c for c in applied["commands"] if c["kind"] == "SUBSTITUTION")
    assert status["status"] == "APPLIED"
    with pytest.raises(MarketError, match="não está em uma partida"):
        service.command("room", "ZZZ", {"kind": "TACTICS", "pressure": "LOW", "idempotency_key": "nobody-here"})


def test_recovery_refuses_invalid_live_round(live):
    service, market, _ = live
    start(service, market)
    snapshot = copy.deepcopy(service.export_room("room"))
    snapshot["live_round"]["match_ids"].pop()
    with pytest.raises(ValueError, match="transmissão"):
        SeasonService().restore_room("bad", snapshot)


def test_start_requires_all_humans_and_lineup_change_cancels_ready(live):
    service, market, now = live
    service.ready("room", "FLA")
    with pytest.raises(MarketError, match="Aguardando"):
        service.advance("room", market, {"FLA", "PAL"})
    assert not service._season("room").matches
    assert service.unready("room", "FLA")
    assert "FLA" not in service._season("room").ready_clubs


def test_preparation_deadline_starts_the_round_with_saved_plans(live):
    service, market, now = live
    assert not service.start_if_preparation_expired("room", market, {"FLA", "PAL"}, 3600)
    now[0] += 3600
    assert service.start_if_preparation_expired("room", market, {"FLA", "PAL"}, 3600)
    assert service._season("room").live_round["round_number"] == 1


@pytest.mark.parametrize("guest_club", ["REM", "PAL"])
def test_http_live_round_commands_frames_authorization_and_reconnection(live, monkeypatch, guest_club):
    service, market, now = live
    monkeypatch.setattr(routes, "season_service", service)
    first, token1 = issue_guest_token()
    _, token2 = issue_guest_token()
    headers1 = {"cookie": f"{SESSION_COOKIE}={token1}"}
    headers2 = {"cookie": f"{SESSION_COOKIE}={token2}"}
    with TestClient(create_app()) as client:
        room_id = client.post("/api/v1/rooms", headers=headers1, json={
            "name": "Transmissão teste", "mode": "ELEVEN_A_SIDE", "initial_budget_cents": 10_000_000_000,
            "max_human_participants": 2, "privacy": "PRIVATE"}).json()["data"]["id"]
        client.post(f"/api/v1/rooms/{room_id}/join", headers=headers2)
        for headers, club in ((headers1, "FLA"), (headers2, guest_club)):
            assert client.put(f"/api/v1/rooms/{room_id}/participants/me/club", headers=headers,
                              json={"club_code": club}).status_code == 200
        service._seasons[room_id] = service._seasons.pop("room")
        routes.market_service.sessions[room_id] = MarketSession(room_id, now[0], market)
        room = routes.room_manager._room(room_id)
        room.phase = "SEASON_PREPARATION"
        assert room.host_user_id == first.id
        base = f"/api/v1/rooms/{room_id}"
        try:
            preview = client.get(base + "/season/preview", headers=headers1).json()["data"]
            assert preview["fixture"]["round_number"] == 1 and preview["home"]["starters"]
            assert client.post(base + "/season/ready", headers=headers1).json()["data"]["live_round"] is None
            with client.websocket_connect(f"/api/v1/ws/rooms/{room_id}", headers=headers1) as ws1, client.websocket_connect(f"/api/v1/ws/rooms/{room_id}", headers=headers2) as ws2:
                assert ws1.receive_json()["type"] == ws2.receive_json()["type"] == "season.sync"
                ws1.send_text("ping")
                assert ws1.receive_text() == "pong"
                response = client.post(base + "/season/ready", headers=headers2)
                assert response.status_code == 200
                assert len(response.json()["data"]["live_round"]["match_ids"]) == 10
                assert client.put(base + "/squad/tactics", headers=headers1, json={"mentality": "ATTACKING", "pressure": "HIGH", "style": "DIRECT"}).status_code == 409
                now[0] += 25
                pushed = None
                for _ in range(200):  # the round task streams each coach his own match
                    message = ws1.receive_json()
                    if message["type"] == "live.frames":
                        pushed = message
                        break
                assert pushed and pushed["frames"] and all(len(f["p"]) % 2 == 0 for f in pushed["frames"])
                own = client.get(base + "/season/live", headers=headers1).json()["data"]
                assert pushed["match_id"] == own["match"]["id"]
                other = client.get(base + "/season/live", headers=headers2).json()["data"]
                assert (own["match"]["id"] == other["match"]["id"]) == (guest_club == "REM")
                if guest_club == "REM":
                    assert own["match"]["events"] == other["match"]["events"]
                forbidden = next(score["id"] for score in own["scores"] if score["id"] != own["match"]["id"])
                assert client.get(base + f"/matches/{forbidden}", headers=headers1).status_code == 403
                # The clock jumped 25 s: the round task catches up in slices in the background.
                for _ in range(100):
                    frames = client.get(base + "/season/live/frames?since=-1", headers=headers1).json()["data"]
                    if frames.get("broadcast") and frames.get("frames"):
                        break
                    if frames.get("broadcast"):
                        now[0] += 0.5  # planned, but the screen sits inside a cut (no frames to send)
                    time.sleep(0.05)
                own = client.get(base + "/season/live", headers=headers1).json()["data"]
                assert frames["match_id"] == own["match"]["id"] and frames["frames"][-1]["t"] <= own["match"]["tick"]
                assert frames["broadcast"] and frames["broadcast"][0]["r0"] <= now[0]
                for _ in range(8):  # the screen may sit exactly on a cut landing (one frame): let it play on
                    if len(frames["frames"]) >= 2:
                        break
                    now[0] += 0.5
                    frames = client.get(base + "/season/live/frames?since=-1", headers=headers1).json()["data"]
                assert len(frames["frames"]) >= 2
                cursor = frames["frames"][-2]["t"]  # a client that already holds everything up to here
                resumed = client.get(base + f"/season/live/frames?since={cursor}", headers=headers1).json()["data"]
                assert [f["t"] for f in resumed["frames"]] == [f["t"] for f in frames["frames"] if f["t"] > cursor]
                payload = {"kind": "TACTICS", "style": "WIDE", "idempotency_key": "http-wide-0001"}
                done = client.post(base + "/season/live/commands", headers=headers1, json=payload)
                assert done.status_code == 200 and done.json()["data"]["command"]["status"] == "APPLIED"
                assert client.post(base + "/season/live/commands", headers=headers1, json=payload).json()["data"]["command"] == done.json()["data"]["command"]
                assert client.post(base + "/season/live/commands", headers=headers1, json={"kind": "SUBSTITUTION", "out_player_id": "x", "in_player_id": "y", "idempotency_key": "http-bad-sub-1"}).status_code == 409
            # Same instant on both paths: the fake clock may have moved inside the loops above.
            own = client.get(base + "/season/live", headers=headers1).json()["data"]
            with client.websocket_connect(f"/api/v1/ws/rooms/{room_id}", headers=headers1) as reconnected:
                sync = reconnected.receive_json()
                assert sync["data"]["match"]["id"] == own["match"]["id"]
                assert sync["data"]["match"]["tick"] == own["match"]["tick"]
            now[0] += 66
            deadline = time.monotonic() + 60  # the background task finishes the ten engines
            while service._season(room_id).live_round and time.monotonic() < deadline:
                time.sleep(.05)
            assert len(service._season(room_id).state.results) == 10
            finished = client.get(base + "/season/live", headers=headers1).json()["data"]["match"]
            assert finished["status"] == "FINISHED" and "command_log" not in finished and "inputs" not in finished
            assert [c["command_id"] for c in finished["commands"]] == ["FLA:http-wide-0001"]
            replay = client.get(base + f"/matches/{finished['id']}/frames?start=100&end=140", headers=headers1).json()["data"]
            assert [f["t"] for f in replay["frames"]] == list(range(100, 141))
            assert not service.finish_due(room_id)
        finally:
            routes.market_service.sessions.pop(room_id, None)
            routes.room_manager._rooms.pop(room_id, None)
            routes.room_manager._locks.pop(room_id, None)
            service._seasons.pop(room_id, None)


def test_next_round_timer_survives_ready_during_completion_notification(live, monkeypatch):
    import asyncio

    service, market, now = live
    start(service, market)
    now[0] += 90
    monkeypatch.setattr(routes, "season_service", service)
    monkeypatch.setattr(routes, "round_tasks", {})
    monkeypatch.setattr(routes, "round_locks", {})
    monkeypatch.setattr(routes, "snapshot_room", lambda _: None)

    async def notify(room_id, event):
        if event["type"] == "season.round_completed":
            service.ready(room_id, "FLA")
            service.advance(room_id, market, {"FLA"})
            routes.schedule_round(room_id)

    monkeypatch.setattr(routes.hub, "broadcast", notify)

    async def scenario():
        routes.schedule_round("room")
        old = routes.round_tasks["room"]
        await old
        new = routes.round_tasks["room"]
        assert new is not old
        assert service._season("room").live_round["round_number"] == 2
        new.cancel()
        await asyncio.gather(new, return_exceptions=True)

    asyncio.run(scenario())
