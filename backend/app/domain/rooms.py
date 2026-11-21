from __future__ import annotations

import asyncio
import copy
import secrets
from dataclasses import asdict, dataclass, field

from fastapi import HTTPException, status

from app.domain.clubs import CLUBS

MATCH_DURATIONS = (60, 90, 120, 180)
TEAM_COUNTS = (4, 6, 8, 10, 12, 16, 20)
# Starting budgets in cents (R$ 50 mi … R$ 1 bi).
BUDGETS = (5_000_000_000, 10_000_000_000, 15_000_000_000, 20_000_000_000,
           30_000_000_000, 40_000_000_000, 50_000_000_000, 100_000_000_000)
DRAFT_MIN_OVERALLS = (0, 65, 70, 72, 75, 78, 80)

# League rules chosen by the host before the season (frozen afterwards).
# name -> (allowed values, default). Older snapshots without a rule get the default.
RULES: dict[str, tuple[tuple[object, ...], object]] = {
    "game_mode": (("TRADITIONAL", "DRAFT", "DRAFT_KNOCKOUT", "SURVIVOR", "PACK"), "TRADITIONAL"),
    "sim_style": (("REALISTIC", "EXCITING"), "REALISTIC"),
    "bot_difficulty": (("CASUAL", "COMPETITIVE", "LEGENDARY"), "COMPETITIVE"),
    "morale_enabled": ((True, False), False),
    "copa_enabled": ((True, False), False),
    "playoff_format": (("SINGLE", "TWO_LEGS"), "SINGLE"),
    "coach_moves_enabled": ((True, False), False),
    "draft_catalog": (("BRASILEIRAO", "WORLD"), "BRASILEIRAO"),
    "draft_min_overall": (DRAFT_MIN_OVERALLS, 0),
    # Último Sobrevivente: clubs eliminated per round (0 = automatic, about a quarter).
    "survivor_eliminations": ((0, 2, 4), 0),
    # Pack & Play: equal quality per collection, or every card drawn independently.
    "pack_luck": (("BALANCED", "LUCK"), "BALANCED"),
    # Modo Jogável (decisive moments) or the technical simulation, for every game mode.
    "execution_mode": (("TECHNICAL", "INTERACTIVE"), "TECHNICAL"),
    # Arcade (no cards/offside, fewer stoppages) or traditional (fouls, free kicks, penalties).
    "ruleset": (("ARCADE", "TRADITIONAL"), "ARCADE"),
    # Server-controlled decision time per action, and optional free time against bots.
    "decision_seconds": ((5, 10, 15, 20), 10),
    "decision_free_vs_bots": ((True, False), False),
}

# Clubs a mode can start with (the knockout bracket and the survival path need these).
MODE_TEAM_COUNTS = {"DRAFT_KNOCKOUT": (4, 8, 16), "PACK": (4, 8, 16), "SURVIVOR": (8, 12, 16, 20)}
# The phase a started room enters, per game mode.
START_PHASE = {"TRADITIONAL": "INITIAL_MARKET", "DRAFT": "DRAFT", "DRAFT_KNOCKOUT": "DRAFT", "PACK": "PACK", "SURVIVOR": "SQUAD_MANAGEMENT"}


def mode_error(game_mode: str, team_count: int, market_mode: str) -> str | None:
    """Combinations a mode cannot run with (checked on create, update and start)."""
    allowed = MODE_TEAM_COUNTS.get(game_mode)
    if allowed and team_count not in allowed:
        sizes = ", ".join(str(n) for n in allowed)
        return f"Este modo começa com {sizes} clubes."
    if game_mode != "TRADITIONAL" and market_mode == "COINS":
        return "Este modo não usa o mercado inicial: escolha valores reais."
    return None


def rules_error(values: dict[str, object]) -> str | None:
    for name, value in values.items():
        if name in RULES and value not in RULES[name][0]:
            return f"Valor inválido para a regra {name}."
    return None


@dataclass
class Participant:
    user_id: str
    display_name: str
    role: str
    selected_club_code: str | None = None


@dataclass
class RoomState:
    id: str
    code: str
    name: str
    mode: str
    initial_budget_cents: int
    max_human_participants: int
    privacy: str
    host_user_id: str
    team_count: int = 20
    double_round_robin: bool = True
    market_mode: str = "TRADITIONAL"
    initial_market_duration_seconds: int = 300
    round_preparation_duration_seconds: int = 300
    withdrawal_penalty_percent: int = 5
    # Real duration of every live match (90 game minutes condensed): 60, 90, 120 or 180 s.
    match_duration_seconds: int = 60
    game_mode: str = "TRADITIONAL"
    sim_style: str = "REALISTIC"
    bot_difficulty: str = "COMPETITIVE"
    morale_enabled: bool = False
    copa_enabled: bool = False
    playoff_format: str = "SINGLE"
    coach_moves_enabled: bool = False
    draft_catalog: str = "BRASILEIRAO"
    draft_min_overall: int = 0
    survivor_eliminations: int = 0
    pack_luck: str = "BALANCED"
    execution_mode: str = "TECHNICAL"
    ruleset: str = "ARCADE"
    decision_seconds: int = 10
    decision_free_vs_bots: bool = False
    phase: str = "WAITING"
    market_ends_at: float | None = None
    revision: int = 0
    participants: dict[str, Participant] = field(default_factory=dict)


class RoomManager:
    """Single-process room authority. A restart loses data unless snapshots are added later."""

    def __init__(self) -> None:
        self._rooms: dict[str, RoomState] = {}
        self._create_lock = asyncio.Lock()
        self._locks: dict[str, asyncio.Lock] = {}

    @staticmethod
    def _id() -> str:
        return secrets.token_urlsafe(10)

    def _new_code(self) -> str:
        used = {room.code for room in self._rooms.values()}
        while True:
            code = secrets.token_hex(3).upper()
            if code not in used:
                return code

    def _room(self, room_id: str) -> RoomState:
        room = self._rooms.get(room_id)
        if not room:
            raise HTTPException(status_code=404, detail="Sala não encontrada.")
        return room

    @staticmethod
    def _view(room: RoomState) -> dict[str, object]:
        return {
            "id": room.id,
            "code": room.code,
            "name": room.name,
            "mode": room.mode,
            "initial_budget_cents": room.initial_budget_cents,
            "max_human_participants": room.max_human_participants,
            "team_count": room.team_count,
            "double_round_robin": room.double_round_robin,
            "market_mode": room.market_mode,
            "coin_starting_balance": 100 if room.market_mode == "COINS" else None,
            "privacy": room.privacy,
            "initial_market_duration_seconds": room.initial_market_duration_seconds,
            "round_preparation_duration_seconds": room.round_preparation_duration_seconds,
            "withdrawal_penalty_percent": room.withdrawal_penalty_percent,
            "match_duration_seconds": room.match_duration_seconds,
            **{name: getattr(room, name) for name in RULES},
            "phase": room.phase,
            "market_ends_at": room.market_ends_at,
            "revision": room.revision,
            "participant_count": sum(member.role != "BOT" for member in room.participants.values()),
            "bot_count": sum(member.role == "BOT" for member in room.participants.values()),
            "selected_club_count": sum(bool(member.selected_club_code) for member in room.participants.values()),
            "available_slots": room.team_count - sum(bool(member.selected_club_code) for member in room.participants.values()),
        }

    @staticmethod
    def _state(room: RoomState) -> dict[str, object]:
        return {
            **RoomManager._view(room),
            "participants": [asdict(member) for member in room.participants.values()],
        }

    def restore(self, payload: dict[str, object]) -> None:
        """Restore a previously validated room snapshot and recreate process-local locks."""
        members = payload.get("participants")
        if not isinstance(members, list):
            raise ValueError("Snapshot de sala sem participantes válidos.")
        participants = {
            str(item["user_id"]): Participant(str(item["user_id"]), str(item["display_name"]), str(item["role"]), item.get("selected_club_code"))
            for item in members if isinstance(item, dict) and {"user_id", "display_name", "role"}.issubset(item)
        }
        if len(participants) != len(members):
            raise ValueError("Snapshot de sala contém participante inválido ou duplicado.")
        room = RoomState(
            id=str(payload["id"]), code=str(payload["code"]), name=str(payload["name"]),
            mode=str(payload["mode"]), initial_budget_cents=int(payload["initial_budget_cents"]),
            max_human_participants=int(payload["max_human_participants"]), privacy=str(payload["privacy"]),
            team_count=int(payload.get("team_count", 20)), double_round_robin=bool(payload.get("double_round_robin", True)),
            market_mode=str(payload.get("market_mode", "TRADITIONAL")),
            host_user_id=str(payload.get("host_user_id") or next((member.user_id for member in participants.values() if member.role == "HOST"), "")),
            initial_market_duration_seconds=int(payload.get("initial_market_duration_seconds", 300)),
            round_preparation_duration_seconds=int(payload.get("round_preparation_duration_seconds", 86_400)),
            withdrawal_penalty_percent=int(payload.get("withdrawal_penalty_percent", 5)),
            match_duration_seconds=int(payload.get("match_duration_seconds", 90)),
            **{name: payload.get(name, default) for name, (_, default) in RULES.items()},
            phase=str(payload.get("phase", "WAITING")), market_ends_at=payload.get("market_ends_at"),
            revision=int(payload.get("revision", 0)), participants=participants,
        )
        selected_clubs = [member.selected_club_code for member in participants.values() if member.selected_club_code]
        known_clubs = {club.code for club in CLUBS}
        if room.mode not in {"FIVE_A_SIDE", "ELEVEN_A_SIDE"} or room.market_mode not in {"TRADITIONAL", "COINS"} or room.team_count not in TEAM_COUNTS or room.max_human_participants > room.team_count or room.withdrawal_penalty_percent not in {0, 2, 5, 10} or room.match_duration_seconds not in MATCH_DURATIONS or rules_error({name: getattr(room, name) for name in RULES}) or room.host_user_id not in participants or len(selected_clubs) != len(set(selected_clubs)) or len(selected_clubs) > room.team_count or not set(selected_clubs).issubset(known_clubs):
            raise ValueError("Snapshot de sala viola invariantes de identidade ou modo.")
        self._rooms[room.id] = room
        self._locks[room.id] = asyncio.Lock()

    async def create(
        self,
        *,
        user_id: str,
        display_name: str,
        name: str,
        mode: str,
        initial_budget_cents: int,
        max_human_participants: int,
        team_count: int = 20,
        double_round_robin: bool = True,
        market_mode: str = "TRADITIONAL",
        privacy: str,
        initial_market_duration_seconds: int = 300,
        round_preparation_duration_seconds: int = 300,
        withdrawal_penalty_percent: int = 5,
        match_duration_seconds: int = 60,
        **rules: object,
    ) -> dict[str, object]:
        if team_count not in TEAM_COUNTS or max_human_participants > team_count:
            raise HTTPException(status_code=422, detail="Escolha uma quantidade válida de clubes e técnicos.")
        if market_mode not in {"TRADITIONAL", "COINS"}:
            raise HTTPException(status_code=422, detail="Modo de mercado inválido.")
        if withdrawal_penalty_percent not in {0, 2, 5, 10}:
            raise HTTPException(status_code=422, detail="A multa deve ser 0%, 2%, 5% ou 10%.")
        if match_duration_seconds not in MATCH_DURATIONS:
            raise HTTPException(status_code=422, detail="Duração da partida deve ser 1:00, 1:30, 2:00 ou 3:00.")
        unknown = set(rules) - set(RULES)
        error = rules_error(rules) or (f"Regra desconhecida: {sorted(unknown)[0]}." if unknown else None)
        if error:
            raise HTTPException(status_code=422, detail=error)
        error = mode_error(str(rules.get("game_mode", "TRADITIONAL")), team_count, market_mode)
        if error:
            raise HTTPException(status_code=422, detail=error)
        async with self._create_lock:
            room = RoomState(
                id=self._id(),
                code=self._new_code(),
                name=name,
                mode=mode,
                initial_budget_cents=initial_budget_cents,
                max_human_participants=max_human_participants,
                team_count=team_count,
                double_round_robin=double_round_robin,
                market_mode=market_mode,
                privacy=privacy,
                initial_market_duration_seconds=initial_market_duration_seconds,
                round_preparation_duration_seconds=round_preparation_duration_seconds,
                withdrawal_penalty_percent=withdrawal_penalty_percent,
                match_duration_seconds=match_duration_seconds,
                **rules,
                host_user_id=user_id,
                participants={user_id: Participant(user_id, display_name, "HOST")},
            )
            self._rooms[room.id] = room
            self._locks[room.id] = asyncio.Lock()
            return self._state(room)

    def list(self) -> list[dict[str, object]]:
        return [self._view(room) for room in self._rooms.values() if room.privacy == "PUBLIC" and room.phase == "WAITING"]

    def list_for(self, user_id: str) -> list[dict[str, object]]:
        return [self._state(room) for room in self._rooms.values() if user_id in room.participants]

    async def join(self, room_id: str, user_id: str, display_name: str) -> dict[str, object]:
        self._room(room_id)
        async with self._locks[room_id]:
            room = self._room(room_id)
            draft = copy.deepcopy(room)
            if user_id in draft.participants:
                return self._state(draft)
            if draft.phase != "WAITING":
                raise HTTPException(status_code=409, detail="A liga já começou. Somente os técnicos que já participam podem retornar.")
            # Bots occupy clubs, not human seats: only people count toward the human limit.
            if sum(member.role != "BOT" for member in draft.participants.values()) >= draft.max_human_participants:
                raise HTTPException(
                    status_code=409, detail="Limite de participantes humanos atingido."
                )
            if len(draft.participants) >= draft.team_count:
                raise HTTPException(
                    status_code=409, detail="Todas as vagas de clube estão ocupadas. O anfitrião pode remover um bot para abrir espaço."
                )
            draft.participants[user_id] = Participant(user_id, display_name, "MEMBER")
            draft.revision += 1
            self._rooms[room_id] = draft
            return self._state(draft)

    async def join_by_code(self, code: str, user_id: str, display_name: str) -> dict[str, object]:
        room = next((item for item in self._rooms.values() if item.code == code.upper()), None)
        if not room:
            raise HTTPException(status_code=404, detail="Código de sala não encontrado.")
        return await self.join(room.id, user_id, display_name)

    async def select_club(self, room_id: str, user_id: str, club_code: str) -> dict[str, object]:
        self._room(room_id)
        club_codes = {club.code for club in CLUBS}
        if club_code not in club_codes:
            raise HTTPException(status_code=404, detail="Clube não encontrado.")
        async with self._locks[room_id]:
            room = self._room(room_id)
            draft = copy.deepcopy(room)
            participant = draft.participants.get(user_id)
            if not participant:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, detail="Você não participa desta sala."
                )
            if draft.phase != "WAITING":
                if participant.selected_club_code == club_code:
                    return self._state(draft)
                raise HTTPException(status_code=409, detail="Não é possível trocar de clube depois do início da liga.")
            claimed = {member.selected_club_code for member in draft.participants.values()}
            if club_code in claimed and participant.selected_club_code != club_code:
                raise HTTPException(
                    status_code=409, detail="Este clube já foi escolhido por outro participante."
                )
            participant.selected_club_code = club_code
            if sum(bool(member.selected_club_code) for member in draft.participants.values()) > draft.team_count:
                raise HTTPException(status_code=409, detail="A sala já atingiu a quantidade configurada de clubes.")
            draft.revision += 1
            self._rooms[room_id] = draft
            return self._state(draft)

    async def update(
        self, room_id: str, user_id: str, **changes: object
    ) -> dict[str, object]:
        self._room(room_id)
        async with self._locks[room_id]:
            room = self._room(room_id)
            if room.host_user_id != user_id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Apenas o anfitrião pode editar a liga.")
            if room.phase != "WAITING":
                raise HTTPException(status_code=409, detail="A temporada já começou e não pode mais ser alterada.")
            if changes.get("match_duration_seconds", room.match_duration_seconds) not in MATCH_DURATIONS:
                raise HTTPException(status_code=422, detail="Duração da partida deve ser 1:00, 1:30, 2:00 ou 3:00.")
            if changes.get("withdrawal_penalty_percent", room.withdrawal_penalty_percent) not in {0, 2, 5, 10}:
                raise HTTPException(status_code=422, detail="A multa deve ser 0%, 2%, 5% ou 10%.")
            if int(changes["max_human_participants"]) < sum(member.role != "BOT" for member in room.participants.values()):
                raise HTTPException(status_code=409, detail="A liga já possui mais participantes que esse limite.")
            team_count = int(changes.get("team_count", room.team_count))
            if team_count not in TEAM_COUNTS or int(changes.get("max_human_participants", room.max_human_participants)) > team_count:
                raise HTTPException(status_code=422, detail="Quantidade de clubes ou técnicos inválida.")
            if sum(bool(member.selected_club_code) for member in room.participants.values()) > team_count:
                raise HTTPException(status_code=409, detail="Reduza bots ou clubes escolhidos antes de diminuir a liga.")
            if changes.get("market_mode", room.market_mode) not in {"TRADITIONAL", "COINS"}:
                raise HTTPException(status_code=422, detail="Modo de mercado inválido.")
            error = rules_error({name: changes[name] for name in RULES if name in changes})
            if error:
                raise HTTPException(status_code=422, detail=error)
            error = mode_error(str(changes.get("game_mode", room.game_mode)), int(changes.get("team_count", room.team_count)),
                               str(changes.get("market_mode", room.market_mode)))
            if error:
                raise HTTPException(status_code=422, detail=error)
            draft = copy.deepcopy(room)
            for field_name, value in changes.items():
                setattr(draft, field_name, value)
            draft.revision += 1
            self._rooms[room_id] = draft
            return self._state(draft)

    async def set_match_duration(self, room_id: str, user_id: str, seconds: int, live_round: bool) -> dict[str, object]:
        """Host-only, any phase: the new duration applies from the next round to kick off."""
        self._room(room_id)
        async with self._locks[room_id]:
            room = self._room(room_id)
            if room.host_user_id != user_id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Apenas o anfitrião pode alterar a duração das partidas.")
            if seconds not in MATCH_DURATIONS:
                raise HTTPException(status_code=422, detail="Duração da partida deve ser 1:00, 1:30, 2:00 ou 3:00.")
            if live_round:
                raise HTTPException(status_code=409, detail="Há uma rodada em andamento: a duração só pode mudar depois do apito final.")
            if room.match_duration_seconds == seconds:
                return self._state(room)
            draft = copy.deepcopy(room)
            draft.match_duration_seconds = seconds
            draft.revision += 1
            self._rooms[room_id] = draft
            return self._state(draft)

    async def start(self, room_id: str, user_id: str) -> dict[str, object]:
        self._room(room_id)
        async with self._locks[room_id]:
            room = self._room(room_id)
            if room.host_user_id != user_id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Apenas o anfitrião pode iniciar a temporada.")
            if room.phase != "WAITING":
                raise HTTPException(status_code=409, detail="A temporada já foi iniciada.")
            host = room.participants.get(user_id)
            if not host or not host.selected_club_code:
                raise HTTPException(status_code=409, detail="Escolha um clube antes de iniciar a temporada.")
            if any(not member.selected_club_code for member in room.participants.values()):
                raise HTTPException(status_code=409, detail="Todos os técnicos precisam escolher um clube antes de iniciar.")
            # Legacy 20-club rooms have always filled unspecified clubs with
            # system bots. Smaller custom leagues require the host to make the
            # composition explicit before the market starts.
            if room.team_count != 20 and len(room.participants) != room.team_count:
                raise HTTPException(status_code=409, detail="Complete as vagas com bots até atingir a quantidade configurada de clubes.")
            draft = copy.deepcopy(room)
            draft.phase = START_PHASE.get(room.game_mode, "INITIAL_MARKET")
            draft.revision += 1
            self._rooms[room_id] = draft
            return self._state(draft)

    async def add_bot(self, room_id: str, user_id: str, club_code: str | None = None) -> dict[str, object]:
        self._room(room_id)
        async with self._locks[room_id]:
            room = self._room(room_id)
            if room.host_user_id != user_id or room.phase != "WAITING":
                raise HTTPException(status_code=409, detail="Bots só podem ser alterados pelo anfitrião antes do início.")
            if len(room.participants) >= room.team_count:
                raise HTTPException(status_code=409, detail="A sala já está completa.")
            claimed = {member.selected_club_code for member in room.participants.values() if member.selected_club_code}
            available = [club.code for club in CLUBS if club.code not in claimed]
            selected = club_code or (available[0] if available else None)
            if selected not in available:
                raise HTTPException(status_code=409, detail="Clube indisponível para bot.")
            draft = copy.deepcopy(room)
            bot_id = f"bot:{len([p for p in draft.participants.values() if p.role == 'BOT']) + 1}:{selected}"
            draft.participants[bot_id] = Participant(bot_id, f"Bot {selected}", "BOT", selected)
            draft.revision += 1
            self._rooms[room_id] = draft
            return self._state(draft)

    async def complete_with_bots(self, room_id: str, user_id: str) -> dict[str, object]:
        """Fill a custom league's remaining club slots with deterministic system bots.

        The 20-club legacy lobby still represents unclaimed teams implicitly. Smaller
        leagues need explicit teams because their fixture list is defined by exactly
        the selected clubs.
        """
        self._room(room_id)
        async with self._locks[room_id]:
            room = self._room(room_id)
            if room.host_user_id != user_id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Apenas o anfitrião pode completar a liga com bots.")
            if room.phase != "WAITING":
                raise HTTPException(status_code=409, detail="Bots só podem ser adicionados antes do início.")
            if room.team_count == 20:
                return self._state(room)
            draft = copy.deepcopy(room)
            claimed = {member.selected_club_code for member in draft.participants.values() if member.selected_club_code}
            available = [club.code for club in CLUBS if club.code not in claimed]
            while len(draft.participants) < draft.team_count:
                selected = available.pop(0) if available else None
                if selected is None:
                    raise HTTPException(status_code=409, detail="Não há clubes suficientes para completar a liga.")
                number = sum(member.role == "BOT" for member in draft.participants.values()) + 1
                bot_id = f"bot:{number}:{selected}"
                draft.participants[bot_id] = Participant(bot_id, f"Bot {selected}", "BOT", selected)
            if draft.participants != room.participants:
                draft.revision += 1
                self._rooms[room_id] = draft
            return self._state(draft)

    async def change_club_between_seasons(self, room_id: str, user_id: str, club_code: str) -> dict[str, object]:
        """Coach market (optional rule): a human takes over a club no human controls."""
        self._room(room_id)
        async with self._locks[room_id]:
            room = self._room(room_id)
            member = room.participants.get(user_id)
            if member is None or member.role == "BOT":
                raise HTTPException(status_code=403, detail="Somente técnicos da liga podem trocar de clube.")
            if member.selected_club_code == club_code:
                return self._state(room)
            holder = next((m for m in room.participants.values() if m.selected_club_code == club_code), None)
            if holder is not None and holder.role != "BOT":
                raise HTTPException(status_code=409, detail="Outro técnico já comanda este clube.")
            draft = copy.deepcopy(room)
            if holder is not None:
                del draft.participants[holder.user_id]  # the club's bot steps aside
            draft.participants[user_id].selected_club_code = club_code
            draft.revision += 1
            self._rooms[room_id] = draft
            return self._state(draft)

    async def remove_bot(self, room_id: str, user_id: str, club_code: str) -> dict[str, object]:
        self._room(room_id)
        async with self._locks[room_id]:
            room = self._room(room_id)
            if room.host_user_id != user_id or room.phase != "WAITING":
                raise HTTPException(status_code=409, detail="Bots só podem ser alterados pelo anfitrião antes do início.")
            bot_id = next((key for key, member in room.participants.items() if member.role == "BOT" and member.selected_club_code == club_code), None)
            if not bot_id:
                raise HTTPException(status_code=404, detail="Bot não encontrado para este clube.")
            draft = copy.deepcopy(room)
            del draft.participants[bot_id]
            draft.revision += 1
            self._rooms[room_id] = draft
            return self._state(draft)

    async def set_market_deadline(self, room_id: str, ends_at: float) -> dict[str, object]:
        async with self._locks[room_id]:
            room = self._room(room_id)
            draft = copy.deepcopy(room)
            draft.market_ends_at = ends_at
            draft.revision += 1
            self._rooms[room_id] = draft
            return self._state(draft)

    async def complete_market(self, room_id: str) -> dict[str, object]:
        async with self._locks[room_id]:
            room = self._room(room_id)
            if room.phase in {"MARKET_SELECTION", "MARKET_REASSIGNMENT", "MARKET_REVIEW", "SQUAD_MANAGEMENT"}:
                return self._state(room)
            if room.phase != "INITIAL_MARKET":
                raise HTTPException(status_code=409, detail="O mercado não está ativo nesta sala.")
            draft = copy.deepcopy(room)
            draft.phase = "MARKET_SELECTION"
            draft.market_ends_at = None
            draft.revision += 1
            self._rooms[room_id] = draft
            return self._state(draft)

    async def set_market_phase(self, room_id: str, phase: str) -> dict[str, object]:
        allowed = {
            "INITIAL_MARKET": {"MARKET_SELECTION"},
            "MARKET_SELECTION": {"MARKET_REASSIGNMENT", "MARKET_REVIEW"},
            "MARKET_REASSIGNMENT": {"MARKET_REVIEW"},
            "MARKET_REVIEW": {"SQUAD_MANAGEMENT"},
            "DRAFT": {"SQUAD_MANAGEMENT"},
            "PACK": {"SQUAD_MANAGEMENT"},
        }
        async with self._locks[room_id]:
            room = self._room(room_id)
            if room.phase == phase:
                return self._state(room)
            if phase not in allowed.get(room.phase, set()):
                raise HTTPException(status_code=409, detail="Transição inválida para a fase do mercado.")
            draft = copy.deepcopy(room)
            draft.phase = phase
            if phase != "INITIAL_MARKET":
                draft.market_ends_at = None
            draft.revision += 1
            self._rooms[room_id] = draft
            return self._state(draft)

    async def start_season(self, room_id: str, user_id: str) -> dict[str, object]:
        async with self._locks[room_id]:
            room = self._room(room_id)
            if room.host_user_id != user_id:
                raise HTTPException(status_code=403, detail="Apenas o anfitrião pode iniciar as rodadas.")
            if room.phase in ("SEASON_PREPARATION", "TRANSFER_WINDOW"):
                # Idempotent: a double click (or another tab) already opened the season.
                return self._state(room)
            if room.phase != "SQUAD_MANAGEMENT":
                raise HTTPException(status_code=409, detail="As rodadas só podem ser abertas depois da gestão de elenco.")
            draft = copy.deepcopy(room)
            draft.phase = "SEASON_PREPARATION"
            draft.revision += 1
            self._rooms[room_id] = draft
            return self._state(draft)

    async def set_phase(self, room_id: str, user_id: str, phase: str) -> dict[str, object]:
        async with self._locks[room_id]:
            room = self._room(room_id)
            if room.host_user_id != user_id:
                raise HTTPException(status_code=403, detail="Apenas o anfitrião pode avançar a fase da liga.")
            if phase not in {"SEASON_PREPARATION", "TRANSFER_WINDOW"}:
                raise HTTPException(status_code=409, detail="Fase de temporada inválida.")
            if room.phase not in {"SEASON_PREPARATION", "TRANSFER_WINDOW"}:
                raise HTTPException(status_code=409, detail="A liga não está na fase de temporada.")
            if room.phase == phase:
                return self._state(room)
            draft = copy.deepcopy(room)
            draft.phase = phase
            draft.revision += 1
            self._rooms[room_id] = draft
            return self._state(draft)

    async def rename_participant(self, user_id: str, display_name: str) -> list[dict[str, object]]:
        changed: list[dict[str, object]] = []
        for room_id, lock in list(self._locks.items()):
            async with lock:
                room = self._room(room_id)
                participant = room.participants.get(user_id)
                if not participant or participant.display_name == display_name:
                    continue
                draft = copy.deepcopy(room)
                draft.participants[user_id].display_name = display_name
                draft.revision += 1
                self._rooms[room_id] = draft
                changed.append(self._state(draft))
        return changed

    async def state_for(self, room_id: str, user_id: str) -> dict[str, object]:
        room = self._room(room_id)
        if user_id not in room.participants:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Você não participa desta sala."
            )
        return self._state(room)

    def member_of(self, room_id: str, user_id: str) -> bool:
        return user_id in self._room(room_id).participants


room_manager = RoomManager()
