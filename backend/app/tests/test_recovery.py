import asyncio
from types import SimpleNamespace

from app.domain.clubs import CLUBS
from app.domain.market import InitialMarket
from app.services import recovery
from app.services.market_service import MarketService, MarketSession
from app.services.season_service import SeasonService
from app.services.snapshots import write_snapshot
from app.services.squad_service import SquadService
from app.tests.fixtures.market_catalog import complete_test_market, synthetic_catalog


def test_boot_recovery_restores_room_market_squad_and_calendar(tmp_path, monkeypatch) -> None:
    room_id = "restore-room"
    clubs = tuple(club.code for club in CLUBS)
    market = InitialMarket(synthetic_catalog("FIVE_A_SIDE", teams=20), "FIVE_A_SIDE", {club: 10_000_000_000 for club in clubs})
    complete_test_market(market, room_id)
    market_source = MarketService()
    market_source.registry._markets[room_id] = market
    market_source.registry._locks[room_id] = asyncio.Lock()
    market_source.sessions[room_id] = MarketSession(room_id, 1_900_000_000, market, finalized=True, selection_complete=True, market_phase="SQUAD_MANAGEMENT")
    season_source = SeasonService()
    season_source.create(room_id, market)
    squad_source = SquadService()
    room = {
        "id": room_id, "code": "ABC123", "name": "Liga de teste", "mode": "FIVE_A_SIDE",
        "initial_budget_cents": 10_000_000_000, "max_human_participants": 1,
        "privacy": "PRIVATE", "initial_market_duration_seconds": 300,
        "round_preparation_duration_seconds": 3600, "phase": "SQUAD_MANAGEMENT",
        "market_ends_at": None, "revision": 2,
        "participants": [{"user_id": "coach", "display_name": "Técnico", "role": "HOST", "selected_club_code": "FLA"}],
    }
    path = tmp_path / "rooms.json"
    write_snapshot(path, {"rooms": {room_id: {"room": room, "market": market_source.export_room(room_id), "lineups": squad_source.export_room(room_id), "season": season_source.export_room(room_id)}}})
    monkeypatch.setattr(recovery, "get_settings", lambda: SimpleNamespace(enable_json_snapshots=True, snapshot_path=path))
    recovery.room_manager._rooms.clear()
    recovery.room_manager._locks.clear()
    recovery.market_service.sessions.clear()
    recovery.market_service.registry._markets.clear()
    recovery.market_service.registry._locks.clear()
    recovery.season_service._seasons.clear()
    recovery.squad_service._lineups.clear()
    recovery.squad_service._strategies.clear()
    try:
        asyncio.run(recovery.restore_snapshots())
        assert recovery.room_manager._room(room_id).participants["coach"].selected_club_code == "FLA"
        assert recovery.market_service._session(room_id).market.teams["FLA"].roster == market.teams["FLA"].roster
        assert recovery.season_service.view(room_id)["current_round"] == 1
    finally:
        recovery.room_manager._rooms.pop(room_id, None)
        recovery.room_manager._locks.pop(room_id, None)
        recovery.market_service.sessions.pop(room_id, None)
        recovery.market_service.registry._markets.pop(room_id, None)
        recovery.market_service.registry._locks.pop(room_id, None)
        recovery.season_service._seasons.pop(room_id, None)
