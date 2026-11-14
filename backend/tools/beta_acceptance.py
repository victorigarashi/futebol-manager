"""Explicit test-only browser fixtures generated with the actual domain engines."""
import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from app.api.routes import market_service, progress_market, room_manager, season_service
from app.domain.clubs import CLUBS
from app.domain.demo_catalog import create_demo_catalog
from app.domain.market import InitialMarket
from app.main import app, lifespan
from app.services.auth import issue_guest_token
from app.services.market_service import MarketSession
from app.tests.fixtures.market_catalog import complete_test_market


@asynccontextmanager
async def beta_lifespan(application):
    if os.environ.get("APP_ENVIRONMENT") not in {"test", "development"}:
        raise RuntimeError("Acceptance fixtures require development/test.")
    async with lifespan(application):
        coaches = [issue_guest_token(display_name=n) for n in ("Ana Resenha", "Bruno Rival")]
        catalog = create_demo_catalog()
        fixtures = {}

        async def create(label, phase, mode="ELEVEN_A_SIDE"):
            coach = coaches[0][0]
            room = await room_manager.create(user_id=coach.id, display_name=coach.display_name,
                name=f"Beta · {label}", mode=mode, initial_budget_cents=5_000_000_000,
                max_human_participants=4, privacy="PRIVATE", initial_market_duration_seconds=1800,
                round_preparation_duration_seconds=3600, withdrawal_penalty_percent=5)
            key = room["id"]
            await room_manager.join(key, coaches[1][0].id, coaches[1][0].display_name)
            state = room_manager._room(key)
            for (identity, _), club in zip(coaches, ("FLA", "REM"), strict=True):
                state.participants[identity.id].selected_club_code = club
            fixtures[label] = key
            if phase == "WAITING":
                return key, None
            market = InitialMarket(catalog, mode, dict.fromkeys((c.code for c in CLUBS), 5_000_000_000))
            market_service.registry._markets[key] = market
            market_service.registry._locks[key] = asyncio.Lock()
            session = MarketSession(key, time.time() + 1800, market)
            market_service.sessions[key] = session
            state.phase = phase
            return key, session

        await create("lobby", "WAITING")
        _, session = await create("market", "INITIAL_MARKET")
        session.market.submit_offer("FLA", "demo-FLA-12", 11_000_000, "fixture-open-flamengo")
        session.market.submit_offer("REM", "demo-REM-12", 12_000_000, "fixture-open-remo")
        key, session = await create("selection", "MARKET_SELECTION")
        for club, player in (("FLA", "demo-PAL-12"), ("FLA", "demo-BAH-03"), ("REM", "demo-REM-12")):
            session.market.submit_offer(club, player, 12_000_000, f"fixture-select-{player}")
        session.market.resolve()
        await market_service.start_selection(key, {"FLA", "REM"}, {"FLA": "Ana Resenha", "REM": "Bruno Rival"}, 1800, progress_market)
        key, session = await create("reassignment", "MARKET_SELECTION")
        session.market.submit_offer("FLA", "demo-PAL-12", 12_000_000, "fixture-first-claim")
        session.market.submit_offer("REM", "demo-PAL-12", 11_000_000, "fixture-second-claim")
        session.market.resolve()
        await market_service.start_selection(key, {"FLA", "REM"}, {"FLA": "Ana Resenha", "REM": "Bruno Rival"}, 1800, progress_market)
        await market_service.confirm_selection(key, "FLA", [], "fixture-decline-first")
        await market_service.confirm_selection(key, "REM", [], "fixture-confirm-remo")
        cases = [("review", "MARKET_REVIEW", "ELEVEN_A_SIDE"), ("squad5", "SQUAD_MANAGEMENT", "FIVE_A_SIDE"),
                 ("squad11", "SQUAD_MANAGEMENT", "ELEVEN_A_SIDE"), ("season", "SEASON_PREPARATION", "ELEVEN_A_SIDE"),
                 ("postmatch", "SEASON_PREPARATION", "ELEVEN_A_SIDE"), ("transfers", "TRANSFER_WINDOW", "ELEVEN_A_SIDE"),
                 ("champion", "SEASON_PREPARATION", "FIVE_A_SIDE"), ("history", "SEASON_PREPARATION", "FIVE_A_SIDE")]
        for label, phase, mode in cases:
            key, session = await create(label, phase, mode)
            for club, player in (("FLA", "demo-PAL-12"), ("REM", "demo-BAH-03")):
                session.market.submit_offer(club, player, 12_000_000, f"fixture-complete-{player}")
            complete_test_market(session.market, key)
            session.finalized = session.selection_complete = True
            session.managers = {"FLA": "Ana Resenha", "REM": "Bruno Rival"}
            session.market_phase = phase
            if phase == "MARKET_REVIEW":
                continue
            season_service.create(key, session.market)
            original = season_service.clock
            now = [time.time()]
            season_service.clock = lambda clock=now: clock[0]
            try:
                rounds = 38 if label in {"champion", "history"} else 19 if label == "transfers" else 1 if label == "postmatch" else 0
                for number in range(1, rounds + 1):
                    for club in ("FLA", "REM"):
                        season_service.ready(key, club)
                    season_service.advance(key, session.market, {"FLA", "REM"})
                    now[0] += 60
                    season_service.finish_due(key)
                    if number == 19 and label != "transfers":
                        season_service.close_transfer_window(key)
                if label in {"champion", "history"}:
                    for _ in range(3):
                        season_service.advance(key, session.market, {"FLA", "REM"})
                if label == "history":
                    season_service.create_next_season(key, session.market)
            finally:
                season_service.clock = original
        state_path = Path(os.environ.get("BETA_ACCEPTANCE_STATE", "/tmp/brasileirao-beta-state.json"))
        state_path.touch(mode=0o600, exist_ok=True)
        state_path.write_text(json.dumps({"rooms": fixtures, "tokens": [token for _, token in coaches]}))
        yield
        for session in market_service.sessions.values():
            for task in (session.task, session.timer_task):
                if task:
                    task.cancel()


app.router.lifespan_context = beta_lifespan
