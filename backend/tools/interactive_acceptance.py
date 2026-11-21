"""Browser acceptance server for the Modo Jogável multiplayer (tests only, never production).

Two human coaches face each other in an interactive (decisive moments) 11x11 semi-final
of a 4-club knockout (the set-up of knockout_acceptance.py, plus execution_mode =
INTERACTIVE). Each coach plays his own attacks with his own renderer (2D or 3D); the
official result must be the same for both, survive a reload and be recorded.

    APP_ENVIRONMENT=test PLAYER_CATALOG_PATH=../data/catalogs/players.json LIVE_INTRO_SECONDS=4 GAMEPLAY_ENGINE=v7 \
    CORS_ORIGINS=http://127.0.0.1:5175 INTERACTIVE_ACCEPTANCE_STATE=/tmp/interactive.json \
    ../.venv/bin/python -m uvicorn tools.interactive_acceptance:app --port 8001
"""

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from app.api.routes import market_service, room_manager, season_service
from app.core.config import get_settings
from app.domain.catalog import load_catalog
from app.domain.market import InitialMarket
from app.main import app, lifespan
from app.services.auth import issue_guest_token
from app.services.market_service import MarketSession
from app.tests.fixtures.market_catalog import complete_test_market

CLUBS = ("FLA", "PAL", "REM", "MIR")  # strength order: FLA/PAL pot 1, REM/MIR pot 2


@asynccontextmanager
async def acceptance_lifespan(application):
    async with lifespan(application):
        catalog = load_catalog(get_settings().player_catalog_path)
        if catalog is None:
            raise RuntimeError("PLAYER_CATALOG_PATH must point to the authorized catalog.")
        identities = [issue_guest_token(display_name=name) for name in ("Vitão", "Rival da Resenha")]
        room = await room_manager.create(user_id=identities[0][0].id, display_name="Vitão", name="Mata-mata da Resenha", mode="ELEVEN_A_SIDE",
                                         initial_budget_cents=10_000_000_000, max_human_participants=2, privacy="PRIVATE", team_count=4,
                                         initial_market_duration_seconds=120, round_preparation_duration_seconds=60, withdrawal_penalty_percent=5,
                                         match_duration_seconds=60, game_mode="DRAFT_KNOCKOUT")
        room_id = room["id"]
        await room_manager.join(room_id, identities[1][0].id, identities[1][0].display_name)
        state = room_manager._room(room_id)
        market = InitialMarket(catalog, "ELEVEN_A_SIDE", dict.fromkeys(CLUBS, 10_000_000_000))
        complete_test_market(market, room_id)
        market_service.sessions[room_id] = MarketSession(room_id, float("inf"), market, finalized=True, selection_complete=True, market_phase="SQUAD_MANAGEMENT")
        season_service.create(room_id, market, rules={"game_mode": "DRAFT_KNOCKOUT", "execution_mode": "INTERACTIVE", "decision_seconds": 10, "ruleset": "ARCADE"})
        season = season_service._season(room_id)
        # Put both humans in the same semi-final (one of them will be eliminated).
        semi = sorted(season.knockout.ties.values(), key=lambda t: t.order)[0]
        humans = (semi.high, semi.low)
        for (identity, _), club in zip(identities, humans, strict=True):
            state.participants[identity.id].selected_club_code = club
        for club in CLUBS:
            if club not in humans:
                await room_manager.add_bot(room_id, identities[0][0].id, club)
        state = room_manager._room(room_id)
        state.phase = "SEASON_PREPARATION"
        path = Path(os.environ.get("INTERACTIVE_ACCEPTANCE_STATE", "/tmp/brasileirao-interactive.json"))
        path.touch(mode=0o600, exist_ok=True)
        path.write_text(json.dumps({"room_id": room_id, "tokens": [token for _, token in identities], "clubs": list(humans)}))
        yield


app.router.lifespan_context = acceptance_lifespan
