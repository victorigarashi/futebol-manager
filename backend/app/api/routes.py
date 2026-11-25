import asyncio
import json
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
from pydantic import ValidationError

from app.api.schemas import (
    BotChange,
    ClubSelectionRequest,
    CustomPlayerCreate,
    DraftFormation,
    DraftPick,
    DraftSlot,
    InstructionsUpdate,
    InteractiveAction,
    JoinByCodeRequest,
    LabCreate,
    LineupUpdate,
    LiveCommand,
    MarketOfferCreate,
    MarketOfferUpdate,
    MarketReassignmentDecision,
    MarketSelectionConfirm,
    MarketSelectionPreview,
    MatchSettingsUpdate,
    PackBench,
    PackPlace,
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
from app.domain.catalog import catalog_status, load_catalog, provenance
from app.domain.clubs import CLUBS
from app.domain.custom_players import (
    ATTRIBUTE_MAX,
    ATTRIBUTE_MIN,
    KEEPER_KEYS,
    MAX_OVERALL,
    MAX_PER_CLUB,
    OUTFIELD_KEYS,
    WEIGHTS,
    CustomPlayerSpec,
)
from app.domain.demo_catalog import create_demo_catalog
from app.domain.draft import DraftError
from app.domain.engine_adapters import EngineCapabilityError
from app.domain.market import InitialMarket, MarketError
from app.domain.match_engine import PlayerInput, derived_attributes
from app.domain.packs import PackError
from app.domain.rooms import RULES, room_manager
from app.services import career_service, metrics
from app.services.auth import (
    SESSION_COOKIE,
    GuestIdentity,
    current_identity,
    identity_from_token,
    issue_guest_token,
)
from app.services.draft_service import draft_service, validate_configuration
from app.services.lab_service import lab_service
from app.services.market_service import MarketSession, market_service
from app.services.match_payload_service import match_payload_service
from app.services.pack_service import pack_service
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
        "draft": draft_service.export_room(room_id),
        "pack": pack_service.export_room(room_id),
    }
    with metrics.cpu("snapshot_serialize"):
        snapshot_store.update(settings.snapshot_path, room_id, result)
    snapshot_store.schedule(settings.snapshot_path)


async def finalize_market(completed_room_id: str) -> None:
    room = room_manager._room(completed_room_id)
    human_clubs = {member.selected_club_code for member in room.participants.values() if member.role != "BOT" and member.selected_club_code}
    managers = {member.selected_club_code: member.display_name for member in room.participants.values() if member.role != "BOT" and member.selected_club_code}
    await market_service.start_selection(completed_room_id, set(human_clubs), managers, room.initial_market_duration_seconds, progress_market)


def check_draft_rules(mode: str, game_mode: str | None, catalog: str | None, min_overall: int | None) -> None:
    """A Draft room must be able to fill every position with its catalog and minimum overall."""
    if game_mode != "DRAFT":
        return
    try:
        validate_configuration(str(catalog or "BRASILEIRAO"), mode, int(min_overall or 0))
    except DraftError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def room_rules(room) -> dict[str, object]:
    return {name: getattr(room, name) for name in RULES}


async def progress_market(room_id: str, phase: str) -> None:
    state = await room_manager.set_market_phase(room_id, phase)
    if phase == "SQUAD_MANAGEMENT" and room_id not in season_service._seasons:
        room = room_manager._room(room_id)
        season_service.create(room_id, market_service._session(room_id).market, double_round_robin=room.double_round_robin,
                              rules=room_rules(room))
    snapshot_room(room_id)
    await hub.broadcast(room_id, {"type": f"market.{phase.lower()}", "revision": state["revision"]})


async def notify_market(room_id: str, message: dict[str, object]) -> None:
    await hub.broadcast(room_id, message)


@router.get("/metrics")
async def runtime_metrics() -> dict[str, object]:
    """CPU per subsystem and event-loop lag (operational; no personal data)."""
    from app.services import realtime
    from app.services.season_service import FRAME_MEMO_HITS, TICKS_SIMULATED
    return envelope({**metrics.snapshot(), "live_rounds": sum(1 for task in round_tasks.values() if not task.done()),
                     "rooms": len(season_service._seasons), "ticks_simulated": TICKS_SIMULATED[0],
                     "frame_memo_hits": FRAME_MEMO_HITS[0], "realtime": realtime.snapshot()})


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
    check_draft_rules(payload.mode, payload.game_mode, payload.draft_catalog, payload.draft_min_overall)
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
        **{name: getattr(payload, name) for name in RULES},
    )
    snapshot_room(str(state["id"]))
    await hub.broadcast(str(state["id"]), {"type": "room.created", "revision": state["revision"]})
    return envelope(state, int(state["revision"]))


@router.put("/rooms/{room_id}")
async def update_room(
    room_id: str, payload: RoomUpdate, identity: GuestIdentity = Depends(current_identity)
) -> dict[str, object]:
    room = room_manager._room(room_id)
    check_draft_rules(payload.mode, payload.game_mode or room.game_mode, payload.draft_catalog or room.draft_catalog,
                      payload.draft_min_overall if payload.draft_min_overall is not None else room.draft_min_overall)
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
    if room.game_mode in ("DRAFT", "DRAFT_KNOCKOUT"):
        return await start_draft(room_id, identity.id)
    if room.game_mode == "PACK":
        return await start_pack(room_id, identity.id)
    if room.game_mode == "SURVIVOR":
        return await start_survivor(room_id, identity.id)
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


async def start_draft(room_id: str, host_id: str) -> dict[str, object]:
    """Draft rooms skip the initial market: squads come from three-card offers."""
    room = room_manager._room(room_id)
    selected = [m.selected_club_code for m in room.participants.values() if m.selected_club_code]
    clubs = selected if len(selected) == room.team_count else [club.code for club in CLUBS]
    humans = {m.selected_club_code for m in room.participants.values() if m.selected_club_code and m.role != "BOT"}
    try:
        async with draft_service.lock(room_id):
            draft_service.start(room_id, room.mode, room.draft_catalog, room.draft_min_overall, [str(c) for c in clubs],
                                {str(c) for c in clubs if c not in humans}, room.bot_difficulty,
                                room.initial_market_duration_seconds, room.initial_budget_cents)
    except DraftError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    state = await room_manager.start(room_id, host_id)
    draft_service.schedule_deadline(room_id, finish_draft)
    snapshot_room(room_id)
    await hub.broadcast(room_id, {"type": "room.started", "revision": state["revision"]})
    return envelope(state, int(state["revision"]))


async def start_pack(room_id: str, host_id: str) -> dict[str, object]:
    """Pack & Play rooms skip the market: squads come from the cards of free packs."""
    room = room_manager._room(room_id)
    selected = [m.selected_club_code for m in room.participants.values() if m.selected_club_code]
    humans = {m.selected_club_code for m in room.participants.values() if m.selected_club_code and m.role != "BOT"}
    try:
        async with pack_service.lock(room_id):
            pack_service.start(room_id, room.mode, room.draft_catalog, room.pack_luck, [str(c) for c in selected],
                               {str(c) for c in selected if c not in humans}, room.bot_difficulty,
                               room.initial_market_duration_seconds, room.initial_budget_cents)
    except (PackError, DraftError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    state = await room_manager.start(room_id, host_id)
    pack_service.schedule_deadline(room_id, finish_pack)
    snapshot_room(room_id)
    await hub.broadcast(room_id, {"type": "room.started", "revision": state["revision"]})
    return envelope(state, int(state["revision"]))


async def finish_pack(room_id: str) -> None:
    await progress_market(room_id, "SQUAD_MANAGEMENT")
    await hub.broadcast(room_id, {"type": "pack.completed"})


async def start_survivor(room_id: str, host_id: str) -> dict[str, object]:
    """Último Sobrevivente is played with the clubs' real squads (no market)."""
    room = room_manager._room(room_id)
    settings = get_settings()
    try:
        catalog = create_demo_catalog() if settings.enable_demo_catalog else load_catalog(settings.player_catalog_path)
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=409, detail="Catálogo de atletas inválido ou indisponível.") from error
    clubs = [str(m.selected_club_code) for m in room.participants.values() if m.selected_club_code]
    market = InitialMarket(catalog, room.mode, dict.fromkeys(clubs, room.initial_budget_cents))
    for club in clubs:
        market.teams[club].roster = [p.id for p in catalog.players if p.club_code == club]
    market.resolved = True
    market.selection_complete = True
    market_service.registry._markets[room_id] = market
    market_service.registry._locks[room_id] = asyncio.Lock()
    market_service.sessions[room_id] = MarketSession(room_id, time.time(), market, finalized=True, selection_complete=True,
                                                     market_phase="SQUAD_MANAGEMENT")
    state = await room_manager.start(room_id, host_id)
    season_service.create(room_id, market, double_round_robin=room.double_round_robin, rules=room_rules(room))
    snapshot_room(room_id)
    await hub.broadcast(room_id, {"type": "room.started", "revision": state["revision"]})
    return envelope(state, int(state["revision"]))


def pack_club(room_id: str, user_id: str) -> str:
    club = market_club(room_id, user_id)
    if room_manager._room(room_id).phase != "PACK":
        raise HTTPException(status_code=409, detail="A sala não está na fase de pacotes.")
    return club


async def pack_action(room_id: str, user_id: str, action) -> dict[str, object]:
    club = pack_club(room_id, user_id)
    try:
        async with pack_service.lock(room_id):
            result = action(club)
            finished = pack_service.complete_due(room_id)  # last squad confirmed: start at once
    except PackError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    snapshot_room(room_id)
    if finished:
        await finish_pack(room_id)
    else:
        await hub.broadcast(room_id, {"type": "pack.updated"})
    return envelope(result)


@router.get("/rooms/{room_id}/pack")
async def pack_state(room_id: str, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    club = market_club(room_id, identity.id)
    try:
        return envelope(pack_service.view(room_id, club))
    except PackError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/rooms/{room_id}/pack/open")
async def pack_open(room_id: str, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    return await pack_action(room_id, identity.id, lambda club: pack_service.open_next(room_id, club))


@router.put("/rooms/{room_id}/pack/formation")
async def pack_formation(room_id: str, payload: DraftFormation, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    return await pack_action(room_id, identity.id, lambda club: pack_service.set_formation(room_id, club, payload.formation_code))


@router.put("/rooms/{room_id}/pack/slot")
async def pack_place(room_id: str, payload: PackPlace, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    return await pack_action(room_id, identity.id, lambda club: pack_service.place(room_id, club, payload.slot_id, payload.catalog_id))


@router.put("/rooms/{room_id}/pack/bench")
async def pack_bench(room_id: str, payload: PackBench, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    return await pack_action(room_id, identity.id, lambda club: pack_service.set_bench(room_id, club, payload.catalog_ids))


@router.post("/rooms/{room_id}/pack/confirm")
async def pack_confirm(room_id: str, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    return await pack_action(room_id, identity.id, lambda club: pack_service.confirm(room_id, club))


@router.post("/rooms/{room_id}/pack/complete")
async def pack_force_complete(room_id: str, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    """The host closes the packs phase: absent managers get an automatic squad."""
    room = room_manager._room(room_id)
    if room.host_user_id != identity.id:
        raise HTTPException(status_code=403, detail="Apenas o anfitrião pode encerrar a fase de pacotes.")
    async with pack_service.lock(room_id):
        finished = pack_service.complete_due(room_id, force=True)
    snapshot_room(room_id)
    if finished:
        await finish_pack(room_id)
    return envelope({"completed": finished})


async def finish_draft(room_id: str) -> None:
    await progress_market(room_id, "SQUAD_MANAGEMENT")
    await hub.broadcast(room_id, {"type": "draft.completed"})


def draft_club(room_id: str, user_id: str) -> str:
    club = market_club(room_id, user_id)
    if room_manager._room(room_id).phase != "DRAFT":
        raise HTTPException(status_code=409, detail="A sala não está na fase de Draft.")
    return club


@router.get("/rooms/{room_id}/draft")
async def draft_state(room_id: str, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    club = market_club(room_id, identity.id)
    try:
        return envelope(draft_service.view(room_id, club))
    except DraftError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.put("/rooms/{room_id}/draft/formation")
async def draft_formation(room_id: str, payload: DraftFormation, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    club = draft_club(room_id, identity.id)
    try:
        async with draft_service.lock(room_id):
            result = draft_service.set_formation(room_id, club, payload.formation_code)
    except DraftError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    snapshot_room(room_id)
    return envelope(result)


@router.post("/rooms/{room_id}/draft/offer")
async def draft_offer(room_id: str, payload: DraftSlot, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    """Three cards for a slot. Asking again returns the same three (no re-roll)."""
    club = draft_club(room_id, identity.id)
    try:
        async with draft_service.lock(room_id):
            result = draft_service.open_slot(room_id, club, payload.slot_id)
    except DraftError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    snapshot_room(room_id)
    return envelope(result)


@router.post("/rooms/{room_id}/draft/pick")
async def draft_pick(room_id: str, payload: DraftPick, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    club = draft_club(room_id, identity.id)
    finished = False
    try:
        async with draft_service.lock(room_id):
            result = draft_service.pick(room_id, club, payload.slot_id, payload.catalog_id)
            finished = draft_service.complete_due(room_id)  # last manager done: start at once
    except DraftError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if finished:
        await finish_draft(room_id)
        result = {**result, "completed": True}
    snapshot_room(room_id)
    await hub.broadcast(room_id, {"type": "draft.progress", "club_code": club})
    return envelope(result)


@router.post("/rooms/{room_id}/draft/complete")
async def draft_force_complete(room_id: str, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    """Host: finish now; every missing pick is made automatically."""
    if room_manager._room(room_id).host_user_id != identity.id:
        raise HTTPException(status_code=403, detail="Apenas o anfitrião pode encerrar o Draft.")
    draft_club(room_id, identity.id)
    async with draft_service.lock(room_id):
        finished = draft_service.complete_due(room_id, force=True)
    if finished:
        await finish_draft(room_id)
    snapshot_room(room_id)
    return envelope({"completed": True})


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
            catalog_player = market.catalog.get(str(row["id"])) if room_id in season_service._seasons else None
            if catalog_player is not None:
                row["provenance"] = provenance(catalog_player)
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


@router.put("/rooms/{room_id}/squad/instructions")
async def save_instructions(room_id: str, payload: InstructionsUpdate, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    """Individual instructions of the starters for the next match."""
    club = market_club(room_id, identity.id)
    if room_manager._room(room_id).phase not in {"SQUAD_MANAGEMENT", "SEASON_PREPARATION"}:
        raise HTTPException(status_code=409, detail="Instruções só podem ser alteradas durante a preparação.")
    if room_id in season_service._seasons and season_service._season(room_id).live_round:
        raise HTTPException(status_code=409, detail="Durante o jogo, use os comandos ao vivo.")
    try:
        result = squad_service.save_instructions(room_id, club, payload.instructions)
    except MarketError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    unready = season_service.unready(room_id, club)
    snapshot_room(room_id)
    await hub.broadcast(room_id, {"type": "squad.strategy_changed", "club_code": club})
    return envelope({**result, "ready_cancelled": unready})


@router.get("/rooms/{room_id}/squad/cohesion")
async def squad_cohesion(room_id: str, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    """Entrosamento tático of the saved plan: compatibility, familiarity, engine factor."""
    club = market_club(room_id, identity.id)
    if room_id not in season_service._seasons:
        raise HTTPException(status_code=409, detail="O entrosamento é calculado a partir do início da temporada.")
    return envelope(season_service.cohesion_view(room_id, market_service._session(room_id).market, club))


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
# Frames reach the client in batches it buffers (it renders ~1 s behind the server
# clock), so pushing more often than this only costs CPU.
FRAME_PUSH_SECONDS = 0.25
# Side-panel detail (statistics, stamina, ratings) over the socket: slow-changing.
LIVE_STATS_SECONDS = 8.0


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
                        await open_window_for_bots(room_id)
                    snapshot_room(room_id)
            now = season_service.clock()
            if not completed and now - last_push >= FRAME_PUSH_SECONDS:
                # Engines were advanced above; read each coach's new frames (visual,
                # disposable) and match state (reliable, sequenced) - no HTTP needed.
                last_push = now
                with metrics.cpu("frame_push"):
                    await hub.push_frames(room_id, lambda club, since, known: season_service.live_frames(room_id, club, since, known_timeline=known))
                with metrics.cpu("live_state_push"):
                    await hub.push_live_state(room_id, lambda club, known, beat: season_service.live_state(room_id, club, known, beat),
                                              lambda club: season_service.live_stats(room_id, club), stats_every=LIVE_STATS_SECONDS)
            if completed:
                # Live state travels in `live.state`; only the end of the round needs a full refresh.
                await hub.broadcast(room_id, {"type": "season.round_completed"})
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


def room_managers(room_id: str) -> dict[str, dict[str, str]]:
    """Human coaches by club right now (history keeps the coach of each title)."""
    room = room_manager._room(room_id)
    return {str(p.selected_club_code): {"user_id": p.user_id, "name": p.display_name}
            for p in room.participants.values() if p.selected_club_code and p.role != "BOT"}


@router.get("/rooms/{room_id}/career/stats")
async def career_stats(room_id: str, competition: str | None = None, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    """Season statistics from committed matches, plus the history of past seasons."""
    market_club(room_id, identity.id)
    season = season_service._season(room_id)
    if competition not in (None, "LEAGUE", "CUP", "PLAYOFF"):
        raise HTTPException(status_code=422, detail="Competição inválida.")
    rows = list(career_service.player_stats(season, competition).values())
    results = career_service.compact_results(season)
    catalog = market_service._session(room_id).market.catalog
    history = season.season_history
    all_results = [row for summary in history for row in summary.get("results", [])] + results
    managers = room_managers(room_id)
    humans = sorted(managers)
    coaches = []
    for club in humans:
        own = [r for r in results if club in (r["home"], r["away"])]
        wins = sum(1 for r in own if (r["home"] == club and r["home_goals"] > r["away_goals"]) or (r["away"] == club and r["away_goals"] > r["home_goals"]))
        draws = sum(1 for r in own if r["home_goals"] == r["away_goals"])
        coaches.append({"club_code": club, "coach": managers[club]["name"], "played": len(own), "wins": wins, "draws": draws,
                        "losses": len(own) - wins - draws})
    rivals = [{"clubs": [a, b], **career_service.head_to_head(all_results, a, b)} for i, a in enumerate(humans) for b in humans[i + 1:]]
    return envelope({
        "season_number": season.season_number, "competition": competition,
        "scorers": sorted(rows, key=lambda r: (-int(r["goals"]), int(r["apps"]), str(r["player_id"])))[:20],
        "assists": sorted(rows, key=lambda r: (-int(r["assists"]), int(r["apps"]), str(r["player_id"])))[:20],
        "ratings": sorted((r for r in rows if int(r["apps"]) >= 3 and r["rating"] is not None), key=lambda r: (-float(r["rating"]), str(r["player_id"])))[:20],
        "goalkeepers": sorted((r for r in rows if r["position"] == "GK" and int(r["apps"]) >= 3), key=lambda r: (-int(r["clean_sheets"]), -int(r["saves"])))[:10],
        "team_of_season": career_service.team_of_season(rows, 3),
        "records": career_service.records(all_results),
        "coaches": coaches, "rivals": rivals,
        "development": [{**r, "name": catalog.get(str(r["player_id"])).name if catalog.get(str(r["player_id"])) else r["player_id"]}
                        for r in season.development_records][-200:],
        "history": [{key: summary.get(key) for key in ("season_number", "champion", "runner_up", "cup_champion", "league_leader", "best_player", "best_goalkeeper")}
                    for summary in history],
    })


@router.get("/rooms/{room_id}/career/trophies")
async def career_trophies(room_id: str, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    market_club(room_id, identity.id)
    season = season_service._season(room_id)
    current = []
    champion = season.playoffs.champion if season.playoffs else None
    if champion or season.knockout.cup_champion:
        current = [{"season_number": season.season_number, "champion": champion, "runner_up": season.knockout.playoff_runner_up,
                    "cup_champion": season.knockout.cup_champion, "cup_runner_up": season.knockout.cup_runner_up,
                    "managers": room_managers(room_id)}]
    return envelope({"trophies": career_service.trophies([*season.season_history, *current])})


@router.get("/rooms/{room_id}/career/news")
async def career_news(room_id: str, club: str | None = None, kind: str | None = None, season_number: int | None = None,
                      identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    """News from real events of the career (templates, no invented facts)."""
    market_club(room_id, identity.id)
    season = season_service._season(room_id)
    market = market_service._session(room_id).market
    names = {pid: player.name for pid, player in market.catalog.items()}
    transfers = [o for o in transfer_service.export_room(room_id)["offers"]]
    items = career_service.news(season, season.season_history, tuple(sorted(market.teams)), room_managers(room_id), transfers, names)
    if club:
        items = [item for item in items if club.upper() in item["clubs"]]
    if kind:
        items = [item for item in items if item["kind"] == kind.upper()]
    if season_number is not None:
        items = [item for item in items if item["season_number"] == season_number]
    return envelope({"items": items[:150]})


@router.post("/rooms/{room_id}/coach/change")
async def change_coach_club(room_id: str, payload: BotChange, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    """Optional coach market: between seasons a coach may take over a club without a
    human coach. Squad and money stay with the clubs; the old club gets a bot coach."""
    room = room_manager._room(room_id)
    if not room.coach_moves_enabled:
        raise HTTPException(status_code=409, detail="Esta liga não permite troca de clube entre temporadas.")
    season = season_service._season(room_id)
    if not season.preseason_window or not season.transfer_window_open or season.live_round or season_service.current_round(room_id) != 1:
        raise HTTPException(status_code=409, detail="A troca de clube só é permitida entre temporadas, antes da primeira rodada.")
    target = (payload.club_code or "").upper()
    market = market_service._session(room_id).market
    if target not in market.teams:
        raise HTTPException(status_code=422, detail="Clube inexistente nesta liga.")
    state = await room_manager.change_club_between_seasons(room_id, identity.id, target)
    snapshot_room(room_id)
    await hub.broadcast(room_id, {"type": "room.updated", "revision": state["revision"]})
    return envelope(state, int(state["revision"]))


async def open_window_for_bots(room_id: str) -> None:
    """Bots take the initiative as soon as a window opens (proposals, disputes)."""
    room = room_manager._room(room_id)
    humans = {p.selected_club_code for p in room.participants.values() if p.selected_club_code and p.role != "BOT"}
    try:
        offers = await transfer_service.bot_window_activity(room_id, humans)
    except MarketError:
        return
    if offers:
        await hub.broadcast(room_id, {"type": "transfer.offer_changed"})


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
            if not season.live_round and season_service.required_ready(room_id, humans).issubset(season.ready_clubs):
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


@router.get("/match-engines")
async def match_engines() -> dict[str, object]:
    """Engines and their TESTED capability matrix (PES 2013 Web: experimental / unavailable)."""
    return envelope({"engines": match_payload_service.engines()})


@router.get("/rooms/{room_id}/season/matches/{match_id}/payload")
async def match_payload(room_id: str, match_id: str, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    """Engine-neutral MatchPayload v1 of an official match that has started (room members only)."""
    market_club(room_id, identity.id)
    try:
        async with round_locks.setdefault(room_id, asyncio.Lock()):
            payload = match_payload_service.payload_for(room_id, match_id)
    except MarketError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return envelope(payload.model_dump(mode="json"))


@router.post("/rooms/{room_id}/season/matches/{match_id}/prepare/{engine}")
async def match_prepare(room_id: str, match_id: str, engine: str, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    """Ask an engine adapter to prepare a live match. Unsupported / unvalidated engines refuse."""
    market_club(room_id, identity.id)
    try:
        async with round_locks.setdefault(room_id, asyncio.Lock()):
            prepared = match_payload_service.prepare(room_id, match_id, engine)
    except EngineCapabilityError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except MarketError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return envelope({"engine": prepared.engine, "match_id": prepared.match_id, "payload_checksum": prepared.payload_checksum})


@router.get("/rooms/{room_id}/season/interactive")
async def interactive_state(room_id: str, revision: int | None = None, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    """Modo Jogável: authoritative state of the coach's decisive-moments match.

    Polling also marks the coach as connected (reconnection = polling again: the
    server restores the frozen decision; see HighlightMatch.advance). With the
    revision the client already has, an unchanged match answers in a few bytes."""
    club = market_club(room_id, identity.id)
    try:
        async with round_locks.setdefault(room_id, asyncio.Lock()):
            return envelope(season_service.interactive_view(room_id, club, revision))
    except MarketError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/rooms/{room_id}/season/interactive/actions")
async def interactive_action(room_id: str, payload: InteractiveAction, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    """One gesture (pass, lofted ball, carry or shot). Validated and resolved by the server;
    duplicates (same action_id) are answered without being applied again."""
    club = market_club(room_id, identity.id)
    try:
        async with round_locks.setdefault(room_id, asyncio.Lock()):
            result = season_service.interactive_action(room_id, club, payload.model_dump())
            if result["status"] == "ACCEPTED":
                snapshot_room(room_id)
    except MarketError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    await hub.broadcast(room_id, {"type": "season.interactive", "revision": result["revision"]})
    return envelope(result)


def _lab_catalog():
    settings = get_settings()
    return create_demo_catalog() if settings.enable_demo_catalog else load_catalog(settings.player_catalog_path)


@router.post("/lab/sessions")
async def lab_create(payload: LabCreate, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    """Gameplay Lab: a reproducible scenario on the real engine, outside any league or career."""
    catalog = _lab_catalog()
    if not catalog:
        raise HTTPException(status_code=503, detail="Catálogo indisponível.")
    try:
        return envelope(lab_service.create(identity.id, catalog, payload.mode, payload.kind, payload.home, payload.away, payload.seed,
                                           second_half=payload.second_half, engine=payload.engine, difficulty=payload.difficulty))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/lab/sessions/{session_id}")
async def lab_state(session_id: str, revision: int | None = None, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    try:
        return envelope(lab_service.view(identity.id, session_id, revision))
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error.args[0])) from error


@router.post("/lab/sessions/{session_id}/actions")
async def lab_action(session_id: str, payload: InteractiveAction, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    try:
        return envelope(lab_service.act(identity.id, session_id, payload.model_dump()))
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error.args[0])) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/rooms/{room_id}/season/preview")
async def season_preview(room_id: str, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    """Next fixture comparison: both projected lineups, sectors and readiness."""
    club = market_club(room_id, identity.id)
    try:
        room = room_manager._room(room_id)
        season_service._season(room_id).human_clubs = {p.selected_club_code for p in room.participants.values() if p.selected_club_code and p.role != "BOT"}
        preview = season_service.preview(room_id, market_service._session(room_id).market, club)
        preview["next_round_starts_at"] = season_service.preparation_deadline(room_id, room.round_preparation_duration_seconds,
                                                                             season_service._season(room_id).human_clubs)
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


@router.get("/custom-players/rules")
async def custom_player_rules() -> dict[str, object]:
    """Limits and the overall formula for created players (the UI previews the same numbers)."""
    return envelope({"attribute_min": ATTRIBUTE_MIN, "attribute_max": ATTRIBUTE_MAX, "max_overall": MAX_OVERALL, "max_per_club": MAX_PER_CLUB,
                     "outfield_keys": list(OUTFIELD_KEYS), "keeper_keys": list(KEEPER_KEYS), "weights": WEIGHTS})


@router.post("/rooms/{room_id}/club/custom-players")
async def create_custom_player(room_id: str, payload: CustomPlayerCreate, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    """A coach creates an athlete for his club, in place of one of the same position."""
    club = market_club(room_id, identity.id)
    try:
        spec = CustomPlayerSpec(name=payload.name, position=payload.position, attributes=payload.attributes, shirt_number=payload.shirt_number)
    except ValidationError as error:
        raise HTTPException(status_code=422, detail=str(error.errors()[0].get("msg", "")).removeprefix("Value error, ")) from error
    try:
        result = await transfer_service.create_custom_player(room_id, club, spec, payload.replace_player_id, payload.operation_id)
    except MarketError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    snapshot_room(room_id)
    await hub.broadcast(room_id, {"type": "transfer.completed", "club_code": club})
    return envelope(result)


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
    # Only people answer offers; bot clubs (participants with role BOT) decide at once.
    human_clubs = {member.selected_club_code for member in room.participants.values() if member.selected_club_code and member.role != "BOT"}
    try:
        offer = await transfer_service.create_offer(room_id, club, payload.incoming_player_id, payload.offered_player_id, payload.amount_cents,
                                                    payload.idempotency_key, set(human_clubs), payload.kind)
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
        season = season_service._season(room_id)
        if not season.playoffs or not season.playoffs.champion or not season.progression_applied:
            raise MarketError("A temporada atual precisa terminar antes de começar outra.")
        returned = await transfer_service.end_loans(room_id)  # loans last one season
        result = season_service.create_next_season(room_id, market_service._session(room_id).market, room_managers(room_id))
    except MarketError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    room = room_manager._room(room_id)
    await room_manager.set_phase(room_id, room.host_user_id, "TRANSFER_WINDOW")
    await open_window_for_bots(room_id)
    result = {**result, "returned_loans": returned}
    snapshot_room(room_id)
    await hub.broadcast(room_id, {"type": "season.next_started", "season_number": result["season_number"]})
    return envelope(result)


@router.get("/rooms/{room_id}/season")
async def season_state(room_id: str, identity: GuestIdentity = Depends(current_identity)) -> dict[str, object]:
    market_club(room_id, identity.id)
    await start_round_if_preparation_expired(room_id)
    try:
        view = season_service.view(room_id)
        room = room_manager._room(room_id)
        humans = {p.selected_club_code for p in room.participants.values() if p.selected_club_code and p.role != "BOT"}
        # When the next round starts by itself (also for coaches who do not play it).
        view["next_round_starts_at"] = season_service.preparation_deadline(room_id, room.round_preparation_duration_seconds, humans)
        return envelope(view)
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
    channel = await hub.connect(room_id, websocket, member.selected_club_code if member else None)
    try:
        # Every write goes through the channel's single writer (no concurrent sends).
        if room_id in season_service._seasons and member and member.selected_club_code:
            club = member.selected_club_code
            channel.send_reliable({"type": "season.sync", "data": season_service.live_view(room_id, club)})
        while True:
            message = await websocket.receive_text()
            if message == "ping":
                channel.send_reliable("pong")
                continue
            if len(message.encode("utf-8")) > 4096:
                await websocket.close(code=status.WS_1009_MESSAGE_TOO_BIG)
                break
            if message.startswith("{"):
                try:
                    payload = json.loads(message)
                except ValueError:
                    continue
                if isinstance(payload, dict) and payload.get("type") == "client.stats":
                    # Anonymous rendering health (fps, canvas time, delay): aggregated only.
                    metrics.record_client(room_id, payload)
    except (WebSocketDisconnect, RuntimeError, OSError):
        pass
    finally:
        await hub.disconnect(room_id, websocket)
