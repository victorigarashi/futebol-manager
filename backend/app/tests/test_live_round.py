"""Public projections, multi-coach authorization, deadlines and snapshot recovery."""

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
from app.services.season_service import SeasonService, project_events
from app.tests.fixtures.market_catalog import complete_test_market, synthetic_catalog


@pytest.fixture
def live():
    now = [1_900_000_000.0]
    service = SeasonService(clock=lambda: now[0])
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


def test_ten_streams_share_clock_and_only_commit_at_sixty_seconds(live):
    service, market, now = live
    state = start(service, market)
    assert state["current_round"] == 1
    assert state["match_count"] == len(state["live_round"]["match_ids"]) == 10
    assert not service._season("room").state.results
    assert all(row["played"] == 0 for row in state["table"])
    original = copy.deepcopy(service._season("room").matches)
    assert service.advance("room", market, {"FLA"})["live_round"] == state["live_round"]
    assert original == service._season("room").matches
    now[0] += 59.999
    assert not service.finish_due("room")
    assert not service._season("room").state.results
    now[0] += .001
    assert service.finish_due("room")
    assert len(service._season("room").state.results) == 10
    assert not service.finish_due("room")
    assert service.view("room")["current_round"] == 2
    assert all(row["played"] == 1 for row in service.view("room")["table"])


def test_no_future_events_scores_xg_stats_or_scorers_and_replay_reconciles(live):
    service, market, now = live
    start(service, market)
    for elapsed in (0, 7.3, 21, 45, 59.9):
        now[0] = 1_900_000_000 + elapsed
        view = service.live_view("room", "FLA")
        match = view["match"]
        assert all(e["animation_ms"] <= elapsed * 1500 + .001 for e in match["events"])
        assert project_events(match["home"], match["away"], match["events"])["statistics"] == match["statistics"]
        assert match["home_goals"] == sum(e["kind"] == "GOAL" and e["team"] == match["home"] for e in match["events"])
        assert service.view("room")["top_scorers"] == []
        assert "probabilities" not in match
        assert len(view["scores"]) == 10
        assert all("events" not in other for other in view["scores"])
    now[0] = 1_900_000_060
    before = service.live_view("room", "FLA")["match"]
    service.finish_due("room")
    after = service.live_view("room", "FLA")["match"]
    assert before["events"] == after["events"]
    for club in (after["home"], after["away"]):
        for key, count in after["statistics"][club].items():
            assert before["statistics"][club][key] == count
    assert before["home_xg"] == after["home_xg"]
    assert before["away_xg"] == after["away_xg"]


def test_goal_updates_provisional_table_with_previous_results_without_persisting(live):
    service, market, now = live
    start(service, market)
    now[0] += 60
    service.finish_due("room")
    previous = copy.deepcopy(service._season("room").state.results)
    start(service, market)
    season = service._season("room")
    candidates = [(key, e) for key in season.live_round["match_ids"]
                  for e in season.matches[key]["events"] if e["kind"] == "GOAL"]
    assert candidates
    match_id, goal = candidates[0]
    at_goal = season.live_round["started_at"] + goal["animation_ms"] / 1500
    now[0] = at_goal - .001
    before = {r["club_code"]: r for r in service.live_table("room")}
    now[0] = at_goal + .001
    after = {r["club_code"]: r for r in service.live_table("room")}
    club = goal["team"]
    assert after[club]["goals_for"] == before[club]["goals_for"] + 1
    assert after[club]["goal_difference"] == before[club]["goal_difference"] + 1
    assert any(before[c]["points"] != after[c]["points"] for c in after)
    assert all(row["played"] == 2 for row in after.values())
    assert season.state.results == previous
    assert service.match("room", match_id)["status"] == "LIVE"


def test_two_coaches_same_match_or_different_matches_and_reconnect(live):
    service, market, now = live
    fixture = service._season("room").state.fixtures[0]
    start(service, market, {fixture.home, fixture.away, "PAL"})
    now[0] += 27
    first = service.live_view("room", fixture.home)
    opponent = service.live_view("room", fixture.away)
    different = service.live_view("room", "PAL")
    assert first["match"] == opponent["match"]
    assert first["match"]["id"] != different["match"]["id"]
    assert first["table"] == opponent["table"] == different["table"]
    snapshot = copy.deepcopy(service.export_room("room"))
    recovered = SeasonService(clock=lambda: now[0])
    recovered.restore_room("room", snapshot)
    assert recovered.live_view("room", fixture.home) == first
    now[0] += 12
    reconnected = recovered.live_view("room", fixture.home)
    assert reconnected["match"]["minute"] == 58.5
    assert reconnected["match"]["events"][:len(first["match"]["events"])] == first["match"]["events"]
    now[0] += 21
    assert recovered.finish_due("room")
    assert not recovered.finish_due("room")


def test_recovery_refuses_invalid_live_round(live):
    service, market, _ = live
    start(service, market)
    snapshot = copy.deepcopy(service.export_room("room"))
    snapshot["live_round"]["match_ids"].pop()
    with pytest.raises(ValueError, match="transmissão"):
        SeasonService().restore_room("bad", snapshot)


def test_start_requires_all_humans(live):
    service, market, _ = live
    service.ready("room", "FLA")
    with pytest.raises(MarketError, match="Aguardando"):
        service.advance("room", market, {"FLA", "PAL"})
    assert not service._season("room").matches


@pytest.mark.parametrize("guest_club", ["REM", "PAL"])
def test_http_websocket_automatic_start_authorization_and_reconnection(live, monkeypatch, guest_club):
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
            assert client.post(base + "/season/ready", headers=headers1).json()["data"]["live_round"] is None
            with client.websocket_connect(f"/api/v1/ws/rooms/{room_id}", headers=headers1) as ws1, client.websocket_connect(f"/api/v1/ws/rooms/{room_id}", headers=headers2) as ws2:
                assert ws1.receive_json()["type"] == ws2.receive_json()["type"] == "season.sync"
                response = client.post(base + "/season/ready", headers=headers2)
                assert response.status_code == 200
                assert len(response.json()["data"]["live_round"]["match_ids"]) == 10
                now[0] += 25
                own = client.get(base + "/season/live", headers=headers1).json()["data"]
                other = client.get(base + "/season/live", headers=headers2).json()["data"]
                assert (own["match"]["id"] == other["match"]["id"]) == (guest_club == "REM")
                if guest_club == "REM":
                    assert own["match"]["events"] == other["match"]["events"]
                forbidden = next(score["id"] for score in own["scores"] if score["id"] != own["match"]["id"])
                assert client.get(base + f"/matches/{forbidden}", headers=headers1).status_code == 403
            with client.websocket_connect(f"/api/v1/ws/rooms/{room_id}", headers=headers1) as reconnected:
                sync = reconnected.receive_json()
                assert sync["data"]["match"] == own["match"]
                assert sync["data"]["match"]["minute"] == 37.5
            now[0] += 35
            # Let the actual background task perform finalization (no GET-side commit).
            deadline = time.monotonic() + 3
            while service._season(room_id).live_round and time.monotonic() < deadline:
                time.sleep(.02)
            assert len(service._season(room_id).state.results) == 10
            assert client.get(base + "/season/live", headers=headers1).json()["data"]["match"]["status"] == "FINISHED"
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
    now[0] += 60
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
