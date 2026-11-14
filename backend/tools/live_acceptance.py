"""Isolated, explicitly synthetic fixture server for browser acceptance tests only."""
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from app.api.routes import market_service, room_manager, season_service
from app.domain.clubs import CLUBS
from app.domain.market import InitialMarket
from app.main import app, lifespan
from app.services.auth import issue_guest_token
from app.services.market_service import MarketSession
from app.tests.fixtures.market_catalog import complete_test_market, synthetic_catalog


@asynccontextmanager
async def acceptance_lifespan(app):
    async with lifespan(app):
        identities = [issue_guest_token(display_name=name) for name in ('Tecnico Casa', 'Tecnico Visitante', 'Tecnico Rival')]
        room = await room_manager.create(user_id=identities[0][0].id, display_name='Tecnico Casa', name='Liga de verificação', mode='ELEVEN_A_SIDE', initial_budget_cents=10_000_000_000, max_human_participants=3, privacy='PUBLIC', initial_market_duration_seconds=120, round_preparation_duration_seconds=3600, withdrawal_penalty_percent=5)
        room_id = room['id']
        for identity, _ in identities[1:]:
            await room_manager.join(room_id, identity.id, identity.display_name)
        state = room_manager._room(room_id)
        for (identity, _), club in zip(identities, ('FLA', 'REM', 'PAL'), strict=True):
            state.participants[identity.id].selected_club_code = club
        state.phase = 'SEASON_PREPARATION'
        clubs = dict.fromkeys((club.code for club in CLUBS), 10_000_000_000)
        market = InitialMarket(synthetic_catalog('ELEVEN_A_SIDE', teams=20), 'ELEVEN_A_SIDE', clubs)
        complete_test_market(market, room_id)
        market_service.sessions[room_id] = MarketSession(room_id, 0, market, finalized=True, selection_complete=True, market_phase='SQUAD_MANAGEMENT')
        season_service.create(room_id, market)
        state_path = Path(os.environ.get('LIVE_ACCEPTANCE_STATE', '/tmp/brasileirao-acceptance.json'))
        state_path.touch(mode=0o600, exist_ok=True)
        with state_path.open('w') as f:
            json.dump({'room_id':room_id, 'tokens':[token for _,token in identities]},f)
        yield
app.router.lifespan_context = acceptance_lifespan
