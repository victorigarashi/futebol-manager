from __future__ import annotations

import asyncio
import copy
import secrets
from dataclasses import asdict, dataclass, field

from fastapi import HTTPException, status

from app.domain.clubs import CLUBS

MATCH_DURATIONS = (90, 120, 180)
TEAM_COUNTS = (4, 6, 8, 10, 12, 16, 20)


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
    # Real duration of every live match (90 game minutes condensed): 90, 120 or 180 s.
    match_duration_seconds: int = 90
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
            phase=str(payload.get("phase", "WAITING")), market_ends_at=payload.get("market_ends_at"),
            revision=int(payload.get("revision", 0)), participants=participants,
        )
        selected_clubs = [member.selected_club_code for member in participants.values() if member.selected_club_code]
        known_clubs = {club.code for club in CLUBS}
        if room.mode not in {"FIVE_A_SIDE", "ELEVEN_A_SIDE"} or room.market_mode not in {"TRADITIONAL", "COINS"} or room.team_count not in TEAM_COUNTS or room.max_human_participants > room.team_count or room.withdrawal_penalty_percent not in {0, 2, 5, 10} or room.match_duration_seconds not in MATCH_DURATIONS or room.host_user_id not in participants or len(selected_clubs) != len(set(selected_clubs)) or len(selected_clubs) > room.team_count or not set(selected_clubs).issubset(known_clubs):
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
        match_duration_seconds: int = 90,
    ) -> dict[str, object]:
        if team_count not in TEAM_COUNTS or max_human_participants > team_count:
            raise HTTPException(status_code=422, detail="Escolha uma quantidade válida de clubes e técnicos.")
        if market_mode not in {"TRADITIONAL", "COINS"}:
            raise HTTPException(status_code=422, detail="Modo de mercado inválido.")
        if withdrawal_penalty_percent not in {0, 2, 5, 10}:
            raise HTTPException(status_code=422, detail="A multa deve ser 0%, 2%, 5% ou 10%.")
        if match_duration_seconds not in MATCH_DURATIONS:
            raise HTTPException(status_code=422, detail="Duração da partida deve ser 1:30, 2:00 ou 3:00.")
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
                raise HTTPException(status_code=422, detail="Duração da partida deve ser 1:30, 2:00 ou 3:00.")
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
                raise HTTPException(status_code=422, detail="Duração da partida deve ser 1:30, 2:00 ou 3:00.")
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
            draft.phase = "INITIAL_MARKET"
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
            if room.phase != "SQUAD_MANAGEMENT":
                raise HTTPException(status_code=409, detail="A gestão de elenco ainda não está disponível.")
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
