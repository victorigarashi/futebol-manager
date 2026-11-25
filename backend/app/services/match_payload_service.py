"""Match payloads for engine adapters (read-only; does not change how matches are played).

route -> MatchPayloadService -> SeasonService.frozen_match (the season owns its matches)
                             -> match_contract.build_match_payload (pure domain)
                             -> engine_adapters (capabilities; PES 2013 behind a feature flag)
"""

from __future__ import annotations

import logging

from app.core.config import get_settings
from app.domain.engine_adapters import (
    EngineCapabilityError,
    PreparedMatch,
    engine_adapter,
    engines_view,
)
from app.domain.market import MarketError
from app.domain.match_contract import MatchPayload, build_match_payload
from app.services.season_service import SeasonService, season_service

logger = logging.getLogger(__name__)


class MatchPayloadService:
    def __init__(self, seasons: SeasonService) -> None:
        self.seasons = seasons

    def payload_for(self, room_id: str, match_id: str) -> MatchPayload:
        frozen = self.seasons.frozen_match(room_id, match_id)
        return build_match_payload(match_id, str(frozen["mode"]), frozen["home"], frozen["away"],
                                   seed=int(frozen["seed"]), competition=str(frozen["competition"]))

    def prepare(self, room_id: str, match_id: str, engine: str) -> PreparedMatch:
        """Hand a match to an engine adapter. Only a match in play can be prepared; a finished
        match keeps its official result and is never handed out again."""
        if self.seasons.frozen_match(room_id, match_id)["status"] != "LIVE":
            raise MarketError("Partida já encerrada: o resultado oficial não pode ser refeito.")
        payload = self.payload_for(room_id, match_id)
        adapter = engine_adapter(engine, pes2013_enabled=get_settings().pes2013_adapter_enabled)
        try:
            prepared = adapter.prepare(payload)
        except EngineCapabilityError:
            logger.info("engine.prepare.refused engine=%s match=%s", engine, match_id)
            raise
        logger.info("engine.prepare.ok engine=%s match=%s checksum=%s", engine, match_id, payload.checksum)
        return prepared

    @staticmethod
    def engines() -> list[dict[str, object]]:
        return engines_view(pes2013_enabled=get_settings().pes2013_adapter_enabled)


match_payload_service = MatchPayloadService(season_service)
