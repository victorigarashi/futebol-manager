"""Browser acceptance server for knockouts (tests only, never production).

A 4-club knockout tournament (Draft Eliminatório rules): two humans and two bots,
11x11, 1:00 matches, a 60 s preparation deadline. The humans are drawn into the SAME
semi-final, so one of them is eliminated and must watch the final as a spectator —
the situation that used to freeze the competition (nobody could confirm the final).

    APP_ENVIRONMENT=test PLAYER_CATALOG_PATH=../data/catalogs/players.json LIVE_INTRO_SECONDS=4 \
    CORS_ORIGINS=http://127.0.0.1:5174 KNOCKOUT_ACCEPTANCE_STATE=/tmp/knockout.json \
    ../.venv/bin/python -m uvicorn tools.knockout_acceptance:app --port 8000
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
        season_service.create(room_id, market, rules={"game_mode": "DRAFT_KNOCKOUT"})
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
        path = Path(os.environ.get("KNOCKOUT_ACCEPTANCE_STATE", "/tmp/brasileirao-knockout.json"))
        path.touch(mode=0o600, exist_ok=True)
        path.write_text(json.dumps({"room_id": room_id, "tokens": [token for _, token in identities], "clubs": list(humans)}))
        yield


app.router.lifespan_context = acceptance_lifespan
