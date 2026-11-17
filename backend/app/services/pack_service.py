"""Server authority of the Pack & Play phase (one state per room, per-room lock).

Packs are generated once per manager from a seed (room, club) and stored: opening them
again only reveals what was already decided. When every squad is confirmed (or the
deadline passes and absent managers are completed automatically) the chosen cards
become independent instances and go through exactly the same pipeline as the Draft:
the room's own catalog, validated line-ups, squad phase, then the tournament.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from app.domain.draft import Draft, DraftSquad, DraftState
from app.domain.packs import PackCollection, PackError, Packs, PackState, open_packs
from app.services.draft_service import draft_catalog, draft_service

Finished = Callable[[str], Awaitable[None]]


class PackService:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self.clock = clock
        self.states: dict[str, PackState] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._timers: dict[str, asyncio.Task[None]] = {}
        self.bot_clubs: dict[str, set[str]] = {}
        self.difficulty: dict[str, str] = {}
        self.budgets: dict[str, int] = {}

    def lock(self, room_id: str) -> asyncio.Lock:
        return self._locks.setdefault(room_id, asyncio.Lock())

    def _packs(self, room_id: str) -> Packs:
        state = self.states.get(room_id)
        if state is None:
            raise PackError("Esta sala não está no Pack & Play.")
        return Packs(state, draft_catalog(state.catalog_name))

    # ------------------------------------------------------------------ lifecycle
    def start(self, room_id: str, mode: str, catalog_name: str, luck: str, clubs: list[str], bot_clubs: set[str],
              difficulty: str, duration_seconds: int, budget_cents: int) -> PackState:
        if room_id in self.states:
            return self.states[room_id]
        catalog = draft_catalog(catalog_name)
        collections = {club: PackCollection(club, open_packs(f"{room_id}:{club}:packs", mode, catalog, luck)) for club in clubs}
        state = PackState(room_id, mode, catalog_name, luck, collections, deadline=self.clock() + duration_seconds)
        self.states[room_id] = state
        self.bot_clubs[room_id] = set(bot_clubs)
        self.difficulty[room_id] = difficulty
        self.budgets[room_id] = budget_cents
        packs = Packs(state, catalog)
        for club in sorted(bot_clubs):
            packs.auto_complete(club, difficulty)  # bots open the same kind of packs
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
        state = self.states.get(room_id)
        if state is None or state.completed:
            return False
        if not force and self.clock() < float(state.deadline or 0) and not all(c.confirmed for c in state.clubs.values()):
            return False
        packs = self._packs(room_id)
        for club, collection in sorted(state.clubs.items()):
            if not collection.confirmed:
                collection.auto_completed = True
                packs.auto_complete(club, "COMPETITIVE")
        self._finish(room_id, packs)
        return True

    def _finish(self, room_id: str, packs: Packs) -> None:
        """Chosen cards become independent instances; the Draft pipeline does the rest."""
        state = packs.state
        draft_state = DraftState(room_id, state.mode, state.catalog_name, 0, {})
        for club, collection in sorted(state.clubs.items()):
            squad = DraftSquad(club, formation=collection.formation)
            for index, (slot_id, catalog_id) in enumerate(collection.slots.items()):
                squad.slots[slot_id] = self._instance(draft_state, club, index, str(catalog_id), packs)
            squad.bench = [self._instance(draft_state, club, 50 + i, cid, packs) for i, cid in enumerate(collection.bench)]
            draft_state.clubs[club] = squad
        draft_service.budgets[room_id] = self.budgets.get(room_id, 0)
        draft_service._finish(room_id, Draft(draft_state, list(packs.catalog.values())))
        state.completed = True

    @staticmethod
    def _instance(draft_state: DraftState, club: str, index: int, catalog_id: str, packs: Packs) -> str:
        instance_id = f"PCK-{club}-{index:02d}-{catalog_id}"
        draft_state.instances[instance_id] = {"card": packs.catalog[catalog_id].model_dump(), "catalog_id": catalog_id, "owner": club}
        return instance_id

    # ------------------------------------------------------------------ manager actions
    def view(self, room_id: str, club: str) -> dict[str, object]:
        state = self.states.get(room_id)
        if state is None:
            raise PackError("Esta sala não está no Pack & Play.")
        packs = self._packs(room_id)
        others = [{"club_code": c, "confirmed": col.confirmed, "opened": col.opened, "bot": c in self.bot_clubs.get(room_id, set())}
                  for c, col in sorted(state.clubs.items())]
        return {**packs.collection_view(club), "deadline": state.deadline, "server_now": self.clock(), "completed": state.completed,
                "luck": state.luck, "catalog": state.catalog_name, "mode": state.mode, "managers": others}

    def open_next(self, room_id: str, club: str) -> dict[str, object]:
        self._packs(room_id).open_next(club)
        return self.view(room_id, club)

    def set_formation(self, room_id: str, club: str, code: str) -> dict[str, object]:
        self._packs(room_id).set_formation(club, code)
        return self.view(room_id, club)

    def place(self, room_id: str, club: str, slot_id: str, catalog_id: str | None) -> dict[str, object]:
        self._packs(room_id).place(club, slot_id, catalog_id)
        return self.view(room_id, club)

    def set_bench(self, room_id: str, club: str, catalog_ids: list[str]) -> dict[str, object]:
        self._packs(room_id).set_bench(club, catalog_ids)
        return self.view(room_id, club)

    def confirm(self, room_id: str, club: str) -> dict[str, object]:
        self._packs(room_id).confirm(club)
        return self.view(room_id, club)

    # ------------------------------------------------------------------ snapshots
    def export_room(self, room_id: str) -> dict[str, object] | None:
        state = self.states.get(room_id)
        if state is None:
            return None
        return {"state": state.to_dict(), "bots": sorted(self.bot_clubs.get(room_id, set())),
                "difficulty": self.difficulty.get(room_id, "COMPETITIVE"), "budget_cents": self.budgets.get(room_id, 0)}

    def restore_room(self, room_id: str, payload: dict[str, object]) -> None:
        self.states[room_id] = PackState.from_dict(dict(payload["state"]))
        self.bot_clubs[room_id] = set(map(str, payload.get("bots", [])))
        self.difficulty[room_id] = str(payload.get("difficulty", "COMPETITIVE"))
        self.budgets[room_id] = int(payload.get("budget_cents", 0))


pack_service = PackService()
