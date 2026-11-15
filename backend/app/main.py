import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import prepare_rooms_forever, round_tasks, router, schedule_round
from app.core.config import get_settings
from app.domain.market import MarketError
from app.services import metrics
from app.services.http_security import RequestSecurityMiddleware
from app.services.market_service import market_service
from app.services.recovery import restore_snapshots
from app.services.season_service import season_service
from app.services.snapshot_store import snapshot_store


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    await restore_snapshots()
    for room_id, season in season_service._seasons.items():
        if season.live_round:
            schedule_round(room_id)
    housekeeping = asyncio.create_task(prepare_rooms_forever())
    lag = asyncio.create_task(metrics.lag_probe())
    yield
    housekeeping.cancel()
    lag.cancel()
    tasks = list(round_tasks.values())
    for session in market_service.sessions.values():
        tasks.extend(task for task in (session.task, session.timer_task) if task and not task.done())
    tasks = [task for task in tasks if task.get_loop() is asyncio.get_running_loop() and not task.done()]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, housekeeping, lag, return_exceptions=True)
    settings = get_settings()
    if settings.enable_json_snapshots:
        await snapshot_store.flush(settings.snapshot_path)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.add_middleware(RequestSecurityMiddleware, settings=settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    @app.exception_handler(MarketError)
    async def domain_conflict(_request: Request, error: MarketError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(error)})

    app.include_router(router)
    return app


app = create_app()
