"""Boot-time recovery for the single-process JSON snapshot format."""

from __future__ import annotations

import logging
import time

from app.core.config import get_settings
from app.domain.clubs import CLUBS
from app.domain.rooms import room_manager
from app.services.market_service import market_service
from app.services.season_service import season_service
from app.services.snapshots import load_snapshot
from app.services.squad_service import squad_service
from app.services.transfer_service import transfer_service

logger = logging.getLogger(__name__)


def _upgrade_legacy_market(room_id: str, mode: str, raw: dict[str, object], ends_at: float | None) -> dict[str, object]:
    from app.domain.catalog import CatalogPlayer

    catalog_players: dict[str, dict[str, object]] = {}
    teams: dict[str, dict[str, object]] = {}
    offers: list[dict[str, object]] = []
    sequence = 0
    for club, result in raw.items():
        if not isinstance(result, dict):
            raise ValueError(f"Snapshot legado de mercado inválido para {club}.")
        roster = result.get("roster", [])
        if not isinstance(roster, list):
            raise ValueError("Snapshot legado contém elenco inválido.")
        for player in roster:
            if isinstance(player, dict):
                parsed = CatalogPlayer.model_validate(player)
                catalog_players[parsed.id] = parsed.model_dump(mode="json")
        teams[str(club)] = {"budget_cents": int(result["budget_cents"]), "reserved_cents": 0, "roster": [str(player["id"]) for player in roster if isinstance(player, dict)]}
        for offer in result.get("offers", []):
            sequence += 1
            offers.append({"id": str(offer["id"]), "idempotency_key": f"legacy:{offer['id']}", "club_code": str(club), "player_id": str(offer["player_id"]), "amount_cents": int(offer["amount_cents"]), "sequence": sequence, "status": str(offer["status"])})
    players = list(catalog_players.values())
    if not players:
        raise ValueError(f"Snapshot legado da sala {room_id} não contém catálogo para recuperação.")
    return {
        "room_id": room_id, "ends_at": float(ends_at or time.time()), "finalized": True,
        "catalog": {"catalog_version": "restored-legacy", "source": str(players[0]["source"]), "source_version": str(players[0]["source_version"]), "players": players},
        "mode": mode, "resolved": True, "sequence": sequence, "teams": teams, "offers": offers,
    }


async def restore_snapshots() -> None:
    settings = get_settings()
    if not settings.enable_json_snapshots or not settings.snapshot_path.exists():
        return
    snapshot = load_snapshot(settings.snapshot_path)
    rooms = snapshot.get("rooms")
    if not isinstance(rooms, dict):
        raise ValueError("Snapshot sem mapa de salas.")
    prepared: list[tuple[str, dict[str, object]]] = []
    for room_id, raw in rooms.items():
        if not isinstance(raw, dict) or not isinstance(raw.get("room"), dict):
            raise ValueError(f"Snapshot contém estrutura inválida para a sala {room_id}.")
        if str(raw["room"].get("id")) != str(room_id):
            raise ValueError("ID da sala não confere com a chave no snapshot.")
        prepared.append((str(room_id), raw))

    # Validate the complete envelope before hydrating any room in memory.
    for room_id, raw in prepared:
        room = raw["room"]
        market = raw.get("market")
        if isinstance(market, dict) and "room_id" not in market:
            raw["market"] = _upgrade_legacy_market(room_id, str(room.get("mode")), market, room.get("market_ends_at"))
            market = raw["market"]
        if market is not None and (not isinstance(market, dict) or str(market.get("room_id")) != room_id):
            raise ValueError(f"Snapshot de mercado inválido para a sala {room_id}.")
        if isinstance(market, dict):
            catalog = market.get("catalog", {})
            if isinstance(catalog, dict) and catalog.get("source") == "synthetic-demo" and not getattr(settings, "enable_demo_catalog", False):
                raise ValueError("Snapshot de demonstração não pode ser aberto em produção.")
            if isinstance(catalog, dict) and getattr(settings, "enable_demo_catalog", False) and catalog.get("source") != "synthetic-demo":
                raise ValueError("Snapshot de produção não pode ser aberto no modo demonstração.")
            expected_clubs = {club.code for club in CLUBS}
            market_clubs = set(map(str, market.get("teams", {})))
            selected = {str(member.get("selected_club_code")) for member in room.get("participants", []) if member.get("selected_club_code")}
            # Custom leagues use a subset of the 20 clubs (4 to 20).
            if not market_clubs.issubset(expected_clubs) or len(market_clubs) not in (4, 6, 8, 10, 12, 16, 20) or not selected.issubset(market_clubs):
                raise ValueError(f"Snapshot de mercado não corresponde aos clubes da sala {room_id}.")
        if room.get("phase") != "WAITING" and market is None:
            raise ValueError(f"A sala {room_id} avançou sem estado de mercado restaurável.")
        season = raw.get("season")
        if season is not None and not isinstance(season, dict):
            raise ValueError(f"Snapshot de temporada inválido para a sala {room_id}.")
        pack = raw.get("pack")
        if isinstance(pack, dict):
            from app.api.routes import finish_pack
            from app.services.pack_service import pack_service
            pack_service.restore_room(room_id, pack)
            if room_manager._room(room_id).phase == "PACK":
                pack_service.schedule_deadline(room_id, finish_pack)
        transfers = raw.get("transfers", {"offers": [], "operations": []})
        if not isinstance(transfers, dict):
            raise ValueError(f"Snapshot de transferências inválido para a sala {room_id}.")
        if isinstance(season, dict) and "fixtures" not in season and int(season.get("current_round", 1)) > 1:
            raise ValueError(f"Snapshot legado da sala {room_id} omite resultados/eventos já simulados; arquivo preservado para recuperação manual.")

    # Domain validation is staged in isolated service instances without timers.
    # No live room is hydrated if a later room has corrupt financial or replay data.
    from app.domain.rooms import RoomManager
    from app.domain.squad import validate_lineup
    from app.services.market_service import MarketService
    from app.services.season_service import SeasonService
    from app.services.squad_service import SquadService
    from app.services.transfer_service import TransferService

    staged_rooms, staged_market = RoomManager(), MarketService()
    staged_seasons, staged_squads = SeasonService(), SquadService()
    staged_transfers = TransferService()

    async def ignore_event(_room_id: str, _event: dict[str, object]) -> None:
        return None

    for room_id, raw in prepared:
        staged_rooms.restore(raw["room"])
        market_payload = raw.get("market")
        if isinstance(market_payload, dict):
            session = staged_market.restore_room(market_payload, ignore_event, schedule_tasks=False)
            lineups = raw.get("lineups", {})
            if isinstance(lineups, dict):
                if "lineups" not in lineups or "strategies" not in lineups:
                    lineups = {"lineups": lineups, "strategies": {}}
                staged_squads.restore_room(room_id, lineups)
                for club, lineup in lineups.get("lineups", {}).items():
                    if club not in session.market.teams:
                        raise ValueError("Escalação do snapshot referencia clube inexistente.")
                    validate_lineup(mode=session.market.mode, formation_code=lineup["formation_code"],
                                    assignments=lineup["assignments"], roster=session.market.teams[club].roster,
                                    players=session.market.catalog)
            season = raw.get("season")
            if isinstance(season, dict) and "fixtures" in season:
                staged_seasons.restore_room(room_id, season)
            staged_transfers.restore_room(room_id, raw.get("transfers", {"offers": [], "operations": []}))
        if isinstance(raw.get("draft"), dict):
            from app.domain.draft import DraftState
            DraftState.from_dict(dict(raw["draft"]["state"]))  # validates instances before hydrating

    from app.api.routes import finalize_market, notify_market, progress_market, room_rules

    for room_id, raw in prepared:
        room_manager.restore(raw["room"])
        market_payload = raw.get("market")
        if isinstance(market_payload, dict):
            session = market_service.restore_room(market_payload, notify_market, finalize_market, progress_market)
            if session.market.selection_complete and room_id not in season_service._seasons:
                season_service.create(room_id, session.market, double_round_robin=room_manager._room(room_id).double_round_robin, rules=room_rules(room_manager._room(room_id)))
        lineups = raw.get("lineups", {})
        if isinstance(lineups, dict):
            if "lineups" not in lineups or "strategies" not in lineups:
                lineups = {"lineups": lineups, "strategies": {}}
            squad_service.restore_room(room_id, lineups)
        season = raw.get("season")
        if isinstance(season, dict):
            if "fixtures" in season:
                season_service.restore_room(room_id, season)
            elif room_id in market_service.sessions:
                season_service.create(room_id, market_service._session(room_id).market, double_round_robin=room_manager._room(room_id).double_round_robin, rules=room_rules(room_manager._room(room_id)))
        elif room_id in market_service.sessions and market_service._session(room_id).market.selection_complete:
            season_service.create(room_id, market_service._session(room_id).market, double_round_robin=room_manager._room(room_id).double_round_robin, rules=room_rules(room_manager._room(room_id)))
        draft = raw.get("draft")
        if isinstance(draft, dict):
            from app.api.routes import finish_draft
            from app.services.draft_service import draft_service
            draft_service.restore_room(room_id, draft)
            if room_manager._room(room_id).phase == "DRAFT":
                draft_service.schedule_deadline(room_id, finish_draft)
        transfers = raw.get("transfers", {"offers": [], "operations": []})
        if isinstance(transfers, dict):
            transfer_service.restore_room(room_id, transfers)
    logger.info("Restored %d game rooms from JSON snapshots", len(prepared))
