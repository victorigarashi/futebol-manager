"""Multiplayer stability: READY flow, round start exactly once, cooperative simulation,
pre-simulated bot matches, sliced recovery and incremental snapshots.

Context (diagnosis of the Render incident, docs/ESTABILIDADE_MULTIPLAYER.md): the live
simulation ran inline on the event loop, so a 0.1 CPU host missed its 5 s health check
and was restarted mid-round, again and again. These tests pin the fixes down.
"""

from __future__ import annotations

import asyncio
import copy
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.api import routes
from app.domain.broadcast import Director, LinearClock
from app.domain.clubs import CLUBS
from app.domain.market import InitialMarket, MarketError
from app.domain.match_engine import FULL_TIME_TICK, TICKS_PER_HALF
from app.main import create_app
from app.services.auth import SESSION_COOKIE, issue_guest_token
from app.services.market_service import MarketSession
from app.services.season_service import SeasonService
from app.services.snapshot_store import SnapshotStore
from app.services.snapshots import load_snapshot
from app.tests.fixtures.market_catalog import complete_test_market, synthetic_catalog

T0 = 1_900_000_000.0
HUMANS = {"FLA", "PAL"}


def make(now: list[float], mode: str = "ELEVEN_A_SIDE", room: str = "room") -> tuple[SeasonService, InitialMarket]:
    service = SeasonService(clock=lambda: now[0], intro_seconds=5)
    market = InitialMarket(synthetic_catalog(mode, teams=20), mode, dict.fromkeys((c.code for c in CLUBS), 10_000_000_000))
    complete_test_market(market, f"{room}-fixture")
    service.create(room, market)
    return service, market


def play_round_in_slices(service: SeasonService, room: str = "room", step: float = 0.25) -> dict[str, object]:
    """Drive a round exactly like the round task does: bounded slices against the clock."""
    now = service._test_now
    longest = 0.0
    slices = 0
    assert service._season(room).live_round
    while service._season(room).live_round:
        for _ in range(10_000):
            began = time.perf_counter()
            urgent, _more = service.simulate_slice(room)
            longest = max(longest, time.perf_counter() - began)
            slices += 1
            if not urgent:
                break
        if service.ready_to_finish(room):
            assert service.finish_due(room)
            break
        now[0] += step
    return {"longest_slice": longest, "slices": slices}


@pytest.fixture
def room():
    now = [T0]
    service, market = make(now)
    service._test_now = now
    return service, market, now


# ---------------------------------------------------------------- READY flow (service)
def test_ready_is_idempotent_and_round_state_follows_the_machine(room):
    service, market, now = room
    season = service._season("room")
    season.human_clubs = set(HUMANS)
    assert service.round_state("room") == "PREPARING"
    first = service.ready("room", "FLA")
    again = service.ready("room", "FLA")
    assert first["ready_clubs"] == again["ready_clubs"] == ["FLA"]
    assert service.round_state("room") == "PREPARING"
    service.ready("room", "PAL")
    assert service.round_state("room") == "READY"
    service.advance("room", market, HUMANS, 90)
    assert service.round_state("room") == "STARTING"  # presentation before kick-off
    now[0] += 6
    assert service.round_state("room") == "LIVE"
    now[0] += 90
    assert service.round_state("room") == "FINISHED"  # until the commit
    service.sync_live("room")
    assert service.finish_due("room")
    assert service.round_state("room") == "PREPARING"
    assert service.view("room")["current_round"] == 2


def test_bots_never_block_the_start_and_starting_twice_is_a_no_op(room):
    service, market, _now = room
    for club in HUMANS:
        service.ready("room", club)
    started = service.advance("room", market, HUMANS, 90)
    assert len(started["live_round"]["match_ids"]) == 10  # 18 bot clubs included, never waited for
    assert service.advance("room", market, HUMANS, 90)["live_round"] == started["live_round"]
    other, other_market = make([T0], room="other")
    with pytest.raises(MarketError):
        other.advance("other", other_market, HUMANS, 90)  # humans not ready: refused, no round
    assert other._season("other").live_round is None


# ---------------------------------------------------------------- cooperative simulation
@pytest.mark.parametrize("duration", [90, 120, 180])
def test_sliced_simulation_keeps_up_and_ends_exactly_at_the_deadline(room, duration):
    service, market, now = room
    for club in HUMANS:
        service.ready("room", club)
    service.advance("room", market, HUMANS, duration)
    live = service._season("room").live_round
    assert live["ends_at"] - live["started_at"] == duration
    ends_at = live["ends_at"]
    stats = play_round_in_slices(service)
    # Never behind: the round is committed at the deadline (one clock step of tolerance).
    assert ends_at <= now[0] <= ends_at + 0.25
    assert len(service._season("room").state.results) == 10
    # Every unit of work is small: the event loop is never held for long.
    assert stats["longest_slice"] < 0.25, stats


def test_slices_give_exactly_the_same_results_as_the_inline_engine():
    now_a, now_b = [T0], [T0]
    sliced, market_a = make(now_a)
    inline, market_b = make(now_b)
    sliced._test_now = now_a
    for service, market in ((sliced, market_a), (inline, market_b)):
        for club in HUMANS:
            service.ready("room", club)
        service.advance("room", market, HUMANS, 90)
    play_round_in_slices(sliced)
    now_b[0] = inline._season("room").live_round["ends_at"]
    inline.sync_live("room")
    assert inline.finish_due("room")
    a, b = sliced._season("room"), inline._season("room")
    assert a.state.results == b.state.results
    for match_id in a.state.results:
        assert [(e["event_id"], e["kind"], e["tick"]) for e in a.matches[match_id]["events"]] == \
               [(e["event_id"], e["kind"], e["tick"]) for e in b.matches[match_id]["events"]]


def test_unwatched_matches_use_a_linear_clock_without_frames(room):
    service, market, now = room
    for club in HUMANS:
        service.ready("room", club)
    service.advance("room", market, HUMANS, 90)
    season = service._season("room")
    watched = [m for m in season.live_round["match_ids"] if isinstance(season.directors[m], Director)]
    unwatched = [m for m in season.live_round["match_ids"] if isinstance(season.directors[m], LinearClock)]
    assert len(watched) == 2 and len(unwatched) == 8
    assert all(not season.engines[m].record_frames for m in unwatched)
    clock = season.directors[unwatched[0]]
    start = season.live_round["started_at"]
    assert clock.shown_tick(start) == 0
    assert clock.shown_tick(start + clock.half_seconds + clock.halftime / 2) == TICKS_PER_HALF
    assert clock.shown_tick(season.live_round["ends_at"]) == FULL_TIME_TICK
    ticks = [clock.tick_at(start + t / 10) for t in range(0, 901)]
    assert ticks == sorted(ticks)
    # Scores of other matches never run ahead of their clock.
    now[0] = start + 30
    service.sync_live("room")
    for match_id in unwatched:
        shown = clock.shown_tick(now[0])
        score = service._score(season, match_id, now[0])
        goals = [e for e in season.engines[match_id].events if e["kind"] == "GOAL" and e["tick"] <= shown]
        assert score["home_goals"] + score["away_goals"] == len(goals)


# ---------------------------------------------------------------- pre-simulation during preparation
def test_bot_matches_simulated_during_preparation_are_reused_identically():
    now_a, now_b = [T0], [T0]
    prepared, market_a = make(now_a)
    fresh, market_b = make(now_b)
    while prepared.prepare_slice("room", market_a, HUMANS):
        pass
    prebuilt = dict(prepared._season("room").prebuilt)
    assert len(prebuilt) == 8 and all(p.engine.finished for p in prebuilt.values())
    for service, market in ((prepared, market_a), (fresh, market_b)):
        for club in HUMANS:
            service.ready("room", club)
        service.advance("room", market, HUMANS, 90)
    season = prepared._season("room")
    assert all(season.engines[k] is prebuilt[k].engine for k in prebuilt)  # reused, not recomputed
    for service, now in ((prepared, now_a), (fresh, now_b)):
        now[0] = service._season("room").live_round["ends_at"]
        service.sync_live("room")
        assert service.finish_due("room")
    assert prepared._season("room").state.results == fresh._season("room").state.results


def test_prebuilt_match_is_discarded_when_its_inputs_change():
    now = [T0]
    service, market = make(now)
    while service.prepare_slice("room", market, HUMANS):
        pass
    season = service._season("room")
    match_id, prebuilt = next(iter(season.prebuilt.items()))
    fixture = next(f for f in season.state.fixtures if f.id == match_id)
    # A coach takes over one of the clubs before the round: it is no longer bot vs bot.
    humans = HUMANS | {fixture.home}
    for club in humans:
        service.ready("room", club)
    service.advance("room", market, humans, 90)
    assert service._season("room").engines[match_id] is not prebuilt.engine


# ---------------------------------------------------------------- recovery and persistence
def test_sliced_recovery_after_a_restart_keeps_results_identical(room):
    service, market, now = room
    for club in HUMANS:
        service.ready("room", club)
    service.advance("room", market, HUMANS, 90)
    now[0] += 40
    service.sync_live("room")
    fixture = next(f for f in service._season("room").state.fixtures if f.round_number == 1 and "FLA" in (f.home, f.away))
    service.command("room", "FLA", {"kind": "TACTICS", "mentality": "ATTACKING", "idempotency_key": "recover-01"})
    snapshot = copy.deepcopy(service.export_room("room"))
    original = copy.deepcopy(snapshot)  # restore consumes its payload
    recovered = SeasonService(clock=lambda: now[0], intro_seconds=5)
    recovered.restore_room("room", snapshot)
    assert recovered.round_state("room") == "RECOVERING"
    # Mid-rebuild snapshots still carry the complete command log and frontier.
    mid = recovered.export_room("room")["matches"][fixture.id]
    assert [c["command_id"] for c in mid["command_log"]] == [c["command_id"] for c in original["matches"][fixture.id]["command_log"]]
    assert mid["frontier"] == original["matches"][fixture.id]["frontier"]
    while recovered._season("room").recovering:
        recovered.simulate_slice("room")
    for service_ in (service, recovered):
        now[0] = service_._season("room").live_round["ends_at"]
        service_.sync_live("room")
    assert service.finish_due("room") and recovered.finish_due("room")
    assert recovered._season("room").state.results == service._season("room").state.results


def test_snapshot_store_writes_a_valid_checksummed_file_and_caches_finished_matches(tmp_path, room):
    service, market, now = room
    for club in HUMANS:
        service.ready("room", club)
    service.advance("room", market, HUMANS, 90)
    now[0] = service._season("room").live_round["ends_at"]
    service.sync_live("room")
    service.finish_due("room")
    store = SnapshotStore()
    path = tmp_path / "rooms.json"
    payload = {"room": {"id": "room"}, "season": service.export_room("room")}
    store.update(path, "room", payload)
    store.write_now(path)
    loaded = load_snapshot(path)
    assert loaded["rooms"]["room"]["season"]["results"] == payload["season"]["results"]
    # Second serialisation reuses every finished match (immutable) from the cache.
    cached = dict(store._match_cache)
    assert len(cached) == 10
    store.update(path, "room", {"room": {"id": "room"}, "season": service.export_room("room")})
    assert all(store._match_cache[k][1] is cached[k][1] for k in cached)
    # Rooms already in the file survive when another room is written by a new process.
    other = SnapshotStore()
    other.update(path, "second", {"room": {"id": "second"}})
    other.write_now(path)
    assert set(load_snapshot(path)["rooms"]) == {"room", "second"}


# ---------------------------------------------------------------- HTTP: concurrent READY and deadline
def _http_room(client, service, market, now, preparation_seconds=3600):
    first, token1 = issue_guest_token()
    _, token2 = issue_guest_token()
    headers1 = {"cookie": f"{SESSION_COOKIE}={token1}"}
    headers2 = {"cookie": f"{SESSION_COOKIE}={token2}"}
    room_id = client.post("/api/v1/rooms", headers=headers1, json={
        "name": "Fluxo de prontos", "mode": "ELEVEN_A_SIDE", "initial_budget_cents": 10_000_000_000,
        "max_human_participants": 2, "privacy": "PRIVATE", "round_preparation_duration_seconds": preparation_seconds}).json()["data"]["id"]
    client.post(f"/api/v1/rooms/{room_id}/join", headers=headers2)
    for headers, club in ((headers1, "FLA"), (headers2, "PAL")):
        assert client.put(f"/api/v1/rooms/{room_id}/participants/me/club", headers=headers, json={"club_code": club}).status_code == 200
    service._seasons[room_id] = service._seasons.pop("room")
    routes.market_service.sessions[room_id] = MarketSession(room_id, now[0], market)
    routes.room_manager._room(room_id).phase = "SEASON_PREPARATION"
    return room_id, headers1, headers2


def test_concurrent_ready_over_http_starts_the_round_exactly_once(room, monkeypatch):
    service, market, now = room
    monkeypatch.setattr(routes, "season_service", service)
    monkeypatch.setattr(routes, "snapshot_room", lambda _: None)
    calls = {"advance": 0}
    original = service.advance

    def counted(*args, **kwargs):
        calls["advance"] += 1
        return original(*args, **kwargs)
    monkeypatch.setattr(service, "advance", counted)
    with TestClient(create_app()) as client:
        room_id, headers1, headers2 = _http_room(client, service, market, now)
        base = f"/api/v1/rooms/{room_id}"
        with client.websocket_connect(f"/api/v1/ws/rooms/{room_id}", headers=headers2) as ws2:
            ws2.receive_json()  # season.sync
            # 1. One coach confirms: registered on the server, the other coach is told.
            first = client.post(base + "/season/ready", headers=headers1).json()["data"]
            assert first["ready_clubs"] == ["FLA"] and first["round_state"] == "PREPARING" and first["live_round"] is None
            assert ws2.receive_json()["type"] == "season.ready_changed"
            # 2. Confirming again changes nothing (idempotent).
            assert client.post(base + "/season/ready", headers=headers1).json()["data"]["ready_clubs"] == ["FLA"]
            # 3. Both coaches hammer READY at the same time from several threads.
            results: list[int] = []

            def press(headers):
                results.append(client.post(base + "/season/ready", headers=headers).status_code)
            threads = [threading.Thread(target=press, args=(h,)) for h in (headers1, headers2) * 4]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        assert results == [200] * 8
        assert calls["advance"] == 1  # the round started exactly once
        live = client.get(base + "/season/live", headers=headers1).json()["data"]
        assert live["live_round"] and len(live["live_round"]["match_ids"]) == 10
        assert live["round_state"] in {"STARTING", "LIVE"}


def test_preparation_deadline_starts_the_round_even_if_nobody_polls(room, monkeypatch):
    service, market, now = room
    monkeypatch.setattr(routes, "season_service", service)
    monkeypatch.setattr(routes, "snapshot_room", lambda _: None)
    with TestClient(create_app()) as client:
        room_id, headers1, _headers2 = _http_room(client, service, market, now, preparation_seconds=120)
        service._season(room_id).preparation_opened_at = now[0]
        now[0] += 121  # nobody confirmed, nobody is polling /season
        for _ in range(60):  # the housekeeping task runs every second
            if service._season(room_id).live_round:
                break
            time.sleep(0.1)
        assert service._season(room_id).live_round, "the deadline must start the round on its own"


def test_round_task_survives_an_iteration_failure(room, monkeypatch):
    service, market, now = room
    monkeypatch.setattr(routes, "season_service", service)
    monkeypatch.setattr(routes, "snapshot_room", lambda _: None)
    for club in HUMANS:
        service.ready("room", club)
    service.advance("room", market, HUMANS, 90)
    failures = {"left": 1}
    original = service.simulate_slice

    def flaky(*args, **kwargs):
        if failures["left"]:
            failures["left"] -= 1
            raise RuntimeError("boom")
        return original(*args, **kwargs)
    monkeypatch.setattr(service, "simulate_slice", flaky)

    async def scenario():
        routes.schedule_round("room")
        for _ in range(100):
            await asyncio.sleep(0.05)
            if not failures["left"] and routes.round_tasks.get("room"):
                return True
        return False
    assert asyncio.run(scenario())  # the room is not left stuck "live" without a task
    for task in list(routes.round_tasks.values()):
        task.cancel()
    routes.round_tasks.clear()
