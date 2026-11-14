import asyncio
import json
from pathlib import Path

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.routes import market_service
from app.domain.catalog import catalog_status
from app.domain.rooms import RoomManager
from app.main import create_app
from app.tests.fixtures.market_catalog import synthetic_catalog


def guest(client: TestClient) -> dict[str, str]:
    response = client.post("/api/v1/auth/guest")
    assert response.status_code == 201
    return response.json()["data"]


def room_payload() -> dict[str, object]:
    return {
        "name": "Liga de teste",
        "mode": "FIVE_A_SIDE",
        "initial_budget_cents": 5_000_000_000,
        "max_human_participants": 4,
        "privacy": "PUBLIC",
    }


def test_guest_can_create_join_and_select_an_exclusive_club() -> None:
    app = create_app()
    with TestClient(app) as host, TestClient(app) as guest_client:
        guest(host)
        created = host.post("/api/v1/rooms", json=room_payload())
        assert created.status_code == 201
        assert created.json()["data"]["withdrawal_penalty_percent"] == 5
        room_id = created.json()["data"]["id"]

        guest(guest_client)
        assert guest_client.post(f"/api/v1/rooms/{room_id}/join").status_code == 200
        assert (
            host.put(
                f"/api/v1/rooms/{room_id}/participants/me/club", json={"club_code": "FLA"}
            ).status_code
            == 200
        )
        assert (
            guest_client.put(
                f"/api/v1/rooms/{room_id}/participants/me/club", json={"club_code": "FLA"}
            ).status_code
            == 409
        )


def test_signed_bearer_token_is_accepted_when_cross_origin_cookie_is_unavailable() -> None:
    app = create_app()
    with TestClient(app) as client:
        issued = client.post("/api/v1/auth/guest")
        token = issued.json()["data"]["session_token"]
        client.cookies.clear()
        response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert response.json()["data"]["id"] == issued.json()["data"]["id"]


def test_state_requires_membership() -> None:
    app = create_app()
    with TestClient(app) as host, TestClient(app) as outsider:
        guest(host)
        room_id = host.post("/api/v1/rooms", json=room_payload()).json()["data"]["id"]
        guest(outsider)
        assert outsider.get(f"/api/v1/rooms/{room_id}/state").status_code == 403


def test_profile_and_host_settings_are_persisted_in_memory() -> None:
    app = create_app()
    with TestClient(app) as host, TestClient(app) as member:
        guest(host)
        created = host.post("/api/v1/rooms", json=room_payload())
        room_id = created.json()["data"]["id"]
        renamed = host.put("/api/v1/me", json={"display_name": "Vitinho 10"})
        assert renamed.status_code == 200
        assert renamed.json()["data"]["display_name"] == "Vitinho 10"
        assert host.get("/api/v1/me").json()["data"]["display_name"] == "Vitinho 10"
        state = host.get(f"/api/v1/rooms/{room_id}/state").json()["data"]
        assert state["participants"][0]["display_name"] == "Vitinho 10"
        guest(member)
        assert member.post(f"/api/v1/rooms/{room_id}/join").status_code == 200
        settings = {**room_payload(), "name": "Liga da galera", "mode": "ELEVEN_A_SIDE", "max_human_participants": 6}
        assert member.put(f"/api/v1/rooms/{room_id}", json=settings).status_code == 403
        updated = host.put(f"/api/v1/rooms/{room_id}", json=settings)
        assert updated.status_code == 200
        assert updated.json()["data"]["name"] == "Liga da galera"
        assert updated.json()["data"]["mode"] == "ELEVEN_A_SIDE"


def test_only_host_with_club_can_start_market_when_catalog_is_available() -> None:
    app = create_app()
    with TestClient(app) as host, TestClient(app) as member:
        guest(host)
        room_id = host.post("/api/v1/rooms", json=room_payload()).json()["data"]["id"]
        guest(member)
        assert member.post(f"/api/v1/rooms/{room_id}/join").status_code == 200
        assert member.post(f"/api/v1/rooms/{room_id}/start").status_code == 403
        assert host.post(f"/api/v1/rooms/{room_id}/start").status_code == 409
        assert host.put(f"/api/v1/rooms/{room_id}/participants/me/club", json={"club_code": "PAL"}).status_code == 200
        assert host.post(f"/api/v1/rooms/{room_id}/start").status_code == 409
        assert member.put(f"/api/v1/rooms/{room_id}/participants/me/club", json={"club_code": "FLA"}).status_code == 200
        started = host.post(f"/api/v1/rooms/{room_id}/start")
        assert started.status_code == 200
        assert started.json()["data"]["phase"] == "INITIAL_MARKET"


def test_catalog_status_requires_authorized_file_and_reports_coverage(tmp_path: Path) -> None:
    missing = catalog_status(tmp_path / "players.json")
    assert not missing.loaded
    assert "autorizado" in (missing.reason or "")

    catalog_path = tmp_path / "players.json"
    catalog_path.write_text(json.dumps({"catalog_version": "test", "source": "fixture", "source_version": "1", "players": []}), encoding="utf-8")
    incomplete = catalog_status(catalog_path)
    assert not incomplete.loaded
    assert len(incomplete.missing_clubs) == 20


def test_market_api_starts_and_keeps_offers_private_with_test_catalog(monkeypatch) -> None:
    monkeypatch.setattr("app.api.routes.load_catalog", lambda _path: synthetic_catalog("FIVE_A_SIDE", teams=20))
    app = create_app()
    with TestClient(app) as host:
        guest(host)
        room_id = host.post("/api/v1/rooms", json=room_payload()).json()["data"]["id"]
        assert host.put(f"/api/v1/rooms/{room_id}/participants/me/club", json={"club_code": "PAL"}).status_code == 200
        started = host.post(f"/api/v1/rooms/{room_id}/start")
        assert started.status_code == 200
        assert started.json()["data"]["phase"] == "INITIAL_MARKET"
        players = host.get(f"/api/v1/rooms/{room_id}/market/players")
        assert players.status_code == 200
        player_id = players.json()["data"][0]["id"]
        offer = host.post(f"/api/v1/rooms/{room_id}/market/offers", json={"player_id": player_id, "amount_cents": 100_000_000, "idempotency_key": "test-request-001"})
        assert offer.status_code == 201
        state = host.get(f"/api/v1/rooms/{room_id}/market").json()["data"]
        assert state["offers"] == [offer.json()["data"]]


def test_market_two_coaches_selection_reassignment_and_review(monkeypatch) -> None:
    monkeypatch.setattr("app.api.routes.load_catalog", lambda _path: synthetic_catalog("FIVE_A_SIDE", teams=20))
    app = create_app()
    with TestClient(app) as host, TestClient(app) as member:
        guest(host)
        room_id = host.post("/api/v1/rooms", json=room_payload()).json()["data"]["id"]
        guest(member)
        assert member.post(f"/api/v1/rooms/{room_id}/join").status_code == 200
        assert host.put(f"/api/v1/rooms/{room_id}/participants/me/club", json={"club_code": "FLA"}).status_code == 200
        assert member.put(f"/api/v1/rooms/{room_id}/participants/me/club", json={"club_code": "PAL"}).status_code == 200
        assert host.post(f"/api/v1/rooms/{room_id}/start").status_code == 200
        players = host.get(f"/api/v1/rooms/{room_id}/market/players").json()["data"]
        with host.websocket_connect(f"/api/v1/ws/rooms/{room_id}") as socket:
            first = host.post(f"/api/v1/rooms/{room_id}/market/offers", json={"player_id": players[0]["id"], "amount_cents": 200_000_000, "idempotency_key": "market-host-01"})
            assert first.status_code == 201
            assert socket.receive_json() == {"type": "market.offer_changed"}
        second = host.post(f"/api/v1/rooms/{room_id}/market/offers", json={"player_id": players[1]["id"], "amount_cents": 100_000_000, "idempotency_key": "market-host-02"})
        assert second.status_code == 201
        assert member.post(f"/api/v1/rooms/{room_id}/market/offers", json={"player_id": players[0]["id"], "amount_cents": 150_000_000, "idempotency_key": "market-member-01"}).status_code == 201
        assert host.get(f"/api/v1/rooms/{room_id}/market").json()["data"]["reserved_cents"] == 300_000_000
        assert len(member.get(f"/api/v1/rooms/{room_id}/market").json()["data"]["offers"]) == 1

        session = market_service._session(room_id)
        assert host.portal is not None
        host.portal.call(market_service.resolve_if_due, room_id, session.ends_at)
        selection = host.get(f"/api/v1/rooms/{room_id}/market/selection").json()["data"]
        assert len(selection["committed"]) == 2
        assert selection["budget_cents"] == 5_000_000_000
        selected = [second.json()["data"]["id"]]
        preview = host.post(f"/api/v1/rooms/{room_id}/market/selection/preview", json={"offer_ids": selected}).json()["data"]
        assert preview["penalty_cents"] == 10_000_000
        confirmed = host.post(f"/api/v1/rooms/{room_id}/market/selection/confirm", json={"offer_ids": selected})
        assert confirmed.status_code == 200
        assert host.post(f"/api/v1/rooms/{room_id}/market/selection/confirm", json={"offer_ids": selected}).json()["data"] == confirmed.json()["data"]
        assert member.post(f"/api/v1/rooms/{room_id}/market/selection/confirm", json={"offer_ids": []}).status_code == 200
        opportunity = member.get(f"/api/v1/rooms/{room_id}/market/reassignment").json()["data"]["opportunity"]
        assert opportunity["player_id"] == players[0]["id"]
        assert member.post(f"/api/v1/rooms/{room_id}/market/reassignment/{opportunity['offer_id']}", json={"accept": True}).status_code == 200
        review = host.get(f"/api/v1/rooms/{room_id}/market/review").json()["data"]
        assert len(review["entries"]) == 2
        assert host.post(f"/api/v1/rooms/{room_id}/market/review/complete").json()["data"]["phase"] == "SQUAD_MANAGEMENT"
        squad = host.get(f"/api/v1/rooms/{room_id}/squad").json()["data"]
        assert len(squad["players"]) == 8
        formation = squad["formations"][0]
        goalkeeper = next(player for player in squad["players"] if player["position"] == "GK")
        starters = [goalkeeper, *[player for player in squad["players"] if player["id"] != goalkeeper["id"]][:4]]
        assignments = {slot["id"]: player["id"] for slot, player in zip(formation["slots"], starters, strict=True)}
        lineup = host.put(f"/api/v1/rooms/{room_id}/squad/lineup", json={"formation_code": formation["code"], "assignments": assignments})
        assert lineup.status_code == 200
        assert host.put(f"/api/v1/rooms/{room_id}/squad/strategy", json={"strategy": "ATTACKING"}).status_code == 200


def test_withdrawal_penalty_is_validated_and_frozen_when_market_starts(monkeypatch) -> None:
    monkeypatch.setattr("app.api.routes.load_catalog", lambda _path: synthetic_catalog("FIVE_A_SIDE", teams=20))
    app = create_app()
    with TestClient(app) as host, TestClient(app) as member:
        guest(host)
        invalid = host.post("/api/v1/rooms", json={**room_payload(), "withdrawal_penalty_percent": 3})
        assert invalid.status_code == 422

        created = host.post("/api/v1/rooms", json=room_payload())
        room_id = created.json()["data"]["id"]
        guest(member)
        assert member.post(f"/api/v1/rooms/{room_id}/join").status_code == 200
        for percent in (0, 2, 5, 10):
            updated = host.put(f"/api/v1/rooms/{room_id}", json={**room_payload(), "withdrawal_penalty_percent": percent})
            assert updated.status_code == 200
            assert updated.json()["data"]["withdrawal_penalty_percent"] == percent
        assert member.put(f"/api/v1/rooms/{room_id}", json={**room_payload(), "withdrawal_penalty_percent": 0}).status_code == 403
        assert host.put(f"/api/v1/rooms/{room_id}/participants/me/club", json={"club_code": "PAL"}).status_code == 200
        assert member.put(f"/api/v1/rooms/{room_id}/participants/me/club", json={"club_code": "FLA"}).status_code == 200
        assert host.post(f"/api/v1/rooms/{room_id}/start").status_code == 200
        market_state = host.get(f"/api/v1/rooms/{room_id}/market").json()["data"]
        assert market_state["withdrawal_penalty_percent"] == 10
        assert market_state["offer_limit"] == 16
        frozen = host.put(f"/api/v1/rooms/{room_id}", json={**room_payload(), "withdrawal_penalty_percent": 0})
        assert frozen.status_code == 409
        assert host.get(f"/api/v1/rooms/{room_id}/state").json()["data"]["withdrawal_penalty_percent"] == 10


def test_room_manager_lock_allows_only_one_simultaneous_claim() -> None:
    async def scenario() -> list[str]:
        manager = RoomManager()
        room = await manager.create(
            user_id="host",
            display_name="Host",
            name="Concorrência",
            mode="FIVE_A_SIDE",
            initial_budget_cents=5_000_000_000,
            max_human_participants=4,
            privacy="PUBLIC",
        )
        room_id = str(room["id"])
        await manager.join(room_id, "guest", "Guest")

        async def choose(user_id: str) -> str:
            try:
                await manager.select_club(room_id, user_id, "PAL")
                return "won"
            except HTTPException as error:
                return f"failed-{error.status_code}"

        return await asyncio.gather(choose("host"), choose("guest"))

    assert sorted(asyncio.run(scenario())) == ["failed-409", "won"]


def test_legacy_room_snapshot_defaults_withdrawal_penalty_to_five_percent() -> None:
    async def create() -> dict[str, object]:
        return await RoomManager().create(
            user_id="host", display_name="Host", name="Liga antiga", mode="FIVE_A_SIDE",
            initial_budget_cents=5_000_000_000, max_human_participants=4, privacy="PUBLIC",
        )

    legacy_room = asyncio.run(create())
    legacy_room.pop("withdrawal_penalty_percent")
    restored = RoomManager()
    restored.restore(legacy_room)
    assert restored._room(str(legacy_room["id"])).withdrawal_penalty_percent == 5
