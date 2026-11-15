import asyncio
import logging
import time

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
    BotChange,
    ClubSelectionRequest,
    JoinByCodeRequest,
    LineupUpdate,
    LiveCommand,
    MarketOfferCreate,
    MarketOfferUpdate,
    MarketReassignmentDecision,
    MarketSelectionConfirm,
    MarketSelectionPreview,
    MatchSettingsUpdate,
    ProfileUpdate,
    RoomCreate,
    RoomUpdate,
    StrategyUpdate,
    TacticsUpdate,
    TransferBuy,
    TransferCounter,
    TransferListingUpdate,
    TransferOfferCreate,
)
from app.core.config import get_settings
from app.domain.catalog import catalog_status, load_catalog
from app.domain.clubs import CLUBS
from app.domain.demo_catalog import create_demo_catalog
from app.domain.market import InitialMarket, MarketError
from app.domain.match_engine import PlayerInput, derived_attributes
from app.domain.rooms import room_manager
from app.services import metrics
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
from app.services.snapshot_store import snapshot_store
from app.services.squad_service import squad_service
from app.services.transfer_service import transfer_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")


def envelope(data: object, revision: int | None = None) -> dict[str, object]:
    meta: dict[str, object] = {"storage": "memory"}
    if revision is not None:
        meta["revision"] = revision
    return {"data": data, "meta": meta}


def snapshot_room(room_id: str) -> None:
    """Persist the current in-memory authority only when snapshots are enabled.

    Serialisation is incremental (finished matches are cached) and the file is written
    off the event loop, debounced (see app.services.snapshot_store)."""
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
    with metrics.cpu("snapshot_serialize"):
        snapshot_store.update(settings.snapshot_path, room_id, result)
    snapshot_store.schedule(settings.snapshot_path)


async def finalize_market(completed_room_id: str) -> None:
    room = room_manager._room(completed_room_id)
    human_clubs = {member.selected_club_code for member in room.participants.values() if member.role != "BOT" and member.selected_club_code}
    managers = {member.selected_club_code: member.display_name for member in room.participants.values() if member.role != "BOT" and member.selected_club_code}
    await market_service.start_selection(completed_room_id, set(human_clubs), managers, room.initial_market_duration_seconds, progress_market)


async def progress_market(room_id: str, phase: str) -> None:
    state = await room_manager.set_market_phase(room_id, phase)
    if phase == "SQUAD_MANAGEMENT" and room_id not in season_service._seasons:
        season_service.create(room_id, market_service._session(room_id).market, double_round_robin=room_manager._room(room_id).double_round_robin)
    snapshot_room(room_id)
    await hub.broadcast(room_id, {"type": f"market.{phase.lower()}", "revision": state["revision"]})


async def notify_market(room_id: str, message: dict[str, object]) -> None:
    await hub.broadcast(room_id, message)


@router.get("/metrics")
async def runtime_metrics() -> dict[str, object]:
    """CPU per subsystem and event-loop lag (operational; no personal data)."""
    return envelope({**metrics.snapshot(), "live_rounds": sum(1 for task in round_tasks.values() if not task.done()),
                     "rooms": len(season_service._seasons)})


@router.get("/health")
async def health() -> dict[str, str]:
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
    return envelope({"id": identity.id, "display_name": identity.display_name, "session_token": token})


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
    return envelope({"id": updated.id, "display_name": updated.display_name, "session_token": token})


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
        team_count=payload.team_count,
        double_round_robin=payload.double_round_robin,
        market_mode=payload.market_mode,
        privacy=payload.privacy,
        initial_market_duration_seconds=payload.initial_market_duration_seconds,
        round_preparation_duration_seconds=payload.round_preparation_duration_seconds,
        withdrawal_penalty_percent=payload.withdrawal_penalty_percent,
        match_duration_seconds=payload.match_duration_seconds,
    )
    snapshot_room(str(state["id"]))
    await hub.broadcast(str(state["id"]), {"type": "room.created", "revision": state["revision"]})
    return envelope(state, int(state["revision"]))


@router.put("/rooms/{room_id}")
async def update_room(
    room_id: str, payload: RoomUpdate, identity: GuestIdentity = Depends(current_identity)
) -> dict[str, object]:
    state = await room_manager.update(room_id, identity.id, **payload.model_dump(exclude_none=True))
    snapshot_room(room_id)
    await hub.broadcast(room_id, {"type": "room.updated", "revision": state["revision"]})
    return envelope(state, int(state["revision"]))


@router.post("/rooms/{room_id}/bots", status_code=status.HTTP_201_CREATED)
async def add_room_bot(room_id: str, payload: BotChange, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    state = await room_manager.add_bot(room_id, identity.id, payload.club_code)
    snapshot_room(room_id)
    await hub.broadcast(room_id, {"type": "room.bot_added", "revision": state["revision"]})
    return envelope(state, int(state["revision"]))


@router.delete("/rooms/{room_id}/bots/{club_code}")
async def remove_room_bot(room_id: str, club_code: str, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    state = await room_manager.remove_bot(room_id, identity.id, club_code.upper())
    snapshot_room(room_id)
    await hub.broadcast(room_id, {"type": "room.bot_removed", "revision": state["revision"]})
    return envelope(state, int(state["revision"]))


@router.put("/rooms/{room_id}/match-settings")
async def update_match_settings(
    room_id: str, payload: MatchSettingsUpdate, identity: GuestIdentity = Depends(current_identity)
) -> dict[str, object]:
    """Host changes the live match duration; it is frozen for a round once it kicks off."""
    season = season_service._seasons.get(room_id)
    live = bool(season and season.live_round)
    previous = room_manager._room(room_id).match_duration_seconds
    state = await room_manager.set_match_duration(room_id, identity.id, payload.match_duration_seconds, live)
    if state["match_duration_seconds"] != previous:
        snapshot_room(room_id)
        await hub.broadcast(room_id, {"type": "room.match_settings", "revision": state["revision"],
                                      "match_duration_seconds": state["match_duration_seconds"]})
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
    # Custom leagues have an exact fixture list. Complete their unclaimed slots here
    # so a host can start a 4/6/8… club league without an invisible manual bot step.
    await room_manager.complete_with_bots(room_id, identity.id)
    room = room_manager._room(room_id)
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
    selected = [member.selected_club_code for member in room.participants.values() if member.selected_club_code]
    budget = 100 if room.market_mode == "COINS" else int(current["initial_budget_cents"])
    # Preserve the former 20-club lobby behaviour: unclaimed clubs become bots.
    active_clubs = selected if len(selected) == room.team_count else [club.code for club in CLUBS]
    teams = {str(club): budget for club in active_clubs}
    try:
        session = market_service.start(room_id, catalog, str(current["mode"]), teams, int(current["initial_market_duration_seconds"]), hub.broadcast, finalize_market, withdrawal_penalty_percent=int(current["withdrawal_penalty_percent"]), on_progressed=progress_market, market_mode=room.market_mode)
        session.market.place_bot_offers({str(member.selected_club_code) for member in room.participants.values() if member.role == "BOT" and member.selected_club_code})
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
        # The exact abilities the match engine uses (derived from overall when the
        # catalog has no component ratings), so the squad screen shows the truth.
        for row in squad["players"]:
            row["match_attributes"] = {k: round(v) for k, v in derived_attributes(PlayerInput(
                str(row["id"]), str(row["name"]), str(row["position"]), str(row["position"]), 50, 50, int(row["overall"]),
                {k: int(v) + int(row["overall"]) - int(row.get("base_overall", row["overall"])) for k, v in dict(row.get("attributes") or {}).items()})).items()}
            row["attributes_derived"] = not row.get("attributes")
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
    unready = season_service.unready(room_id, club)
    snapshot_room(room_id)
    await hub.broadcast(room_id, {"type": "squad.lineup_changed", "club_code": club})
    if unready:
        await hub.broadcast(room_id, {"type": "season.ready_changed", "club_code": club})
    return envelope({**lineup, "ready_cancelled": unready})


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
    unready = season_service.unready(room_id, club)
    snapshot_room(room_id)
    await hub.broadcast(room_id, {"type": "squad.strategy_changed", "club_code": club})
    if unready:
        await hub.broadcast(room_id, {"type": "season.ready_changed", "club_code": club})
    return envelope({**strategy, "ready_cancelled": unready})


@router.put("/rooms/{room_id}/squad/tactics")
async def save_tactics(room_id: str, payload: TacticsUpdate, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    """Starting tactics for the next match (mentality, pressure, style)."""
    club = market_club(room_id, identity.id)
    if room_manager._room(room_id).phase not in {"SQUAD_MANAGEMENT", "SEASON_PREPARATION"}:
        raise HTTPException(status_code=409, detail="Táticas só podem ser alteradas durante a preparação.")
    if room_id in season_service._seasons and season_service._season(room_id).live_round:
        raise HTTPException(status_code=409, detail="Durante o jogo, use os comandos ao vivo.")
    try:
        result = squad_service.save_tactics(room_id, club, payload.model_dump())
    except MarketError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    unready = season_service.unready(room_id, club)
    snapshot_room(room_id)
    await hub.broadcast(room_id, {"type": "squad.strategy_changed", "club_code": club})
    if unready:
        await hub.broadcast(room_id, {"type": "season.ready_changed", "club_code": club})
    return envelope({**result, "ready_cancelled": unready})


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


# Simulation runs in small slices (see SeasonService.simulate_slice) with a yield to
# the event loop after each one, so health checks, requests and sockets are served in
# between. While the broadcast needs work the task keeps going (on a 0.1 CPU host
# idle pauses would waste the CPU share the round is entitled to); it only sleeps once
# it has caught up. Frames are pushed at least every URGENT_BURST_SECONDS.
URGENT_BURST_SECONDS = 0.5
SPARE_BURST_SECONDS = 0.05
IDLE_SLEEP_SECONDS = 0.1
TICK_NOTIFY_SECONDS = 2.0
# Frames reach the client in batches it buffers (it renders ~1 s behind the server
# clock), so pushing more often than this only costs CPU.
FRAME_PUSH_SECONDS = 0.25


# Until when some live broadcast is behind schedule: background pre-simulation backs off.
live_pressure_until = 0.0


async def simulate_round(room_id: str) -> bool:
    """Advance the room's live engines cooperatively. Returns True while still behind."""
    global live_pressure_until
    began = time.perf_counter()
    urgent = more = True
    while urgent and time.perf_counter() - began < URGENT_BURST_SECONDS:
        async with round_locks.setdefault(room_id, asyncio.Lock()):
            if room_id not in season_service._seasons or not season_service._season(room_id).live_round:
                return False
            with metrics.cpu("simulation"):
                urgent, more = season_service.simulate_slice(room_id)
        await asyncio.sleep(0)
    if urgent:
        live_pressure_until = time.perf_counter() + 0.5
        return True
    # Caught up: a little spare work (finishing unwatched matches early), then rest.
    spare_began = time.perf_counter()
    while more and time.perf_counter() - spare_began < SPARE_BURST_SECONDS:
        async with round_locks.setdefault(room_id, asyncio.Lock()):
            if room_id not in season_service._seasons or not season_service._season(room_id).live_round:
                return False
            with metrics.cpu("simulation"):
                urgent, more = season_service.simulate_slice(room_id)
        await asyncio.sleep(0)
        if urgent:
            return True
    return False


async def broadcast_round(room_id: str) -> None:
    completed = False
    crashed = False
    last_tick_broadcast = 0.0
    last_push = 0.0
    try:
        while season_service._season(room_id).live_round:
            behind = await simulate_round(room_id)
            async with round_locks.setdefault(room_id, asyncio.Lock()):
                completed = False
                if season_service.ready_to_finish(room_id):
                    # Every engine is already at the final whistle: committing is cheap.
                    with metrics.cpu("round_commit"):
                        completed = season_service.finish_due(room_id)
                if completed:
                    season = season_service._season(room_id)
                    if season.transfer_window_open:
                        room = room_manager._room(room_id)
                        await room_manager.set_phase(room_id, room.host_user_id, "TRANSFER_WINDOW")
                    snapshot_room(room_id)
            now = season_service.clock()
            if not completed and now - last_push >= FRAME_PUSH_SECONDS:
                # Engines were advanced above; just read each coach's new frames.
                last_push = now
                with metrics.cpu("frame_push"):
                    await hub.push_frames(room_id, lambda club, since, known: season_service.live_frames(room_id, club, since, known_timeline=known))
            if completed or now - last_tick_broadcast >= TICK_NOTIFY_SECONDS:
                # Frames go over the socket; this only nudges score/event refreshes.
                await hub.broadcast(room_id, {"type": "season.round_completed" if completed else "season.tick"})
                last_tick_broadcast = now
            if completed:
                break
            await asyncio.sleep(0 if behind else IDLE_SLEEP_SECONDS)
    except Exception:
        # Never leave a room stuck "live" because one iteration failed: log, pause, retry.
        logger.exception("Falha na transmissão da rodada da sala %s", room_id)
        crashed = True
        await asyncio.sleep(1)
    finally:
        round_tasks.pop(room_id, None)
        # A coach may ready the next round while the completion notification is
        # being sent. Hand that round to a new timer after retiring this task.
        season = season_service._seasons.get(room_id)
        if (completed or crashed) and season and season.live_round:
            schedule_round(room_id)


async def start_round_if_preparation_expired(room_id: str) -> None:
    """Enforce the league's preparation deadline (configured when creating the room)."""
    if room_id not in season_service._seasons:
        return
    room = room_manager._room(room_id)
    if room.phase != "SEASON_PREPARATION":
        return
    humans = {p.selected_club_code for p in room.participants.values() if p.selected_club_code and p.role != "BOT"}
    async with round_locks.setdefault(room_id, asyncio.Lock()):
        try:
            started = season_service.start_if_preparation_expired(
                room_id, market_service._session(room_id).market, humans, room.round_preparation_duration_seconds,
                room.match_duration_seconds)
        except MarketError:
            return
        if started:
            schedule_round(room_id)
            snapshot_room(room_id)
    if started:
        await hub.broadcast(room_id, {"type": "season.round_started", "reason": "preparation_timeout"})


async def prepare_rooms_forever(interval: float = 1.0) -> None:
    """Housekeeping for rooms in preparation (one task for the whole server).

    * enforces the preparation deadline even when nobody is polling the season;
    * spends idle CPU simulating the next round's bot-against-bot matches, one slice
      per room in turn with a yield after each, until there is nothing left to do."""
    while True:
        await asyncio.sleep(interval)
        working: dict[str, tuple[InitialMarket, set[str]]] = {}
        for room_id in list(season_service._seasons):
            try:
                room = room_manager._room(room_id)
                if room.phase != "SEASON_PREPARATION" or room_id not in market_service.sessions:
                    continue
                await start_round_if_preparation_expired(room_id)
                humans = {p.selected_club_code for p in room.participants.values() if p.selected_club_code and p.role != "BOT"}
                working[room_id] = (market_service._session(room_id).market, humans)
            except (KeyError, MarketError):
                continue
            except Exception:
                logger.exception("Falha na preparação da sala %s", room_id)
        began = time.perf_counter()
        while working and time.perf_counter() - began < 2.0:
            if time.perf_counter() < live_pressure_until:
                await asyncio.sleep(0.05)  # live broadcasts first
                continue
            for room_id, (market, humans) in list(working.items()):
                try:
                    async with round_locks.setdefault(room_id, asyncio.Lock()):
                        with metrics.cpu("preparation_presim"):
                            more = season_service.prepare_slice(room_id, market, humans)
                except (KeyError, MarketError):
                    more = False
                except Exception:
                    logger.exception("Falha na pré-simulação da sala %s", room_id)
                    more = False
                if not more:
                    working.pop(room_id)
                await asyncio.sleep(0)


@router.post("/rooms/{room_id}/season/ready")
async def ready_for_round(room_id: str, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    club = market_club(room_id, identity.id)
    room = room_manager._room(room_id)
    humans = {p.selected_club_code for p in room.participants.values() if p.selected_club_code and p.role != "BOT"}
    if room.phase != "SEASON_PREPARATION":
        raise HTTPException(status_code=409, detail="Aguarde a etapa de preparação da rodada.")
    try:
        async with round_locks.setdefault(room_id, asyncio.Lock()):
            # Idempotent: confirming twice is the same as once. The lock makes "every
            # coach ready -> start" atomic, so the round starts exactly once.
            season = season_service._season(room_id)
            season.human_clubs = set(humans)
            result = season_service.ready(room_id, club)
            if not season.live_round and humans.issubset(season.ready_clubs):
                result = season_service.advance(room_id, market_service._session(room_id).market, humans, room_manager._room(room_id).match_duration_seconds)
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
    humans = {p.selected_club_code for p in room.participants.values() if p.selected_club_code and p.role != "BOT"}
    if room.phase != "SEASON_PREPARATION":
        raise HTTPException(status_code=409, detail="Aguarde a etapa de preparação da rodada.")
    try:
        async with round_locks.setdefault(room_id, asyncio.Lock()):
            result = season_service.advance(room_id, market_service._session(room_id).market, humans, room_manager._room(room_id).match_duration_seconds)
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
        async with round_locks.setdefault(room_id, asyncio.Lock()):
            return envelope(season_service.live_view(room_id, club))
    except MarketError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/rooms/{room_id}/season/live/frames")
async def live_frames(room_id: str, since: int = -1, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    """Authoritative positions of the coach's own match since a tick (for the 2D view)."""
    club = market_club(room_id, identity.id)
    try:
        async with round_locks.setdefault(room_id, asyncio.Lock()):
            return envelope(season_service.live_frames(room_id, club, since))
    except MarketError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/rooms/{room_id}/season/live/commands")
async def live_command(room_id: str, payload: LiveCommand, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    """Tactical change or substitution for the coach's own club, validated by the server."""
    club = market_club(room_id, identity.id)
    try:
        async with round_locks.setdefault(room_id, asyncio.Lock()):
            result = season_service.command(room_id, club, payload.model_dump())
            snapshot_room(room_id)
    except MarketError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    await hub.broadcast(room_id, {"type": "season.live_command", "club_code": club, "kind": payload.kind})
    return envelope(result)


@router.get("/rooms/{room_id}/season/preview")
async def season_preview(room_id: str, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    """Next fixture comparison: both projected lineups, sectors and readiness."""
    club = market_club(room_id, identity.id)
    try:
        room = room_manager._room(room_id)
        season_service._season(room_id).human_clubs = {p.selected_club_code for p in room.participants.values() if p.selected_club_code and p.role != "BOT"}
        preview = season_service.preview(room_id, market_service._session(room_id).market, club)
        managers = {p.selected_club_code: p.display_name for p in room.participants.values() if p.selected_club_code}
        for side in ("home", "away"):
            if side in preview:
                preview[side]["manager"] = managers.get(preview[side]["club_code"])
        return envelope(preview)
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
    await start_round_if_preparation_expired(room_id)
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
        return envelope(season_service._personal_match(room_id, match_id, club))
    except MarketError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/rooms/{room_id}/matches/{match_id}/frames")
async def match_frames(room_id: str, match_id: str, start: int = 0, end: int = 600, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    """2D replay window of a finished match, regenerated deterministically by the engine."""
    club = market_club(room_id, identity.id)
    try:
        match = season_service.match(room_id, match_id)
        if club not in (match["home"], match["away"]):
            raise HTTPException(status_code=403, detail="Você pode rever somente as partidas do seu clube.")
        # Re-simulates a finished match on its own engine: safe in a worker thread,
        # where it no longer stalls the event loop.
        return envelope(await asyncio.to_thread(season_service.replay_frames, room_id, match_id, start, end))
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
        # Native browser WebSocket clients cannot attach an Authorization
        # header. The HTTPS query fallback is used only when the Render cookie
        # is unavailable across the static-site/API origins.
        identity = identity_from_token(
            websocket.cookies.get(SESSION_COOKIE) or websocket.query_params.get("access_token")
        )
        if not room_manager.member_of(room_id, identity.id):
            raise HTTPException(status_code=403, detail="Você não participa desta sala.")
    except HTTPException:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    member = room_manager._room(room_id).participants.get(identity.id)
    await hub.connect(room_id, websocket, member.selected_club_code if member else None)
    try:
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
