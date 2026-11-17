"""Server authority of the Draft phase (one state per room, under a per-room lock)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from app.core.config import get_settings
from app.domain.catalog import CatalogPlayer, PlayerCatalog, load_catalog
from app.domain.draft import (
    Draft,
    DraftError,
    DraftSquad,
    DraftState,
    best_feasible_minimum,
    feasibility,
)
from app.domain.market import InitialMarket
from app.domain.rooms import DRAFT_MIN_OVERALLS
from app.domain.squad import formations, validate_lineup
from app.services.market_service import MarketSession, market_service
from app.services.squad_service import squad_service

Finished = Callable[[str], Awaitable[None]]


def catalog_path(name: str) -> Path:
    settings = get_settings()
    if name == "BRASILEIRAO":
        return settings.player_catalog_path
    if settings.world_catalog_path.exists():
        return settings.world_catalog_path
    # Deployments that only configure the national catalog ship both files side by side.
    return settings.player_catalog_path.parent / "world_players.json"


_catalog_cache: dict[tuple[str, float], list[CatalogPlayer]] = {}


def draft_catalog(name: str) -> list[CatalogPlayer]:
    path = catalog_path(name)
    try:
        stamp = path.stat().st_mtime
    except OSError as error:
        raise DraftError("Catálogo do Draft indisponível.") from error
    key = (str(path), stamp)
    if key not in _catalog_cache:
        catalog = load_catalog(path)
        if not catalog:
            raise DraftError("Catálogo do Draft indisponível.")
        _catalog_cache.clear()
        _catalog_cache[key] = list(catalog.players)
    return _catalog_cache[key]


def validate_configuration(catalog_name: str, mode: str, min_overall: int) -> None:
    """Refuse an impossible minimum overall and suggest the highest one that works."""
    players = draft_catalog(catalog_name)
    problems = feasibility(players, mode, min_overall)
    if problems:
        best = best_feasible_minimum(players, mode, DRAFT_MIN_OVERALLS)
        hint = f" Overall mínimo viável para este catálogo: {best}." if best is not None else ""
        raise DraftError("Overall mínimo inviável: " + " ".join(problems) + hint)


class DraftService:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self.clock = clock
        self.states: dict[str, DraftState] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._timers: dict[str, asyncio.Task[None]] = {}
        self.bot_clubs: dict[str, set[str]] = {}
        self.difficulty: dict[str, str] = {}
        self.budgets: dict[str, int] = {}

    def lock(self, room_id: str) -> asyncio.Lock:
        return self._locks.setdefault(room_id, asyncio.Lock())

    def _draft(self, room_id: str) -> Draft:
        state = self.states.get(room_id)
        if state is None:
            raise DraftError("Esta sala não está em Draft.")
        return Draft(state, draft_catalog(state.catalog_name))

    # ------------------------------------------------------------------ lifecycle
    def start(self, room_id: str, mode: str, catalog_name: str, min_overall: int, clubs: list[str], bot_clubs: set[str],
              difficulty: str, duration_seconds: int, budget_cents: int) -> DraftState:
        if room_id in self.states:
            return self.states[room_id]
        validate_configuration(catalog_name, mode, min_overall)
        state = DraftState(room_id, mode, catalog_name, min_overall, {club: DraftSquad(club) for club in clubs},
                           deadline=self.clock() + duration_seconds)
        self.states[room_id] = state
        self.bot_clubs[room_id] = set(bot_clubs)
        self.difficulty[room_id] = difficulty
        self.budgets[room_id] = budget_cents
        draft = Draft(state, draft_catalog(catalog_name))
        for club in sorted(bot_clubs):
            draft.auto_complete(club, difficulty)  # bots draft from the same offers
        return state

    def schedule_deadline(self, room_id: str, on_finished: Finished) -> None:
        state = self.states.get(room_id)
        if state is None or state.completed or room_id in self._timers:
            return

        async def wait() -> None:
            try:
                await asyncio.sleep(max(0.0, float(state.deadline or self.clock()) - self.clock()))
                async with self.lock(room_id):
                    finished = self.complete_due(room_id)
                if finished:
                    await on_finished(room_id)
            finally:
                self._timers.pop(room_id, None)

        self._timers[room_id] = asyncio.create_task(wait())

    def complete_due(self, room_id: str, force: bool = False) -> bool:
        """At the deadline (or when the host forces it) absent managers get automatic picks."""
        state = self.states.get(room_id)
        if state is None or state.completed:
            return False
        if not force and self.clock() < float(state.deadline or 0) and not all(state.clubs[c].formation and self._done(state, c) for c in state.clubs):
            return False
        draft = self._draft(room_id)
        for club in sorted(state.clubs):
            if not self._done(state, club):
                state.clubs[club].auto_completed = True
                draft.auto_complete(club, "COMPETITIVE")
        self._finish(room_id, draft)
        return True

    @staticmethod
    def _done(state: DraftState, club: str) -> bool:
        return state.is_complete(club)

    def _finish(self, room_id: str, draft: Draft) -> InitialMarket:
        """Instances become the room's own catalog; the career pipeline runs unchanged."""
        state = draft.state
        players = [player for club in sorted(state.clubs) for player in draft.roster_players(club)]
        catalog = PlayerCatalog(catalog_version=f"draft-{room_id}", source="draft-instances",
                                source_version=state.catalog_name, players=players)
        market = InitialMarket(catalog, state.mode, dict.fromkeys(state.clubs, self.budgets.get(room_id, 0)))
        for club in state.clubs:
            market.teams[club].roster = [p.id for p in players if (p.source_ids or {}).get("draft_owner") == club]
        market.resolved = True
        market.selection_complete = True
        market_service.registry._markets[room_id] = market
        market_service.registry._locks[room_id] = asyncio.Lock()
        market_service.sessions[room_id] = MarketSession(room_id, self.clock(), market, finalized=True, selection_complete=True,
                                                         market_phase="SQUAD_MANAGEMENT")
        for club in state.clubs:
            # The drafted shape is the starting line-up (validated like any other).
            formation, assignments = draft.lineup(club)
            evaluation = validate_lineup(mode=state.mode, formation_code=formation, assignments=assignments,
                                         roster=market.teams[club].roster, players=market.catalog)
            squad_service.commit_lineup(room_id, club, {"formation_code": formation, "assignments": assignments, "evaluation": evaluation})
        state.completed = True
        return market

    # ------------------------------------------------------------------ manager actions
    def set_formation(self, room_id: str, club: str, code: str) -> dict[str, object]:
        draft = self._draft(room_id)
        draft.set_formation(club, code)
        return self.view(room_id, club)

    def open_slot(self, room_id: str, club: str, slot_id: str) -> dict[str, object]:
        draft = self._draft(room_id)
        cards = draft.offer(club, slot_id)
        return {"slot_id": slot_id, "cards": [self.card(c) for c in cards],
                "note": draft.state.clubs[club].offer_notes.get(slot_id)}

    def pick(self, room_id: str, club: str, slot_id: str, catalog_id: str) -> dict[str, object]:
        draft = self._draft(room_id)
        draft.pick(club, slot_id, catalog_id)
        return self.view(room_id, club)

    # ------------------------------------------------------------------ views
    @staticmethod
    def card(player: CatalogPlayer | dict[str, object]) -> dict[str, object]:
        data = player.model_dump(mode="json") if isinstance(player, CatalogPlayer) else dict(player)
        return {key: data.get(key) for key in ("id", "name", "overall", "potential", "position", "secondary_positions",
                                                 "club_code", "club_name", "nationality", "age", "attributes",
                                                 "photo_url", "source", "verification_status")}

    def view(self, room_id: str, club: str) -> dict[str, object]:
        state = self.states.get(room_id)
        if state is None:
            raise DraftError("Esta sala não está em Draft.")
        squad = state.squad(club)
        def instance_view(instance_id: str | None) -> dict[str, object] | None:
            if not instance_id:
                return None
            instance = state.instances[instance_id]
            return {"instance_id": instance_id, "catalog_id": instance["catalog_id"], "card": self.card(dict(instance["card"]))}
        bench = [instance_view(i) for i in squad.bench]
        warnings = []
        if len(squad.bench) == state.bench_size():
            positions = [dict(state.instances[i]["card"])["position"] for i in squad.bench]
            if "GK" not in positions:
                warnings.append("Nenhum goleiro reserva: uma expulsão ou lesão do titular deixará um improvisado no gol.")
            if len(set(positions)) == 1:
                warnings.append("Todos os reservas jogam na mesma posição: poucas alternativas de substituição.")
        return {"room_id": room_id, "mode": state.mode, "catalog": state.catalog_name, "min_overall": state.min_overall,
                "deadline": state.deadline, "server_now": self.clock(), "completed": state.completed,
                "bench_size": state.bench_size(), "formation": squad.formation, "formations": formations(state.mode),
                "slots": {slot: instance_view(i) for slot, i in squad.slots.items()}, "bench": bench,
                "open_offers": {key: [self.card(draft_card) for draft_card in self._cards(state, ids)] for key, ids in squad.offers.items()},
                "warnings": warnings, "complete": state.is_complete(club),
                "progress": {c: {"picks": len([i for i in s.slots.values() if i]) + len(s.bench),
                                 "total": len(s.slots) + state.bench_size() if s.formation else None,
                                 "bot": c in self.bot_clubs.get(room_id, set())} for c, s in state.clubs.items()}}

    @staticmethod
    def _cards(state: DraftState, ids: list[str]) -> list[CatalogPlayer]:
        catalog = {p.id: p for p in draft_catalog(state.catalog_name)}
        return [catalog[i] for i in ids if i in catalog]

    # ------------------------------------------------------------------ snapshots
    def export_room(self, room_id: str) -> dict[str, object] | None:
        state = self.states.get(room_id)
        if state is None:
            return None
        return {"state": state.to_dict(), "bots": sorted(self.bot_clubs.get(room_id, set())),
                "difficulty": self.difficulty.get(room_id, "COMPETITIVE"), "budget_cents": self.budgets.get(room_id, 0)}

    def restore_room(self, room_id: str, payload: dict[str, object]) -> None:
        self.states[room_id] = DraftState.from_dict(dict(payload["state"]))
        self.bot_clubs[room_id] = set(map(str, payload.get("bots", [])))
        self.difficulty[room_id] = str(payload.get("difficulty", "COMPETITIVE"))
        self.budgets[room_id] = int(payload.get("budget_cents", 0))


draft_service = DraftService()
