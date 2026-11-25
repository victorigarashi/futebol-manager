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

from app.api.routes import market_service, room_manager, season_service, transfer_service
from app.core.config import get_settings
from app.domain.catalog import load_catalog
from app.domain.custom_players import CustomPlayerSpec
from app.domain.market import InitialMarket
from app.main import app, lifespan
from app.services.auth import issue_guest_token
from app.services.market_service import MarketSession
from app.tests.fixtures.market_catalog import complete_test_market

CLUBS = tuple(os.environ.get("ACCEPTANCE_CLUBS", "FLA,PAL,REM,MIR").split(","))   # default: FLA/PAL pot 1, REM/MIR pot 2
# Optional: force the humans' semi-final ("COR,SAO" = Corinthians hosts São Paulo) and prepare the
# squad cases of the Corinthians x São Paulo acceptance (a created player, a player bought from SAO).
PAIR = tuple(os.environ.get("ACCEPTANCE_PAIR", "").split(",")) if os.environ.get("ACCEPTANCE_PAIR") else None
SQUAD_CASES = os.environ.get("ACCEPTANCE_SQUAD_CASES") == "1"


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
                                         match_duration_seconds=int(os.environ.get("ACCEPTANCE_MATCH_SECONDS", "60")), game_mode="DRAFT_KNOCKOUT")
        room_id = room["id"]
        await room_manager.join(room_id, identities[1][0].id, identities[1][0].display_name)
        state = room_manager._room(room_id)
        market = InitialMarket(catalog, "ELEVEN_A_SIDE", dict.fromkeys(CLUBS, 10_000_000_000))
        complete_test_market(market, room_id)
        market_service.sessions[room_id] = MarketSession(room_id, float("inf"), market, finalized=True, selection_complete=True, market_phase="SQUAD_MANAGEMENT")
        season_service.create(room_id, market, rules={"game_mode": "DRAFT_KNOCKOUT", "execution_mode": "INTERACTIVE", "decision_seconds": 10, "ruleset": "ARCADE"})
        season = season_service._season(room_id)
        # Put both humans in the same semi-final (one of them will be eliminated).
        semis = sorted(season.knockout.ties.values(), key=lambda t: t.order)
        semi = semis[0]
        if PAIR:
            others = [c for c in CLUBS if c not in PAIR]
            semi.high, semi.low = PAIR
            semis[1].high, semis[1].low = others
        humans = (semi.high, semi.low)
        cases = {}
        if SQUAD_CASES:
            home, away = humans
            # A player bought from the away club (a completed transfer): he must play for home.
            bought = next(p for p in market.teams[away].roster if market.catalog[p].position == "MF")
            sold = next(p for p in market.teams[home].roster if market.catalog[p].position == "MF")
            market.teams[away].roster[market.teams[away].roster.index(bought)] = sold
            market.teams[home].roster[market.teams[home].roster.index(sold)] = bought
            # A created player, through the real service (pre-season: no match played yet).
            replaced = max((p for p in market.teams[home].roster if market.catalog[p].position == "ST"), key=lambda p: -market.catalog[p].overall)
            spec = CustomPlayerSpec(name="Zé da Resenha", position="ST",
                                    attributes={"pace": 88, "shooting": 82, "passing": 60, "dribbling": 80, "defending": 35, "physical": 70})
            created = await transfer_service.create_custom_player(room_id, home, spec, replaced, "acceptance-custom-1")
            cases = {"bought_from_away": bought, "custom_player": created["player"]["id"], "home": home, "away": away}
        for (identity, _), club in zip(identities, humans, strict=True):
            state.participants[identity.id].selected_club_code = club
        for club in CLUBS:
            if club not in humans:
                await room_manager.add_bot(room_id, identities[0][0].id, club)
        state = room_manager._room(room_id)
        state.phase = "SEASON_PREPARATION"
        path = Path(os.environ.get("INTERACTIVE_ACCEPTANCE_STATE", "/tmp/brasileirao-interactive.json"))
        path.touch(mode=0o600, exist_ok=True)
        path.write_text(json.dumps({"room_id": room_id, "tokens": [token for _, token in identities], "clubs": list(humans), "squad_cases": cases}))
        yield


app.router.lifespan_context = acceptance_lifespan
