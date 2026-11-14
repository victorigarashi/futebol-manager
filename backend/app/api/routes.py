import asyncio

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)

from app.api.schemas import (
    ClubSelectionRequest,
    JoinByCodeRequest,
    LineupUpdate,
    MarketOfferCreate,
    MarketOfferUpdate,
    MarketReassignmentDecision,
    MarketSelectionConfirm,
    MarketSelectionPreview,
    ProfileUpdate,
    RoomCreate,
    RoomUpdate,
    StrategyUpdate,
    TransferBuy,
    TransferCounter,
    TransferListingUpdate,
    TransferOfferCreate,
)
from app.core.config import get_settings
from app.domain.catalog import catalog_status, load_catalog
from app.domain.clubs import CLUBS
from app.domain.demo_catalog import create_demo_catalog
from app.domain.market import MarketError
from app.domain.rooms import room_manager
from app.services.auth import (
    SESSION_COOKIE,
    GuestIdentity,
    current_identity,
    identity_from_token,
    issue_guest_token,
)
from app.services.market_service import market_service
from app.services.realtime import hub
from app.services.season_service import season_service
from app.services.snapshots import load_snapshot, write_snapshot
from app.services.squad_service import squad_service
from app.services.transfer_service import transfer_service

router = APIRouter(prefix="/api/v1")


def envelope(data: object, revision: int | None = None) -> dict[str, object]:
    meta: dict[str, object] = {"storage": "memory"}
    if revision is not None:
        meta["revision"] = revision
    return {"data": data, "meta": meta}


def snapshot_room(room_id: str) -> None:
    """Persist the current in-memory authority only when snapshots are enabled."""
    settings = get_settings()
    if not settings.enable_json_snapshots:
        return
    result = {
        "room": room_manager._state(room_manager._room(room_id)),
        "market": market_service.export_room(room_id) if room_id in market_service.sessions else None,
        "lineups": squad_service.export_room(room_id),
        "season": season_service.export_room(room_id) if room_id in season_service._seasons else None,
        "transfers": transfer_service.export_room(room_id) if room_id in transfer_service._offers or room_id in transfer_service._operations else {"offers": [], "operations": []},
    }
    stored: dict[str, object] = {"rooms": {}}
    if settings.snapshot_path.exists():
        stored = load_snapshot(settings.snapshot_path)
    rooms = stored.setdefault("rooms", {})
    if isinstance(rooms, dict):
        rooms[room_id] = result
    write_snapshot(settings.snapshot_path, stored)


async def finalize_market(completed_room_id: str) -> None:
    room = room_manager._room(completed_room_id)
    human_clubs = {member.selected_club_code for member in room.participants.values() if member.selected_club_code}
    managers = {member.selected_club_code: member.display_name for member in room.participants.values() if member.selected_club_code}
    await market_service.start_selection(completed_room_id, set(human_clubs), managers, room.initial_market_duration_seconds, progress_market)


async def progress_market(room_id: str, phase: str) -> None:
    state = await room_manager.set_market_phase(room_id, phase)
    if phase == "SQUAD_MANAGEMENT" and room_id not in season_service._seasons:
        season_service.create(room_id, market_service._session(room_id).market)
    snapshot_room(room_id)
    await hub.broadcast(room_id, {"type": f"market.{phase.lower()}", "revision": state["revision"]})


async def notify_market(room_id: str, message: dict[str, object]) -> None:
    await hub.broadcast(room_id, message)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "storage": "memory"}


@router.post("/auth/guest", status_code=status.HTTP_201_CREATED)
def create_guest(response: Response) -> dict[str, object]:
    identity, token = issue_guest_token()
    settings = get_settings()
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        max_age=31_536_000,
    )
    return envelope({"id": identity.id, "display_name": identity.display_name})


@router.get("/me")
def me(identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    return envelope({"id": identity.id, "display_name": identity.display_name})


@router.put("/me")
async def update_me(
    payload: ProfileUpdate, response: Response, identity: GuestIdentity = Depends(current_identity)
) -> dict[str, object]:
    updated, token = issue_guest_token(identity.id, payload.display_name)
    settings = get_settings()
    response.set_cookie(key=SESSION_COOKIE, value=token, httponly=True, secure=settings.session_cookie_secure, samesite="lax", max_age=31_536_000)
    changed_rooms = await room_manager.rename_participant(updated.id, updated.display_name)
    for room in changed_rooms:
        await hub.broadcast(str(room["id"]), {"type": "room.participant_renamed", "revision": room["revision"]})
    return envelope({"id": updated.id, "display_name": updated.display_name})


@router.get("/clubs")
def list_clubs() -> dict[str, object]:
    return envelope(
        [{"code": club.code, "name": club.name, "sort_order": club.sort_order} for club in CLUBS]
    )


@router.get("/catalog/status")
def get_catalog_status() -> dict[str, object]:
    settings = get_settings()
    if settings.enable_demo_catalog:
        return envelope({"loaded": True, "player_count": len(create_demo_catalog().players), "catalog_version": "demo-1", "demo": True, "reason": "Demonstração: atletas e valores sintéticos."})
    return envelope({**catalog_status(settings.player_catalog_path).model_dump(), "demo": False})


@router.post("/rooms", status_code=status.HTTP_201_CREATED)
async def create_room(
    payload: RoomCreate, identity: GuestIdentity = Depends(current_identity)
) -> dict[str, object]:
    state = await room_manager.create(
        user_id=identity.id,
        display_name=identity.display_name,
        name=payload.name,
        mode=payload.mode,
        initial_budget_cents=payload.initial_budget_cents,
        max_human_participants=payload.max_human_participants,
        privacy=payload.privacy,
        initial_market_duration_seconds=payload.initial_market_duration_seconds,
        round_preparation_duration_seconds=payload.round_preparation_duration_seconds,
        withdrawal_penalty_percent=payload.withdrawal_penalty_percent,
    )
    snapshot_room(str(state["id"]))
    await hub.broadcast(str(state["id"]), {"type": "room.created", "revision": state["revision"]})
    return envelope(state, int(state["revision"]))


@router.put("/rooms/{room_id}")
async def update_room(
    room_id: str, payload: RoomUpdate, identity: GuestIdentity = Depends(current_identity)
) -> dict[str, object]:
    state = await room_manager.update(room_id, identity.id, **payload.model_dump())
    snapshot_room(room_id)
    await hub.broadcast(room_id, {"type": "room.updated", "revision": state["revision"]})
    return envelope(state, int(state["revision"]))


@router.post("/rooms/{room_id}/start")
async def start_room(room_id: str, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    room = room_manager._room(room_id)
    if room.host_user_id != identity.id:
        raise HTTPException(status_code=403, detail="Apenas o anfitrião pode iniciar a temporada.")
    if any(not member.selected_club_code for member in room.participants.values()):
        raise HTTPException(status_code=409, detail="Todos os técnicos precisam escolher um clube antes de iniciar.")
    host = room.participants.get(identity.id)
    if not host or not host.selected_club_code:
        raise HTTPException(status_code=409, detail="Escolha um clube antes de iniciar a temporada.")
    if room.phase != "WAITING":
        raise HTTPException(status_code=409, detail="A temporada já foi iniciada.")
    settings = get_settings()
    try:
        catalog = create_demo_catalog() if settings.enable_demo_catalog else load_catalog(settings.player_catalog_path)
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=409, detail="Catálogo de atletas inválido ou indisponível. Verifique o arquivo autorizado.") from error
    if catalog and catalog.source == "synthetic-demo" and not settings.enable_demo_catalog:
        raise HTTPException(status_code=409, detail="Catálogo sintético permitido apenas no modo demonstração.")
    if not catalog:
        raise HTTPException(status_code=409, detail="O mercado exige um catálogo autorizado de atletas.")
    current = await room_manager.state_for(room_id, identity.id)
    teams = {club.code: int(current["initial_budget_cents"]) for club in CLUBS}
    try:
        session = market_service.start(room_id, catalog, str(current["mode"]), teams, int(current["initial_market_duration_seconds"]), hub.broadcast, finalize_market, withdrawal_penalty_percent=int(current["withdrawal_penalty_percent"]), on_progressed=progress_market)
    except MarketError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    state = await room_manager.start(room_id, identity.id)
    state = await room_manager.set_market_deadline(room_id, session.ends_at)
    snapshot_room(room_id)
    await hub.broadcast(room_id, {"type": "room.started", "revision": state["revision"]})
    return envelope(state, int(state["revision"]))


def market_club(room_id: str, user_id: str) -> str:
    room = room_manager._room(room_id)
    participant = room.participants.get(user_id)
    if not participant or not participant.selected_club_code:
        raise HTTPException(status_code=403, detail="Escolha um clube para acessar o mercado.")
    return participant.selected_club_code


@router.get("/rooms/{room_id}/market/players")
async def market_players(room_id: str, query: str = "", position: str | None = None, min_overall: int | None = None, max_overall: int | None = None, min_price_cents: int | None = None, max_price_cents: int | None = None, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    club = market_club(room_id, identity.id)
    del club
    try:
        await market_service.resolve_if_due(room_id)
        session = market_service._session(room_id)
        players = session.market.search(query=query, position=position, min_overall=min_overall, max_overall=max_overall, min_price_cents=min_price_cents, max_price_cents=max_price_cents)
    except MarketError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return envelope([player.model_dump() for player in players])


@router.get("/rooms/{room_id}/market/players/{player_id}")
async def market_player(room_id: str, player_id: str, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    market_club(room_id, identity.id)
    try:
        player = market_service._session(room_id).market._player(player_id)
    except MarketError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return envelope(player.model_dump())


@router.get("/rooms/{room_id}/market")
async def market_state(room_id: str, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    club = market_club(room_id, identity.id)
    try:
        await market_service.resolve_if_due(room_id)
        result = market_service.state_for(room_id, club)
        result["withdrawal_penalty_percent"] = room_manager._room(room_id).withdrawal_penalty_percent
        return envelope(result)
    except MarketError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/rooms/{room_id}/market/result")
async def market_result(room_id: str, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    club = market_club(room_id, identity.id)
    try:
        await market_service.resolve_if_due(room_id)
        return envelope(market_service.result_for(room_id, club))
    except MarketError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/rooms/{room_id}/market/selection")
async def market_selection(room_id: str, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    club = market_club(room_id, identity.id)
    try:
        return envelope(market_service.selection_for(room_id, club))
    except MarketError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/rooms/{room_id}/market/selection/preview")
async def preview_market_selection(room_id: str, payload: MarketSelectionPreview, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    club = market_club(room_id, identity.id)
    try:
        return envelope(await market_service.preview_selection(room_id, club, payload.offer_ids))
    except MarketError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/rooms/{room_id}/market/selection/confirm")
async def confirm_market_selection(room_id: str, payload: MarketSelectionConfirm, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    club = market_club(room_id, identity.id)
    operation_id = f"{room_id}:initial-market:selection:{club}"
    try:
        result = await market_service.confirm_selection(room_id, club, payload.offer_ids, operation_id)
    except MarketError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    snapshot_room(room_id)
    await hub.broadcast(room_id, {"type": "market.selection_updated"})
    return envelope(result)


@router.get("/rooms/{room_id}/market/reassignment")
async def market_reassignment(room_id: str, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    club = market_club(room_id, identity.id)
    try:
        current = market_service.current_reassignment_for(room_id, club)
        return envelope({"phase": room_manager._room(room_id).phase, "opportunity": current})
    except MarketError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/rooms/{room_id}/market/reassignment/{offer_id}")
async def decide_market_reassignment(room_id: str, offer_id: str, payload: MarketReassignmentDecision, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    club = market_club(room_id, identity.id)
    try:
        result = await market_service.respond_reassignment(room_id, club, offer_id, payload.accept)
    except MarketError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    snapshot_room(room_id)
    await hub.broadcast(room_id, {"type": "market.reassignment_updated"})
    return envelope(result)


@router.get("/rooms/{room_id}/market/review")
async def market_review(room_id: str, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    market_club(room_id, identity.id)
    try:
        return envelope(market_service.review_for(room_id))
    except MarketError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/rooms/{room_id}/market/review/complete")
async def complete_market_review(room_id: str, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    if room_manager._room(room_id).host_user_id != identity.id:
        raise HTTPException(status_code=403, detail="Apenas o anfitrião pode concluir a review do mercado.")
    try:
        await market_service.complete_review(room_id)
    except MarketError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    snapshot_room(room_id)
    return envelope(await room_manager.state_for(room_id, identity.id))


@router.get("/rooms/{room_id}/squad")
async def get_squad(room_id: str, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    club = market_club(room_id, identity.id)
    try:
        await market_service.resolve_if_due(room_id)
        squad = squad_service.squad(room_id, club)
        if room_id in season_service._seasons:
            market = market_service._session(room_id).market
            squad["players"] = [transfer_service.player_view(room_id, market, player.id) for player in market.catalog.values() if player.id in market.teams[club].roster]
        return envelope(squad)
    except MarketError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.put("/rooms/{room_id}/squad/lineup")
async def save_lineup(room_id: str, payload: LineupUpdate, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    club = market_club(room_id, identity.id)
    if room_manager._room(room_id).phase not in {"SQUAD_MANAGEMENT", "SEASON_PREPARATION"}:
        raise HTTPException(status_code=409, detail="A escalação só pode ser alterada após a review do mercado.")
    if room_id in season_service._seasons and season_service._season(room_id).live_round:
        raise HTTPException(status_code=409, detail="Aguarde o fim da partida para alterar o elenco.")
    try:
        lineup = squad_service.save_lineup(room_id, club, payload.formation_code, payload.assignments)
    except MarketError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    snapshot_room(room_id)
    await hub.broadcast(room_id, {"type": "squad.lineup_changed", "club_code": club})
    return envelope(lineup)


@router.put("/rooms/{room_id}/squad/strategy")
async def save_strategy(room_id: str, payload: StrategyUpdate, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    club = market_club(room_id, identity.id)
    if room_manager._room(room_id).phase not in {"SQUAD_MANAGEMENT", "SEASON_PREPARATION"}:
        raise HTTPException(status_code=409, detail="Estratégias só podem ser alteradas durante a preparação da temporada.")
    if room_id in season_service._seasons and season_service._season(room_id).live_round:
        raise HTTPException(status_code=409, detail="Aguarde o fim da partida para alterar a estratégia.")
    try:
        strategy = squad_service.save_strategy(room_id, club, payload.strategy)
    except MarketError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    snapshot_room(room_id)
    await hub.broadcast(room_id, {"type": "squad.strategy_changed", "club_code": club})
    return envelope(strategy)


@router.post("/rooms/{room_id}/season/start")
async def start_season(room_id: str, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    state = await room_manager.start_season(room_id, identity.id)
    snapshot_room(room_id)
    await hub.broadcast(room_id, {"type": "season.started", "revision": state["revision"]})
    return envelope(state, int(state["revision"]))


# One task and lock per room; all clients read the same server-owned event prefix.
round_tasks: dict[str, asyncio.Task] = {}
round_locks: dict[str, asyncio.Lock] = {}


def schedule_round(room_id: str) -> None:
    if room_id not in round_tasks or round_tasks[room_id].done():
        round_tasks[room_id] = asyncio.create_task(broadcast_round(room_id))


async def broadcast_round(room_id: str) -> None:
    completed = False
    try:
        while season_service._season(room_id).live_round:
            async with round_locks.setdefault(room_id, asyncio.Lock()):
                completed = season_service.finish_due(room_id)
                if completed:
                    season = season_service._season(room_id)
                    if season.transfer_window_open:
                        room = room_manager._room(room_id)
                        await room_manager.set_phase(room_id, room.host_user_id, "TRANSFER_WINDOW")
                    snapshot_room(room_id)
            await hub.broadcast(room_id, {"type": "season.round_completed" if completed else "season.tick"})
            if completed:
                break
            remaining = season_service._season(room_id).live_round["ends_at"] - season_service.clock()
            await asyncio.sleep(max(0, min(.2, remaining)))
    finally:
        round_tasks.pop(room_id, None)
        # A coach may ready the next round while the completion notification is
        # being sent. Hand that round to a new timer after retiring this task.
        season = season_service._seasons.get(room_id)
        if completed and season and season.live_round:
            schedule_round(room_id)


@router.post("/rooms/{room_id}/season/ready")
async def ready_for_round(room_id: str, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    club = market_club(room_id, identity.id)
    room = room_manager._room(room_id)
    humans = {p.selected_club_code for p in room.participants.values() if p.selected_club_code}
    if room.phase != "SEASON_PREPARATION":
        raise HTTPException(status_code=409, detail="Aguarde a etapa de preparação da rodada.")
    try:
        async with round_locks.setdefault(room_id, asyncio.Lock()):
            result = season_service.ready(room_id, club)
            season = season_service._season(room_id)
            if not season.live_round and humans.issubset(season.ready_clubs):
                result = season_service.advance(room_id, market_service._session(room_id).market, humans)
            if season.live_round:
                schedule_round(room_id)
            snapshot_room(room_id)
    except MarketError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    await hub.broadcast(room_id, {"type": "season.round_started" if result["live_round"] else "season.ready_changed"})
    return envelope(result)


@router.post("/rooms/{room_id}/season/advance")
async def advance_round(room_id: str, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    room = room_manager._room(room_id)
    if room.host_user_id != identity.id:
        raise HTTPException(status_code=403, detail="Apenas o anfitrião pode iniciar a rodada.")
    humans = {p.selected_club_code for p in room.participants.values() if p.selected_club_code}
    if room.phase != "SEASON_PREPARATION":
        raise HTTPException(status_code=409, detail="Aguarde a etapa de preparação da rodada.")
    try:
        async with round_locks.setdefault(room_id, asyncio.Lock()):
            result = season_service.advance(room_id, market_service._session(room_id).market, humans)
            if result["live_round"]:
                schedule_round(room_id)
            snapshot_room(room_id)
    except MarketError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    await hub.broadcast(room_id, {"type": "season.changed"})
    return envelope(result)


@router.get("/rooms/{room_id}/season/live")
async def live_round(room_id: str, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    club = market_club(room_id, identity.id)
    try:
        return envelope(season_service.live_view(room_id, club))
    except MarketError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/rooms/{room_id}/season/transfer-window/close")
async def close_transfer_window(room_id: str, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    if room_manager._room(room_id).host_user_id != identity.id:
        raise HTTPException(status_code=403, detail="Apenas o anfitrião pode encerrar a janela.")
    try:
        result = season_service.close_transfer_window(room_id)
        await transfer_service.close_window(room_id)
    except MarketError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    await room_manager.set_phase(room_id, identity.id, "SEASON_PREPARATION")
    snapshot_room(room_id)
    await hub.broadcast(room_id, {"type": "season.transfer_window_closed"})
    return envelope(result)


@router.get("/rooms/{room_id}/career")
async def career_state(room_id: str, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    club = market_club(room_id, identity.id)
    try:
        return envelope(transfer_service.career(room_id, club))
    except MarketError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.put("/rooms/{room_id}/transfers/listings")
async def update_transfer_listing(room_id: str, payload: TransferListingUpdate, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    club = market_club(room_id, identity.id)
    try:
        result = await transfer_service.set_listing(room_id, club, payload.player_id, payload.listed)
    except MarketError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    snapshot_room(room_id)
    await hub.broadcast(room_id, {"type": "transfer.listing_changed"})
    return envelope(result)


@router.get("/rooms/{room_id}/transfers/available")
async def available_transfer_players(room_id: str, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    market_club(room_id, identity.id)
    try:
        return envelope(transfer_service.available_players(room_id))
    except MarketError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/rooms/{room_id}/transfers")
async def transfer_state(room_id: str, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    club = market_club(room_id, identity.id)
    return envelope(transfer_service.view_for(room_id, club))


@router.get("/rooms/{room_id}/transfers/clubs")
async def transfer_clubs(room_id: str, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    club = market_club(room_id, identity.id)
    try:
        return envelope(transfer_service.club_rosters(room_id, club))
    except MarketError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/rooms/{room_id}/transfers/buy")
async def buy_transfer_player(room_id: str, payload: TransferBuy, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    club = market_club(room_id, identity.id)
    try:
        result = await transfer_service.buy_available(room_id, club, payload.incoming_player_id, payload.replace_player_id, payload.amount_cents, payload.operation_id)
    except MarketError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    snapshot_room(room_id)
    await hub.broadcast(room_id, {"type": "transfer.completed", "club_code": club})
    return envelope(result)


@router.post("/rooms/{room_id}/transfers/offers")
async def create_transfer_offer(room_id: str, payload: TransferOfferCreate, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    club = market_club(room_id, identity.id)
    room = room_manager._room(room_id)
    human_clubs = {member.selected_club_code for member in room.participants.values() if member.selected_club_code}
    try:
        offer = await transfer_service.create_offer(room_id, club, payload.incoming_player_id, payload.offered_player_id, payload.amount_cents, payload.idempotency_key, set(human_clubs))
    except MarketError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    snapshot_room(room_id)
    await hub.broadcast(room_id, {"type": "transfer.offer_changed"})
    return envelope(transfer_service._offer_view(offer))


@router.post("/rooms/{room_id}/transfers/offers/{offer_id}/accept")
async def accept_transfer_offer(room_id: str, offer_id: str, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    club = market_club(room_id, identity.id)
    try:
        offer = await transfer_service.accept(room_id, offer_id, club)
    except MarketError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    snapshot_room(room_id)
    await hub.broadcast(room_id, {"type": "transfer.offer_accepted", "offer_id": offer.id})
    return envelope(transfer_service._offer_view(offer))


@router.post("/rooms/{room_id}/transfers/offers/{offer_id}/reject")
async def reject_transfer_offer(room_id: str, offer_id: str, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    club = market_club(room_id, identity.id)
    try:
        offer = await transfer_service.reject(room_id, offer_id, club)
    except MarketError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    snapshot_room(room_id)
    await hub.broadcast(room_id, {"type": "transfer.offer_rejected", "offer_id": offer.id})
    return envelope(transfer_service._offer_view(offer))


@router.post("/rooms/{room_id}/transfers/offers/{offer_id}/counter")
async def counter_transfer_offer(room_id: str, offer_id: str, payload: TransferCounter, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    club = market_club(room_id, identity.id)
    try:
        offer = await transfer_service.counter(room_id, offer_id, club, payload.amount_cents)
    except MarketError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    snapshot_room(room_id)
    await hub.broadcast(room_id, {"type": "transfer.offer_countered", "offer_id": offer.id})
    return envelope(transfer_service._offer_view(offer))


@router.post("/rooms/{room_id}/transfers/offers/{offer_id}/cancel")
async def cancel_transfer_offer(room_id: str, offer_id: str, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    club = market_club(room_id, identity.id)
    try:
        offer = await transfer_service.cancel(room_id, offer_id, club)
    except MarketError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    snapshot_room(room_id)
    await hub.broadcast(room_id, {"type": "transfer.offer_cancelled", "offer_id": offer.id})
    return envelope(transfer_service._offer_view(offer))


@router.post("/rooms/{room_id}/season/next")
async def start_next_season(room_id: str, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    if room_manager._room(room_id).host_user_id != identity.id:
        raise HTTPException(status_code=403, detail="Apenas o anfitrião pode iniciar a próxima temporada.")
    try:
        result = season_service.create_next_season(room_id, market_service._session(room_id).market)
    except MarketError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    snapshot_room(room_id)
    await hub.broadcast(room_id, {"type": "season.next_started", "season_number": result["season_number"]})
    return envelope(result)


@router.get("/rooms/{room_id}/season")
async def season_state(room_id: str, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    market_club(room_id, identity.id)
    try:
        return envelope(season_service.view(room_id))
    except MarketError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/rooms/{room_id}/matches/{match_id}")
async def get_match(room_id: str, match_id: str, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    club = market_club(room_id, identity.id)
    try:
        match = season_service.match(room_id, match_id)
        if club not in (match["home"], match["away"]):
            raise HTTPException(status_code=403, detail="Você pode assistir somente à partida do seu clube.")
        return envelope(match)
    except MarketError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/rooms/{room_id}/market/offers", status_code=status.HTTP_201_CREATED)
async def create_market_offer(room_id: str, payload: MarketOfferCreate, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    club = market_club(room_id, identity.id)
    try:
        offer = await market_service.offer(room_id, club, payload.player_id, payload.amount_cents, payload.idempotency_key)
    except MarketError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    snapshot_room(room_id)
    await hub.broadcast(room_id, {"type": "market.offer_changed"})
    return envelope(market_service._offer_view(offer))


@router.put("/rooms/{room_id}/market/offers/{offer_id}")
async def update_market_offer(room_id: str, offer_id: str, payload: MarketOfferUpdate, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    club = market_club(room_id, identity.id)
    try:
        offer = await market_service.update_offer(room_id, club, offer_id, payload.amount_cents)
    except MarketError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    snapshot_room(room_id)
    await hub.broadcast(room_id, {"type": "market.offer_changed"})
    return envelope(market_service._offer_view(offer))


@router.delete("/rooms/{room_id}/market/offers/{offer_id}")
async def cancel_market_offer(room_id: str, offer_id: str, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    club = market_club(room_id, identity.id)
    try:
        offer = await market_service.cancel_offer(room_id, club, offer_id)
    except MarketError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    snapshot_room(room_id)
    await hub.broadcast(room_id, {"type": "market.offer_changed"})
    return envelope(market_service._offer_view(offer))


@router.get("/rooms/mine")
def my_rooms(identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    return envelope(room_manager.list_for(identity.id))


@router.get("/rooms")
def list_rooms(identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    del identity
    return envelope(room_manager.list())


@router.post("/rooms/join")
async def join_by_code(
    payload: JoinByCodeRequest, identity: GuestIdentity = Depends(current_identity)
) -> dict[str, object]:
    state = await room_manager.join_by_code(payload.code, identity.id, identity.display_name)
    snapshot_room(str(state["id"]))
    await hub.broadcast(
        str(state["id"]), {"type": "room.participant_joined", "revision": state["revision"]}
    )
    return envelope(state, int(state["revision"]))


@router.post("/rooms/{room_id}/join")
async def join_room(
    room_id: str, identity: GuestIdentity = Depends(current_identity)
) -> dict[str, object]:
    state = await room_manager.join(room_id, identity.id, identity.display_name)
    snapshot_room(room_id)
    await hub.broadcast(
        str(state["id"]), {"type": "room.participant_joined", "revision": state["revision"]}
    )
    return envelope(state, int(state["revision"]))


@router.get("/rooms/{room_id}/state")
async def room_state(
    room_id: str, identity: GuestIdentity = Depends(current_identity)
) -> dict[str, object]:
    state = await room_manager.state_for(room_id, identity.id)
    return envelope(state, int(state["revision"]))


@router.put("/rooms/{room_id}/participants/me/club")
async def choose_club(
    room_id: str,
    payload: ClubSelectionRequest,
    identity: GuestIdentity = Depends(current_identity),
) -> dict[str, object]:
    state = await room_manager.select_club(room_id, identity.id, payload.club_code)
    snapshot_room(room_id)
    await hub.broadcast(
        room_id,
        {
            "type": "room.club_claimed",
            "revision": state["revision"],
            "club_code": payload.club_code,
        },
    )
    return envelope(state, int(state["revision"]))


@router.websocket("/ws/rooms/{room_id}")
async def room_websocket(websocket: WebSocket, room_id: str) -> None:
    try:
        settings = get_settings()
        origin = websocket.headers.get("origin")
        if settings.app_environment == "production" and origin not in settings.cors_origins:
            raise HTTPException(status_code=403, detail="Origem não autorizada.")
        if origin and "*" not in settings.cors_origins and origin not in settings.cors_origins:
            raise HTTPException(status_code=403, detail="Origem não autorizada.")
        identity = identity_from_token(websocket.cookies.get(SESSION_COOKIE))
        if not room_manager.member_of(room_id, identity.id):
            raise HTTPException(status_code=403, detail="Você não participa desta sala.")
    except HTTPException:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await hub.connect(room_id, websocket)
    try:
        member = room_manager._room(room_id).participants.get(identity.id)
        if room_id in season_service._seasons and member and member.selected_club_code:
            club = member.selected_club_code
            await websocket.send_json({"type": "season.sync", "data": season_service.live_view(room_id, club)})
        while True:
            message = await websocket.receive_text()
            if message == "ping":
                await websocket.send_text("pong")
                continue
            if len(message.encode("utf-8")) > 4096:
                await websocket.close(code=status.WS_1009_MESSAGE_TOO_BIG)
                break
    except (WebSocketDisconnect, RuntimeError, OSError):
        pass
    finally:
        await hub.disconnect(room_id, websocket)
