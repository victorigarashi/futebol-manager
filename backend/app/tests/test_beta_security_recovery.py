import asyncio
import copy
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import app.main as main_module
from app.core.config import Settings
from app.domain.clubs import CLUBS
from app.domain.market import InitialMarket
from app.domain.rooms import RoomManager
from app.services import recovery
from app.services.market_service import MarketService, MarketSession
from app.services.season_service import SeasonService
from app.services.snapshots import write_snapshot
from app.services.squad_service import SquadService
from app.services.transfer_service import TransferService
from app.tests.fixtures.market_catalog import complete_test_market, synthetic_catalog


def test_mutating_origin_is_checked_and_api_response_has_security_headers():
    with TestClient(main_module.create_app()) as client:
        rejected = client.post("/api/v1/auth/guest", headers={"origin": "https://untrusted.invalid"})
        assert rejected.status_code == 403
        allowed = client.post("/api/v1/auth/guest", headers={"origin": "http://localhost:5174"})
        assert allowed.status_code == 201
        assert allowed.headers["x-content-type-options"] == "nosniff"
        assert allowed.headers["cache-control"] == "no-store"
        assert client.get("/api/v1/me").status_code == 200


def test_request_limits_and_body_limit_are_enforced_before_handler(monkeypatch):
    settings = Settings(_env_file=None, app_environment="test", auth_limit_per_minute=2,
                        request_limit_per_minute=10, max_request_body_bytes=128)
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    with TestClient(main_module.create_app()) as client:
        assert client.post("/api/v1/auth/guest").status_code == 201
        assert client.post("/api/v1/auth/guest").status_code == 201
        throttled = client.post("/api/v1/auth/guest")
        assert throttled.status_code == 429 and throttled.headers["retry-after"] == "60"
        oversized = client.put("/api/v1/me", content=b"x" * 129,
                               headers={"content-type": "application/json"})
        assert oversized.status_code == 413


def test_production_requires_secret_https_secure_cookie_and_forbids_demo():
    valid = {"_env_file": None, "app_environment": "production", "app_secret": "x" * 32,
             "session_cookie_secure": True, "cors_origins": ["https://resenha.example"]}
    assert Settings(**valid).app_environment == "production"
    invalid = [
        {"app_secret": "short"}, {"session_cookie_secure": False},
        {"cors_origins": ["*"]}, {"cors_origins": ["http://resenha.example"]},
        {"enable_demo_catalog": True},
    ]
    for replacement in invalid:
        with pytest.raises(ValidationError):
            Settings(**(valid | replacement))


def test_corrupt_second_room_snapshot_does_not_partially_restore_first_room(tmp_path, monkeypatch):
    clubs = {club.code: 10_000_000_000 for club in CLUBS}
    market = InitialMarket(synthetic_catalog("FIVE_A_SIDE", teams=20), "FIVE_A_SIDE", clubs)
    complete_test_market(market, "snapshot-preflight")
    source_rooms = RoomManager()
    source_markets = MarketService()
    source_seasons = SeasonService()

    async def prepare():
        result = {}
        for index in range(2):
            room = await source_rooms.create(user_id=f"coach-{index}", display_name="Técnico",
                                            name=f"Snapshot liga {index}", mode="FIVE_A_SIDE",
                                            initial_budget_cents=10_000_000_000,
                                            max_human_participants=1, privacy="PRIVATE")
            room_id = room["id"]
            await source_rooms.select_club(room_id, f"coach-{index}", "FLA")
            source_rooms._room(room_id).phase = "SQUAD_MANAGEMENT"
            room = await source_rooms.state_for(room_id, f"coach-{index}")
            source_markets.sessions[room_id] = MarketSession(room_id, 0, market, finalized=True,
                                                           selection_complete=True, market_phase="SQUAD_MANAGEMENT")
            source_seasons.create(room_id, market)
            result[room_id] = {"room": room, "market": source_markets.export_room(room_id),
                               "lineups": {"lineups": {}, "strategies": {}},
                               "season": source_seasons.export_room(room_id),
                               "transfers": {"offers": [], "operations": []}}
        return result

    rooms = asyncio.run(prepare())
    last = list(rooms)[-1]
    rooms[last] = copy.deepcopy(rooms[last])
    rooms[last]["market"]["teams"]["FLA"]["budget_cents"] = -1
    path = tmp_path / "corrupt-second-room.json"
    write_snapshot(path, {"rooms": rooms})
    restored_rooms, restored_markets = RoomManager(), MarketService()
    restored_seasons = SeasonService()
    monkeypatch.setattr(recovery, "get_settings", lambda: SimpleNamespace(enable_json_snapshots=True,
                                                                           snapshot_path=path,
                                                                           enable_demo_catalog=False))
    for name, service in {"room_manager": restored_rooms, "market_service": restored_markets,
                          "season_service": restored_seasons, "squad_service": SquadService(),
                          "transfer_service": TransferService()}.items():
        monkeypatch.setattr(recovery, name, service)
    with pytest.raises(ValueError, match="saldo|reserva"):
        asyncio.run(recovery.restore_snapshots())
    assert not restored_rooms._rooms
    assert not restored_markets.sessions
    assert not restored_seasons._seasons
    assert path.exists()
