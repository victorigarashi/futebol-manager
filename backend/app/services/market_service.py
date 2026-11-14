"""Authoritative market lifecycle with absolute deadlines and background settlement."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from app.domain.catalog import CatalogPlayer, PlayerCatalog
from app.domain.market import (
    InitialMarket,
    MarketError,
    MarketRegistry,
    Offer,
    OfferStatus,
    TeamMarketState,
)

Notify = Callable[[str, dict[str, object]], Awaitable[None]]
Resolved = Callable[[str], Awaitable[None]]
Progressed = Callable[[str, str], Awaitable[None]]


@dataclass
class MarketSession:
    room_id: str
    ends_at: float
    market: InitialMarket
    task: asyncio.Task[None] | None = None
    on_resolved: Resolved | None = None
    finalized: bool = False
    on_progressed: Progressed | None = None
    human_clubs: set[str] = field(default_factory=set)
    managers: dict[str, str] = field(default_factory=dict)
    selection_ends_at: float | None = None
    selection_duration_seconds: int = 120
    reassignment_ends_at: float | None = None
    selection_complete: bool = False
    market_phase: str = "INITIAL_MARKET"
    current_reassignment: dict[str, object] | None = None
    timer_task: asyncio.Task[None] | None = None
    withdrawals_by_club: dict[str, int] = field(default_factory=dict)


class MarketService:
    def __init__(self, clock: Callable[[], float] = time.time, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
        self.registry = MarketRegistry()
        self.sessions: dict[str, MarketSession] = {}
        self._clock = clock
        self._sleep = sleep

    def start(self, room_id: str, catalog: PlayerCatalog, mode: str, teams: dict[str, int], duration_seconds: int, notify: Notify, on_resolved: Resolved | None = None, *, withdrawal_penalty_percent: int = 5, on_progressed: Progressed | None = None) -> MarketSession:
        if room_id in self.sessions:
            return self.sessions[room_id]
        market = InitialMarket(catalog, mode, teams, withdrawal_penalty_percent)
        viability = market.viable()
        if not viability.viable:
            raise MarketError("Mercado inviável: " + " ".join(viability.reasons))
        self.registry._markets[room_id] = market
        self.registry._locks[room_id] = asyncio.Lock()
        session = MarketSession(room_id=room_id, ends_at=self._clock() + duration_seconds, market=market, on_resolved=on_resolved, on_progressed=on_progressed)
        session.task = asyncio.create_task(self._close_when_due(session, notify))
        self.sessions[room_id] = session
        return session

    def export_room(self, room_id: str) -> dict[str, object]:
        session = self._session(room_id)
        market = session.market
        return {
            "room_id": room_id, "ends_at": session.ends_at, "finalized": session.finalized,
            "catalog": market.catalog_payload, "mode": market.mode, "resolved": market.resolved,
            "penalty_percent": market.penalty_percent, "commitments": market.commitments,
            "excess_offers": market.excess_offers, "confirmed_clubs": sorted(market.confirmed_clubs),
            "confirmations": market.confirmations, "generated_players": market.generated_players,
            "transactions": market.transactions, "reassignment": market.reassignment,
            "reassignment_responses": market.reassignment_responses, "review": market.review,
            "selection_complete": market.selection_complete,
            "sequence": market._sequence,
            "teams": {code: {"budget_cents": team.budget_cents, "initial_budget_cents": team.initial_budget_cents, "spent_cents": team.spent_cents, "reserved_cents": team.reserved_cents, "roster": list(team.roster), "financial_ledger": team.financial_ledger, "paid_operation_ids": sorted(team.paid_operation_ids)} for code, team in market.teams.items()},
            "offers": [{"id": offer.id, "idempotency_key": offer.idempotency_key, "club_code": offer.club_code, "player_id": offer.player_id, "amount_cents": offer.amount_cents, "sequence": offer.sequence, "status": offer.status.value} for offer in market.offers.values()],
            "session": {"human_clubs": sorted(session.human_clubs), "managers": session.managers, "selection_ends_at": session.selection_ends_at, "selection_duration_seconds": session.selection_duration_seconds, "reassignment_ends_at": session.reassignment_ends_at, "selection_complete": session.selection_complete, "market_phase": session.market_phase, "current_reassignment": session.current_reassignment, "withdrawals_by_club": session.withdrawals_by_club},
        }

    def restore_room(self, payload: dict[str, object], notify: Notify, on_resolved: Resolved | None = None, on_progressed: Progressed | None = None, *, schedule_tasks: bool = True) -> MarketSession:
        room_id = str(payload["room_id"])
        if room_id in self.sessions:
            return self.sessions[room_id]
        catalog = PlayerCatalog.model_validate(payload["catalog"])
        teams_payload = payload["teams"]
        if not isinstance(teams_payload, dict):
            raise ValueError("Snapshot do mercado não contém clubes válidos.")
        mode = str(payload["mode"])
        penalty = int(payload.get("penalty_percent", 5))
        market = InitialMarket(catalog, mode, {str(code): int(team["budget_cents"]) for code, team in teams_payload.items()}, penalty)
        self.registry._markets[room_id] = market
        self.registry._locks[room_id] = asyncio.Lock()
        for code, team_payload in teams_payload.items():
            if code not in market.teams:
                raise ValueError("Snapshot do mercado referencia clube inválido.")
            market.teams[code] = TeamMarketState(str(code), int(team_payload["budget_cents"]), list(team_payload["roster"]), int(team_payload["reserved_cents"]), list(team_payload.get("financial_ledger", [])), set(team_payload.get("paid_operation_ids", [])), int(team_payload.get("initial_budget_cents", int(team_payload["budget_cents"]) + int(team_payload.get("spent_cents", 0)))), int(team_payload.get("spent_cents", 0)))
        for raw in payload.get("offers", []):
            offer = Offer(str(raw["id"]), str(raw["idempotency_key"]), str(raw["club_code"]), str(raw["player_id"]), int(raw["amount_cents"]), int(raw["sequence"]), OfferStatus(str(raw["status"])))
            if offer.club_code not in market.teams or offer.player_id not in market.catalog:
                raise ValueError("Snapshot contém proposta para clube ou atleta inexistente.")
            market.offers[offer.id] = offer
            market._idempotency[(offer.club_code, offer.idempotency_key)] = offer.id
        market.resolved = bool(payload["resolved"])
        market.commitments = {str(club): list(map(str, ids)) for club, ids in payload.get("commitments", {}).items()} or {club: [] for club in market.teams}
        market.excess_offers = {str(club): list(map(str, ids)) for club, ids in payload.get("excess_offers", {}).items()} or {club: [] for club in market.teams}
        market.confirmed_clubs = set(map(str, payload.get("confirmed_clubs", [])))
        market.confirmations = dict(payload.get("confirmations", {}))
        market.generated_players = dict(payload.get("generated_players", {}))
        for player_id, raw_player in market.generated_players.items():
            player = CatalogPlayer.model_validate(raw_player)
            if player.id != player_id or player.source != "synthetic-career":
                raise ValueError("Snapshot contém jogador genérico inválido.")
            market.catalog[player.id] = player
        market.transactions = list(payload.get("transactions", []))
        market.reassignment = list(payload.get("reassignment", []))
        market.reassignment_responses = dict(payload.get("reassignment_responses", {}))
        market.review = list(payload.get("review", []))
        market.selection_complete = bool(payload.get("selection_complete", False))
        legacy_settled = "selection_complete" not in payload and market.resolved
        if legacy_settled:
            market.selection_complete = True
        if market.confirmed_clubs != set(market.confirmations):
            raise ValueError("Confirmações do snapshot não reconciliam com os clubes confirmados.")
        owned: set[str] = set()
        for code, team in market.teams.items():
            if team.budget_cents < 0 or team.reserved_cents < 0 or team.available_cents < 0:
                raise ValueError("Snapshot do mercado contém saldo ou reserva negativa.")
            if len(team.roster) != len(set(team.roster)) or any(player_id not in market.catalog for player_id in team.roster):
                raise ValueError("Snapshot do mercado contém atleta duplicado ou inexistente.")
            if owned.intersection(team.roster):
                raise ValueError("Snapshot atribui o mesmo atleta a mais de um clube.")
            owned.update(team.roster)
            reserved_statuses = {OfferStatus.ACTIVE} if not market.resolved else {OfferStatus.COMMITTED, OfferStatus.EXCESS}
            expected_reserved = sum(offer.amount_cents for offer in market.offers.values() if offer.club_code == code and offer.status in reserved_statuses)
            if expected_reserved != team.reserved_cents:
                raise ValueError("Reservas do mercado não reconciliam com as ofertas provisórias.")
            if sum(offer.club_code == code and offer.status == OfferStatus.ACTIVE for offer in market.offers.values()) > market.offer_limit:
                raise ValueError("Snapshot excede o limite de propostas ativas do clube.")
            if market.selection_complete:
                expected_roster_size = sum(market.slots.values()) if legacy_settled else market.max_roster_size
                if team.reserved_cents != 0 or len(team.roster) != expected_roster_size:
                    raise ValueError("Elenco confirmado no snapshot está incompleto.")
                if any(market._position_count(team, position) < count for position, count in market.slots.items()):
                    raise ValueError("Elenco resolvido no snapshot viola vagas por posição.")
        market._sequence = int(payload["sequence"])
        session_payload = payload.get("session", {})
        if not isinstance(session_payload, dict):
            session_payload = {}
        session = MarketSession(room_id, float(payload["ends_at"]), market, on_resolved=on_resolved, finalized=bool(payload.get("finalized", False)), human_clubs=set(map(str, session_payload.get("human_clubs", []))), managers=dict(session_payload.get("managers", {})), selection_ends_at=session_payload.get("selection_ends_at"), selection_duration_seconds=int(session_payload.get("selection_duration_seconds", 120)), reassignment_ends_at=session_payload.get("reassignment_ends_at"), selection_complete=bool(session_payload.get("selection_complete", market.selection_complete)), market_phase=str(session_payload.get("market_phase", "SQUAD_MANAGEMENT" if legacy_settled else "INITIAL_MARKET")), current_reassignment=session_payload.get("current_reassignment"), withdrawals_by_club=dict(session_payload.get("withdrawals_by_club", {})), on_progressed=on_progressed)
        self.sessions[room_id] = session
        if not schedule_tasks:
            return session
        if not market.resolved:
            session.task = asyncio.create_task(self._close_when_due(session, notify))
        elif not session.finalized and on_resolved:
            session.task = asyncio.create_task(on_resolved(room_id))
        elif not market.selection_complete and session.selection_ends_at is not None:
            session.timer_task = asyncio.create_task(self._phase_deadline_loop(session))
        elif session.market_phase == "MARKET_REASSIGNMENT" and session.reassignment_ends_at is not None:
            session.timer_task = asyncio.create_task(self._phase_deadline_loop(session))
        return session

    async def _close_when_due(self, session: MarketSession, notify: Notify) -> None:
        await self._sleep(max(0, session.ends_at - self._clock()))
        if await self.resolve_if_due(session.room_id):
            await notify(session.room_id, {"type": "market.resolved"})

    async def resolve_if_due(self, room_id: str, now: float | None = None) -> bool:
        session = self._session(room_id)
        if (self._clock() if now is None else now) < session.ends_at:
            return False
        await self.registry.resolve(room_id)
        if not session.finalized:
            session.finalized = True
            if session.on_resolved:
                await session.on_resolved(room_id)
        return True

    async def start_selection(self, room_id: str, human_clubs: set[str], managers: dict[str, str], duration_seconds: int, on_progressed: Progressed) -> None:
        session = self._session(room_id)
        async with self.registry._locks[room_id]:
            if not session.market.resolved:
                raise MarketError("As ofertas ainda não foram apuradas.")
            if session.market_phase != "INITIAL_MARKET":
                return
            session.human_clubs = set(human_clubs)
            session.managers = dict(managers)
            session.selection_duration_seconds = max(1, duration_seconds)
            session.selection_ends_at = self._clock() + session.selection_duration_seconds
            session.market_phase = "MARKET_SELECTION"
            session.on_progressed = on_progressed
            bot_clubs = set(session.market.teams) - session.human_clubs
            for club in sorted(bot_clubs):
                offer_ids = list(session.market.commitments.get(club, []))
                op_id = f"{room_id}:initial-market:automatic-selection:{club}"
                session.market.confirm_selection(club, offer_ids, op_id, automatic=True)
            if session.timer_task and not session.timer_task.done():
                session.timer_task.cancel()
            session.timer_task = asyncio.create_task(self._phase_deadline_loop(session))
            phase = self._advance_after_selection_locked(session) if session.human_clubs.issubset(session.market.confirmed_clubs) else session.market_phase
        if session.on_progressed:
            await session.on_progressed(room_id, phase)

    def selection_for(self, room_id: str, club_code: str) -> dict[str, object]:
        session = self._session(room_id)
        market = session.market
        if not market.resolved or session.market_phase != "MARKET_SELECTION":
            raise MarketError("A seleção de jogadores não está aberta.")
        if club_code not in session.human_clubs:
            raise MarketError("Este clube não possui técnico humano nesta seleção.")
        team = market.teams[club_code]
        rights = [market.offers[offer_id] for offer_id in [*market.commitments[club_code], *market.excess_offers[club_code]]]
        return {
            "phase": session.market_phase,
            "ends_at": session.selection_ends_at,
            "remaining_seconds": max(0, int((session.selection_ends_at or self._clock()) - self._clock())),
            "confirmed": club_code in market.confirmed_clubs,
            "club_code": club_code,
            "budget_cents": team.budget_cents,
            "total_budget_cents": team.total_budget_cents,
            "spent_cents": team.spent_cents,
            "reserved_cents": team.reserved_cents,
            "available_cents": team.available_cents,
            "withdrawal_penalty_percent": market.penalty_percent,
            "max_roster_size": market.max_roster_size,
            "committed": [{"offer_id": offer.id, "classification": "COMPROMISSADA", "amount_cents": offer.amount_cents, "player": market.catalog[offer.player_id].model_dump()} for offer in rights if offer.status == OfferStatus.COMMITTED],
            "excess": [{"offer_id": offer.id, "classification": "EXCEDENTE SEM MULTA", "amount_cents": offer.amount_cents, "player": market.catalog[offer.player_id].model_dump()} for offer in rights if offer.status == OfferStatus.EXCESS],
        }

    async def preview_selection(self, room_id: str, club_code: str, offer_ids: list[str]) -> dict[str, object]:
        session = self._session(room_id)
        async with self.registry._locks[room_id]:
            return session.market.selection_preview(club_code, offer_ids)

    async def confirm_selection(self, room_id: str, club_code: str, offer_ids: list[str], operation_id: str) -> dict[str, object]:
        session = self._session(room_id)
        async with self.registry._locks[room_id]:
            if club_code not in session.human_clubs:
                raise MarketError("Somente um clube humano pode confirmar esta seleção.")
            if club_code in session.market.confirmations and session.market_phase != "MARKET_SELECTION":
                return session.market.confirmations[club_code]
            if session.market_phase != "MARKET_SELECTION":
                raise MarketError("A fase de seleção foi encerrada.")
            result = session.market.confirm_selection(club_code, offer_ids, operation_id)
            preview = session.market.confirmations[club_code]
            if int(preview.get("penalty_cents", 0)):
                session.withdrawals_by_club[club_code] = session.withdrawals_by_club.get(club_code, 0) + int(preview["penalty_cents"])
            phase = self._advance_after_selection_locked(session) if session.human_clubs.issubset(session.market.confirmed_clubs) else session.market_phase
            if phase == "MARKET_REASSIGNMENT":
                self._restart_phase_timer(session)
        if session.on_progressed:
            await session.on_progressed(room_id, phase)
        return result

    def current_reassignment_for(self, room_id: str, club_code: str) -> dict[str, object] | None:
        session = self._session(room_id)
        current = session.current_reassignment
        if session.market_phase != "MARKET_REASSIGNMENT" or current is None or current.get("club_code") != club_code:
            return None
        return {**current, "ends_at": session.reassignment_ends_at, "remaining_seconds": max(0, int((session.reassignment_ends_at or self._clock()) - self._clock()))}

    async def respond_reassignment(self, room_id: str, club_code: str, offer_id: str, accept: bool) -> dict[str, object]:
        session = self._session(room_id)
        async with self.registry._locks[room_id]:
            previous = session.market.reassignment_responses.get(offer_id)
            if previous is not None:
                if previous.get("club_code") != club_code:
                    raise MarketError("Esta segunda oportunidade pertence a outro clube.")
                return previous
            if session.market_phase != "MARKET_REASSIGNMENT":
                raise MarketError("Não há redistribuição em andamento.")
            operation_id = f"{room_id}:reassignment:{offer_id}:{'accept' if accept else 'decline'}"
            result = session.market.respond_reassignment(club_code, offer_id, accept, operation_id)
            phase = self._advance_reassignment_locked(session)
            if phase == "MARKET_REASSIGNMENT":
                self._restart_phase_timer(session)
        if session.on_progressed:
            await session.on_progressed(room_id, phase)
        return result

    def review_for(self, room_id: str) -> dict[str, object]:
        session = self._session(room_id)
        if session.market_phase != "MARKET_REVIEW" and not session.market.selection_complete:
            raise MarketError("A review pública ainda não está disponível.")
        market = session.market
        entries = []
        for number, transaction in enumerate(market.review, 1):
            player = market.catalog[str(transaction["player_id"])]
            club = str(transaction["club_code"])
            entries.append({"number": number, "total": len(market.review), "player_id": player.id, "player_name": player.name, "position": player.position, "overall": player.overall, "origin_club_code": player.club_code, "buyer_club_code": club, "manager_name": session.managers.get(club, f"Bot do {club}"), "amount_cents": abs(int(transaction["amount_cents"]))})
        return {"entries": entries, "summary": {"player_count": len(entries), "total_spent_cents": sum(item["amount_cents"] for item in entries), "generic_players_by_club": {club: sum(player_id in market.generated_players for player_id in team.roster) for club, team in market.teams.items()}, "balances_cents": {club: team.budget_cents for club, team in market.teams.items()}, "withdrawals_cents": dict(session.withdrawals_by_club)}}

    async def complete_review(self, room_id: str) -> None:
        session = self._session(room_id)
        if session.market_phase != "MARKET_REVIEW":
            raise MarketError("A review ainda não terminou.")
        session.market_phase = "SQUAD_MANAGEMENT"
        if session.on_progressed:
            await session.on_progressed(room_id, "SQUAD_MANAGEMENT")

    def _advance_after_selection_locked(self, session: MarketSession) -> str:
        market = session.market
        market.prepare_reassignment()
        return self._advance_reassignment_locked(session)

    def _advance_reassignment_locked(self, session: MarketSession) -> str:
        market = session.market
        current = market.current_reassignment(session.human_clubs)
        if current:
            session.current_reassignment = current
            session.reassignment_ends_at = self._clock() + session.selection_duration_seconds
            session.market_phase = "MARKET_REASSIGNMENT"
            return session.market_phase
        session.current_reassignment = None
        session.reassignment_ends_at = None
        market.finalize_rosters(session.room_id)
        for transaction in market.review:
            club = str(transaction["club_code"])
            transaction["manager_name"] = session.managers.get(club, f"Bot do {club}")
        session.selection_complete = True
        session.market_phase = "MARKET_REVIEW"
        return session.market_phase

    def _restart_phase_timer(self, session: MarketSession) -> None:
        if session.timer_task and not session.timer_task.done() and session.timer_task is not asyncio.current_task():
            session.timer_task.cancel()
        session.timer_task = asyncio.create_task(self._phase_deadline_loop(session))

    async def _phase_deadline_loop(self, session: MarketSession) -> None:
        while session.market_phase in {"MARKET_SELECTION", "MARKET_REASSIGNMENT"}:
            deadline = session.selection_ends_at if session.market_phase == "MARKET_SELECTION" else session.reassignment_ends_at
            await self._sleep(max(0, float(deadline or self._clock()) - self._clock()))
            async with self.registry._locks[session.room_id]:
                if session.market_phase == "MARKET_SELECTION" and session.selection_ends_at is not None and self._clock() >= session.selection_ends_at:
                    for club in sorted(session.human_clubs - session.market.confirmed_clubs):
                        offer_ids = list(session.market.commitments.get(club, []))
                        operation_id = f"{session.room_id}:initial-market:automatic-selection:{club}"
                        session.market.confirm_selection(club, offer_ids, operation_id, automatic=True)
                    if session.human_clubs.issubset(session.market.confirmed_clubs):
                        phase = self._advance_after_selection_locked(session)
                    else:
                        phase = session.market_phase
                elif session.market_phase == "MARKET_REASSIGNMENT" and session.current_reassignment and session.reassignment_ends_at is not None and self._clock() >= session.reassignment_ends_at:
                    club = str(session.current_reassignment["club_code"])
                    offer_id = str(session.current_reassignment["offer_id"])
                    operation_id = f"{session.room_id}:reassignment:{offer_id}:expire"
                    session.market.respond_reassignment(club, offer_id, False, operation_id)
                    phase = self._advance_reassignment_locked(session)
                else:
                    continue
            if session.on_progressed:
                await session.on_progressed(session.room_id, phase)

    async def offer(self, room_id: str, club_code: str, player_id: str, amount_cents: int, idempotency_key: str) -> Offer:
        await self._assert_open(room_id)
        return await self.registry.submit_offer(room_id, club_code, player_id, amount_cents, idempotency_key)

    async def update_offer(self, room_id: str, club_code: str, offer_id: str, amount_cents: int) -> Offer:
        await self._assert_open(room_id)
        session = self._session(room_id)
        async with self.registry._locks[room_id]:
            return session.market.update_offer(offer_id, club_code, amount_cents)

    async def cancel_offer(self, room_id: str, club_code: str, offer_id: str) -> Offer:
        await self._assert_open(room_id)
        session = self._session(room_id)
        async with self.registry._locks[room_id]:
            return session.market.cancel_offer(offer_id, club_code)

    def state_for(self, room_id: str, club_code: str) -> dict[str, object]:
        session = self._session(room_id)
        market = session.market
        team = market.teams[club_code]
        mine = [offer for offer in market.offers.values() if offer.club_code == club_code]
        current_time = self._clock()
        return {"phase": session.market_phase, "ends_at": session.ends_at, "remaining_seconds": max(0, int(session.ends_at - current_time)) if not market.resolved else max(0, int(((session.selection_ends_at if session.market_phase == "MARKET_SELECTION" else session.reassignment_ends_at) or current_time) - current_time)), "resolved": market.resolved, "total_budget_cents": team.total_budget_cents, "budget_cents": team.budget_cents, "spent_cents": team.spent_cents, "reserved_cents": team.reserved_cents, "available_cents": team.available_cents, "offer_limit": market.offer_limit, "active_offer_count": sum(offer.status == OfferStatus.ACTIVE for offer in mine), "withdrawal_penalty_percent": market.penalty_percent, "roster": list(team.roster), "offers": [self._offer_view(offer) for offer in mine]}

    def result_for(self, room_id: str, club_code: str) -> dict[str, object]:
        session = self._session(room_id)
        market = session.market
        if not market.selection_complete:
            raise MarketError("A seleção do mercado ainda não foi concluída.")
        team = market.teams[club_code]
        offers = [offer for offer in market.offers.values() if offer.club_code == club_code]
        return {"club_code": club_code, "budget_cents": team.budget_cents, "roster": [market.catalog[player_id].model_dump() for player_id in team.roster], "offers": [self._offer_view(offer) for offer in offers]}

    @staticmethod
    def _offer_view(offer: Offer) -> dict[str, object]:
        return {"id": offer.id, "player_id": offer.player_id, "amount_cents": offer.amount_cents, "status": offer.status}

    async def _assert_open(self, room_id: str) -> None:
        if await self.resolve_if_due(room_id):
            raise MarketError("O prazo do mercado terminou.")
        if self._session(room_id).market.resolved:
            raise MarketError("O mercado já foi resolvido.")

    def _session(self, room_id: str) -> MarketSession:
        if room_id not in self.sessions:
            raise MarketError("Mercado não iniciado para esta sala.")
        return self.sessions[room_id]


market_service = MarketService()
