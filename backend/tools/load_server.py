"""Light-load test server (tests only, never production).

Creates LOAD_ROOMS leagues (11x11, two human coaches each, 18 bot clubs, settled
market) waiting at round 1 preparation and writes their tokens to LOAD_STATE so
``tools/load_test.py`` can drive them like real browsers.

    APP_ENVIRONMENT=test PLAYER_CATALOG_PATH=../data/catalogs/players.json LOAD_ROOMS=3 \
    LOAD_STATE=/tmp/load.json LIVE_INTRO_SECONDS=3 \
    ../.venv/bin/python -m uvicorn tools.load_server:app --port 8010
"""

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from app.api.routes import market_service, room_manager, season_service
from app.core.config import get_settings
from app.domain.catalog import load_catalog
from app.domain.clubs import CLUBS
from app.domain.market import InitialMarket
from app.main import app, lifespan
from app.services.auth import issue_guest_token
from app.services.market_service import MarketSession
from app.tests.fixtures.market_catalog import complete_test_market

PAIRS = (("FLA", "REM"), ("PAL", "CHA"), ("COR", "MIR"), ("SAO", "CFC"), ("SAN", "VIT"))


@asynccontextmanager
async def load_lifespan(application):
    async with lifespan(application):
        catalog = load_catalog(get_settings().player_catalog_path)
        if catalog is None:
            raise RuntimeError("PLAYER_CATALOG_PATH must point to the catalog.")
        rooms = []
        for index in range(int(os.environ.get("LOAD_ROOMS", "1"))):
            identities = [issue_guest_token(display_name=f"Técnico {index}-{n}") for n in (1, 2)]
            room = await room_manager.create(user_id=identities[0][0].id, display_name=identities[0][0].display_name, name=f"Carga {index}",
                                             mode="ELEVEN_A_SIDE", initial_budget_cents=10_000_000_000, max_human_participants=2,
                                             privacy="PRIVATE", initial_market_duration_seconds=120,
                                             round_preparation_duration_seconds=int(os.environ.get("LOAD_PREPARATION", "3600")),
                                             withdrawal_penalty_percent=5)
            room_id = room["id"]
            await room_manager.join(room_id, identities[1][0].id, identities[1][0].display_name)
            state = room_manager._room(room_id)
            clubs = PAIRS[index % len(PAIRS)]
            for (identity, _), club in zip(identities, clubs, strict=True):
                state.participants[identity.id].selected_club_code = club
            state.phase = "SEASON_PREPARATION"
            state.match_duration_seconds = int(os.environ.get("LOAD_MATCH_SECONDS", "90"))
            market = InitialMarket(catalog, "ELEVEN_A_SIDE", dict.fromkeys((club.code for club in CLUBS), 10_000_000_000))
            complete_test_market(market, room_id)
            market_service.sessions[room_id] = MarketSession(room_id, float("inf"), market, finalized=True, selection_complete=True,
                                                             market_phase="SQUAD_MANAGEMENT")
            season_service.create(room_id, market)
            rooms.append({"room_id": room_id, "tokens": [token for _, token in identities], "clubs": list(clubs)})
        path = Path(os.environ.get("LOAD_STATE", "/tmp/brasileirao-load.json"))
        path.write_text(json.dumps({"rooms": rooms}))
        yield


app.router.lifespan_context = load_lifespan
