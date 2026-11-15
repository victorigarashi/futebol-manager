"""Browser acceptance server for the career mode (tests only, never production).

Loads the authorized catalog from PLAYER_CATALOG_PATH, creates a two-coach 11x11
league (FLA and REM humans, rivals in round 1; 18 bot clubs), runs the normal market resolution and
leaves the room at round 1 preparation. Identities are written to
CAREER_ACCEPTANCE_STATE so the browser script can sign in as each coach.

    APP_ENVIRONMENT=test PLAYER_CATALOG_PATH=../data/catalogs/players.json \
    LIVE_INTRO_SECONDS=6 \
    CORS_ORIGINS=http://127.0.0.1:5174 ../.venv/bin/python -m uvicorn tools.career_acceptance:app --port 8000
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


@asynccontextmanager
async def acceptance_lifespan(application):
    async with lifespan(application):
        catalog = load_catalog(get_settings().player_catalog_path)
        if catalog is None:
            raise RuntimeError("PLAYER_CATALOG_PATH must point to the authorized catalog.")
        identities = [issue_guest_token(display_name=name) for name in ("Vitão", "Rival da Resenha")]
        room = await room_manager.create(user_id=identities[0][0].id, display_name="Vitão", name="Liga da Resenha", mode="ELEVEN_A_SIDE",
                                         initial_budget_cents=10_000_000_000, max_human_participants=2, privacy="PRIVATE",
                                         initial_market_duration_seconds=120, round_preparation_duration_seconds=3600, withdrawal_penalty_percent=5)
        room_id = room["id"]
        await room_manager.join(room_id, identities[1][0].id, identities[1][0].display_name)
        state = room_manager._room(room_id)
        for (identity, _), club in zip(identities, ("FLA", "REM"), strict=True):
            state.participants[identity.id].selected_club_code = club
        state.phase = "SEASON_PREPARATION"
        market = InitialMarket(catalog, "ELEVEN_A_SIDE", dict.fromkeys((club.code for club in CLUBS), 10_000_000_000))
        complete_test_market(market, room_id)
        # Market already settled by complete_test_market: never "due" again in this fixture.
        market_service.sessions[room_id] = MarketSession(room_id, float("inf"), market, finalized=True, selection_complete=True, market_phase="SQUAD_MANAGEMENT")
        season_service.create(room_id, market)
        path = Path(os.environ.get("CAREER_ACCEPTANCE_STATE", "/tmp/brasileirao-career.json"))
        path.touch(mode=0o600, exist_ok=True)
        path.write_text(json.dumps({"room_id": room_id, "tokens": [token for _, token in identities]}))
        yield


app.router.lifespan_context = acceptance_lifespan
