"""Deterministic, in-memory initial market. The API layer owns room locks."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from app.domain.catalog import CatalogPlayer, PlayerCatalog


class MarketError(ValueError):
    pass


class OfferStatus(StrEnum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    COMMITTED = "COMMITTED"
    EXCESS = "EXCESS"
    LOST = "LOST"
    WON = "WON"  # Legacy settled snapshots only.
    DECLINED = "DECLINED"
    CONFIRMED = "CONFIRMED"
    REASSIGNMENT_AVAILABLE = "REASSIGNMENT_AVAILABLE"
    EXPIRED = "EXPIRED"


FORMATION_SLOTS = {
    "FIVE_A_SIDE": {"GK": 1, "DF": 2, "MF": 1, "ST": 1},
    "ELEVEN_A_SIDE": {"GK": 1, "DF": 4, "MF": 3, "ST": 3},
}


@dataclass
class Offer:
    id: str
    idempotency_key: str
    club_code: str
    player_id: str
    amount_cents: int
    sequence: int
    status: OfferStatus = OfferStatus.ACTIVE


@dataclass
class TeamMarketState:
    club_code: str
    budget_cents: int
    roster: list[str] = field(default_factory=list)
    reserved_cents: int = 0
    financial_ledger: list[dict[str, object]] = field(default_factory=list)
    paid_operation_ids: set[str] = field(default_factory=set)
    initial_budget_cents: int = 0
    spent_cents: int = 0

    @property
    def total_budget_cents(self) -> int:
        return self.budget_cents + self.spent_cents

    @property
    def available_cents(self) -> int:
        return self.budget_cents - self.reserved_cents


@dataclass
class MarketViability:
    viable: bool
    reasons: list[str] = field(default_factory=list)


class InitialMarket:
    """Pure rules: callers serialize mutations with their per-room async lock."""

    def __init__(self, catalog: PlayerCatalog, mode: str, teams: dict[str, int], withdrawal_penalty_percent: int = 5) -> None:
        if mode not in FORMATION_SLOTS:
            raise MarketError("Modo de jogo inválido.")
        self.catalog = {player.id: player for player in catalog.players}
        self.catalog_payload = catalog.model_dump(mode="json")
        if len(self.catalog) != len(catalog.players):
            raise MarketError("Catálogo contém identificadores duplicados.")
        self.mode = mode
        self.slots = FORMATION_SLOTS[mode]
        self.max_roster_size = 8 if mode == "FIVE_A_SIDE" else 16
        self.offer_limit = 16 if mode == "FIVE_A_SIDE" else 48
        self.teams = {club: TeamMarketState(club, budget, initial_budget_cents=budget) for club, budget in teams.items()}
        self.offers: dict[str, Offer] = {}
        self._idempotency: dict[tuple[str, str], str] = {}
        self._sequence = 0
        self.resolved = False
        self.commitments: dict[str, list[str]] = {club: [] for club in teams}
        self.excess_offers: dict[str, list[str]] = {club: [] for club in teams}
        self.confirmed_clubs: set[str] = set()
        self.confirmations: dict[str, dict[str, object]] = {}
        self.generated_players: dict[str, dict[str, object]] = {}
        self.transactions: list[dict[str, object]] = []
        self.reassignment: list[dict[str, object]] = []
        self.reassignment_responses: dict[str, dict[str, object]] = {}
        self.review: list[dict[str, object]] = []
        self.selection_complete = False
        if withdrawal_penalty_percent not in {0, 2, 5, 10}:
            raise MarketError("Percentual de multa inválido.")
        self.penalty_percent = withdrawal_penalty_percent

    def viable(self) -> MarketViability:
        reasons: list[str] = []
        total_teams = len(self.teams)
        if total_teams == 0:
            reasons.append("Não há clubes para montar elencos.")
        for position, required in self.slots.items():
            available = sum(player.position == position for player in self.catalog.values())
            need = required * total_teams
            if available < need:
                reasons.append(f"Faltam {need - available} atletas da posição {position}.")
        required_count = sum(self.slots.values()) * total_teams
        if len(self.catalog) < required_count:
            reasons.append(f"Faltam {required_count - len(self.catalog)} atletas para completar os elencos.")
        # No budget floor: a club that buys nobody keeps its own catalog players for free and
        # finalize_rosters completes any gap with free generics, so every budget >= 0 is playable.
        for team in self.teams.values():
            if team.budget_cents < 0:
                reasons.append(f"{team.club_code} não possui orçamento para o elenco mínimo.")
        return MarketViability(viable=not reasons, reasons=reasons)

    def search(self, *, query: str = "", position: str | None = None, min_overall: int | None = None, max_overall: int | None = None, min_price_cents: int | None = None, max_price_cents: int | None = None) -> list[CatalogPlayer]:
        if any(value is not None and value < 0 for value in (min_overall, max_overall, min_price_cents, max_price_cents)):
            raise MarketError("Os filtros de overall e preço não podem ser negativos.")
        if min_overall is not None and max_overall is not None and min_overall > max_overall:
            raise MarketError("A faixa de overall está invertida.")
        if min_price_cents is not None and max_price_cents is not None and min_price_cents > max_price_cents:
            raise MarketError("A faixa de preço está invertida.")
        needle = query.casefold().strip()
        players = [player for player in self.catalog.values() if player.id not in self._assigned_players()]
        if needle:
            players = [player for player in players if needle in player.name.casefold() or needle in player.club_code.casefold()]
        if position:
            players = [player for player in players if player.position == position]
        if max_overall is not None:
            players = [player for player in players if player.overall <= max_overall]
        if min_overall is not None:
            players = [player for player in players if player.overall >= min_overall]
        if min_price_cents is not None:
            players = [player for player in players if player.market_value_cents >= min_price_cents]
        if max_price_cents is not None:
            players = [player for player in players if player.market_value_cents <= max_price_cents]
        return sorted(players, key=lambda player: (-player.overall, player.name, player.id))

    def submit_offer(self, club_code: str, player_id: str, amount_cents: int, idempotency_key: str) -> Offer:
        if self.resolved:
            raise MarketError("O mercado já foi resolvido.")
        if (club_code, idempotency_key) in self._idempotency:
            return self.offers[self._idempotency[(club_code, idempotency_key)]]
        team = self._team(club_code)
        active_count = sum(offer.club_code == club_code and offer.status == OfferStatus.ACTIVE for offer in self.offers.values())
        if active_count >= self.offer_limit:
            raise MarketError(f"Limite de {self.offer_limit} propostas ativas atingido.")
        player = self._player(player_id)
        if amount_cents < player.market_value_cents:
            raise MarketError("A proposta precisa atingir o valor-base do atleta.")
        if player_id in self._assigned_players():
            raise MarketError("Atleta já contratado.")
        if amount_cents > team.available_cents:
            raise MarketError("Saldo insuficiente para reservar esta proposta.")
        self._sequence += 1
        offer = Offer(id=f"offer-{self._sequence}", idempotency_key=idempotency_key, club_code=club_code, player_id=player_id, amount_cents=amount_cents, sequence=self._sequence)
        self.offers[offer.id] = offer
        self._idempotency[(club_code, idempotency_key)] = offer.id
        team.reserved_cents += amount_cents
        return offer

    def update_offer(self, offer_id: str, club_code: str, amount_cents: int) -> Offer:
        offer = self._offer(offer_id, club_code)
        if offer.status != OfferStatus.ACTIVE:
            raise MarketError("Somente propostas ativas podem ser alteradas.")
        player = self._player(offer.player_id)
        if amount_cents < player.market_value_cents:
            raise MarketError("A proposta precisa atingir o valor-base do atleta.")
        team = self._team(club_code)
        delta = amount_cents - offer.amount_cents
        if delta > team.available_cents:
            raise MarketError("Saldo insuficiente para aumentar a proposta.")
        team.reserved_cents += delta
        offer.amount_cents = amount_cents
        return offer

    def cancel_offer(self, offer_id: str, club_code: str) -> Offer:
        offer = self._offer(offer_id, club_code)
        if offer.status != OfferStatus.ACTIVE:
            return offer
        self._team(club_code).reserved_cents -= offer.amount_cents
        offer.status = OfferStatus.CANCELLED
        return offer

    def resolve(self) -> dict[str, list[str]]:
        """Freeze offers and provisional rights without charging or moving players."""
        if self.resolved:
            return {club: list(team.roster) for club, team in self.teams.items()}
        viability = self.viable()
        if not viability.viable:
            raise MarketError("Mercado inviável: " + " ".join(viability.reasons))
        candidates = sorted((offer for offer in self.offers.values() if offer.status == OfferStatus.ACTIVE), key=lambda offer: (offer.player_id, -offer.amount_cents, offer.sequence))
        won: dict[str, list[Offer]] = {club: [] for club in self.teams}
        won_players: set[str] = set()
        for offer in candidates:
            if offer.player_id in won_players:
                offer.status = OfferStatus.LOST
                self._team(offer.club_code).reserved_cents -= offer.amount_cents
                continue
            won_players.add(offer.player_id)
            won[offer.club_code].append(offer)
        for club in self.teams:
            positional_capacity = {position: count + max(1, self.max_roster_size // 4) for position, count in self.slots.items()}
            positional_counts = {position: 0 for position in self.slots}
            for offer in sorted(won[club], key=lambda item: item.sequence):
                position = self._player(offer.player_id).position
                if len(self.commitments[club]) < self.max_roster_size and positional_counts[position] < positional_capacity[position]:
                    offer.status = OfferStatus.COMMITTED
                    self.commitments[club].append(offer.id)
                    positional_counts[position] += 1
                else:
                    offer.status = OfferStatus.EXCESS
                    self.excess_offers[club].append(offer.id)
        self.resolved = True
        return {club: list(team.roster) for club, team in self.teams.items()}

    @staticmethod
    def penalty_cents(amount_cents: int, percent: int) -> int:
        if amount_cents < 0 or percent not in {0, 2, 5, 10}:
            raise MarketError("Valor ou percentual de multa inválido.")
        return int((Decimal(amount_cents) * Decimal(percent) / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    def selection_preview(self, club_code: str, selected_offer_ids: list[str], penalty_percent: int | None = None) -> dict[str, object]:
        team = self._team(club_code)
        if not self.resolved or self.selection_complete:
            raise MarketError("A seleção do elenco não está aberta.")
        percent = self.penalty_percent if penalty_percent is None else penalty_percent
        if percent not in {0, 2, 5, 10}:
            raise MarketError("Percentual de multa inválido.")
        if len(selected_offer_ids) != len(set(selected_offer_ids)):
            raise MarketError("A seleção contém propostas duplicadas.")
        selected: list[Offer] = []
        for offer_id in selected_offer_ids:
            offer = self.offers.get(offer_id)
            if offer is None or offer.club_code != club_code or offer.status not in {OfferStatus.COMMITTED, OfferStatus.EXCESS}:
                raise MarketError("A seleção contém direito de contratação inválido.")
            selected.append(offer)
        if len(selected) > self.max_roster_size:
            raise MarketError(f"O elenco permite no máximo {self.max_roster_size} contratações nesta fase.")
        position_caps = {position: count + max(1, self.max_roster_size // 4) for position, count in self.slots.items()}
        counts = {position: 0 for position in self.slots}
        for offer in selected:
            counts[self._player(offer.player_id).position] += 1
        if any(counts[position] > position_caps[position] for position in counts):
            raise MarketError("A seleção excede a composição posicional máxima.")
        committed = [self.offers[offer_id] for offer_id in self.commitments[club_code]]
        selected_ids = set(selected_offer_ids)
        declined_committed = [offer for offer in committed if offer.id not in selected_ids]
        purchase_cents = sum(offer.amount_cents for offer in selected)
        penalties = [
            {"offer_id": offer.id, "player_id": offer.player_id, "amount_cents": offer.amount_cents, "penalty_cents": self.penalty_cents(offer.amount_cents, percent), "percent": percent, "reason": "Desistência voluntária de oferta compromissada"}
            for offer in declined_committed
        ]
        penalty_total = sum(int(item["penalty_cents"]) for item in penalties)
        reserved = sum(self.offers[offer_id].amount_cents for offer_id in [*self.commitments[club_code], *self.excess_offers[club_code]])
        debit = purchase_cents + penalty_total
        if debit > team.budget_cents or debit > reserved:
            raise MarketError("Saldo ou reserva insuficiente para confirmar essa seleção.")
        assigned = self._assigned_players()
        external_rights = {offer.player_id for offer in self.offers.values() if offer.club_code != club_code and offer.status in {OfferStatus.COMMITTED, OfferStatus.EXCESS}}
        selected_player_ids = {offer.player_id for offer in selected}
        origin_players = sorted((player for player in self.catalog.values() if player.club_code == club_code and player.id not in assigned and player.id not in selected_player_ids and player.id not in external_rights), key=lambda player: (player.position, player.id))
        final_counts = dict(counts)
        origin_starting: list[CatalogPlayer] = []
        for position, required in self.slots.items():
            need = max(0, required - final_counts[position])
            for player in [item for item in origin_players if item.position == position][:need]:
                if len(team.roster) + len(selected) + len(origin_starting) >= self.max_roster_size:
                    break
                origin_starting.append(player)
                final_counts[position] += 1
        missing_positions = {position: max(0, required - final_counts[position]) for position, required in self.slots.items()}
        missing_starters = sum(missing_positions.values())
        if len(team.roster) + len(selected) + len(origin_starting) + missing_starters > self.max_roster_size:
            raise MarketError("Essa seleção não deixa vagas para uma formação válida; remova algum atleta.")
        remaining_slots = self.max_roster_size - len(team.roster) - len(selected) - len(origin_starting)
        generic_starters = min(remaining_slots, missing_starters)
        bench_slots = remaining_slots - generic_starters
        origin_bench = [player for player in origin_players if player not in origin_starting][:bench_slots]
        generic_count = generic_starters + (bench_slots - len(origin_bench))
        return {
            "club_code": club_code, "selected_offer_ids": list(selected_offer_ids),
            "players": [{"offer_id": offer.id, "player": self._player(offer.player_id).model_dump(), "amount_cents": offer.amount_cents} for offer in selected],
            "purchase_cents": purchase_cents, "penalties": penalties, "penalty_cents": penalty_total,
            "reserved_release_cents": reserved - debit, "debit_cents": debit,
            "balance_after_cents": team.budget_cents - debit,
            "spent_after_cents": team.spent_cents + debit,
            "total_budget_cents": team.total_budget_cents,
            "generic_players_needed": generic_count,
            "missing_positions": missing_positions, "withdrawal_penalty_percent": percent,
        }

    def confirm_selection(self, club_code: str, selected_offer_ids: list[str], operation_id: str, *, automatic: bool = False) -> dict[str, object]:
        if club_code in self.confirmations:
            return self.confirmations[club_code]
        if operation_id in self.teams[club_code].paid_operation_ids:
            return self.confirmations.get(club_code, {"status": "COMPLETED", "operation_id": operation_id})
        preview = self.selection_preview(club_code, selected_offer_ids, 0 if automatic else None)
        team = self._team(club_code)
        selected_ids = set(selected_offer_ids)
        all_rights = [*self.commitments[club_code], *self.excess_offers[club_code]]
        reserved = sum(self.offers[offer_id].amount_cents for offer_id in all_rights)
        debit = int(preview["debit_cents"])
        if reserved > team.reserved_cents or debit > team.budget_cents:
            raise MarketError("As reservas ou o saldo mudaram; confirme a prévia novamente.")
        for offer_id in selected_offer_ids:
            offer = self.offers[offer_id]
            if offer.player_id in self._assigned_players():
                raise MarketError("O atleta já pertence a outro clube.")
        team.reserved_cents -= reserved
        for offer_id in selected_offer_ids:
            offer = self.offers[offer_id]
            offer.status = OfferStatus.CONFIRMED
            team.roster.append(offer.player_id)
            team.budget_cents -= offer.amount_cents
            team.spent_cents += offer.amount_cents
            transaction = {"operation_id": f"{operation_id}:purchase:{offer.id}", "type": "PURCHASE", "offer_id": offer.id, "player_id": offer.player_id, "club_code": club_code, "amount_cents": -offer.amount_cents, "balance_cents": team.budget_cents, "automatic": automatic, "offer_sequence": offer.sequence}
            self._record_transaction(team, transaction)
        penalty_by_offer = {str(item["offer_id"]): int(item["penalty_cents"]) for item in preview["penalties"]}
        for offer_id in all_rights:
            offer = self.offers[offer_id]
            if offer_id in selected_ids:
                continue
            penalty = penalty_by_offer.get(offer_id, 0)
            if penalty:
                penalty_operation = f"market:{operation_id}:offer:{offer.id}:voluntary-withdrawal"
                team.budget_cents -= penalty
                team.spent_cents += penalty
                transaction = {"operation_id": penalty_operation, "type": "WITHDRAWAL_PENALTY", "offer_id": offer.id, "player_id": offer.player_id, "club_code": club_code, "offer_amount_cents": offer.amount_cents, "percent": self.penalty_percent, "amount_cents": -penalty, "reason": "Desistência voluntária de oferta compromissada", "balance_cents": team.budget_cents, "automatic": False, "offer_sequence": offer.sequence}
                self._record_transaction(team, transaction)
            offer.status = OfferStatus.DECLINED
        team.paid_operation_ids.add(operation_id)
        result = {"status": "COMPLETED", "operation_id": operation_id, "selected_offer_ids": list(selected_offer_ids), "debit_cents": debit, "penalty_cents": int(preview["penalty_cents"]), "balance_cents": team.budget_cents, "automatic": automatic}
        self.confirmations[club_code] = result
        self.confirmed_clubs.add(club_code)
        return result

    def prepare_reassignment(self) -> None:
        if self.reassignment:
            return
        declined = [offer for offer in self.offers.values() if offer.status == OfferStatus.DECLINED]
        queues: list[dict[str, object]] = []
        for winner in sorted(declined, key=lambda offer: offer.sequence):
            alternatives = sorted(
                (offer for offer in self.offers.values() if offer.player_id == winner.player_id and offer.status == OfferStatus.LOST and offer.club_code != winner.club_code),
                key=lambda offer: (-offer.amount_cents, offer.sequence),
            )
            if alternatives:
                queues.append({"player_id": winner.player_id, "declined_offer_id": winner.id, "offer_ids": [offer.id for offer in alternatives], "cursor": 0, "status": "PENDING"})
        self.reassignment = queues

    def current_reassignment(self, human_clubs: set[str]) -> dict[str, object] | None:
        self.prepare_reassignment()
        for queue in self.reassignment:
            if queue["status"] != "PENDING":
                continue
            offer_ids = queue["offer_ids"]
            cursor = int(queue["cursor"])
            while cursor < len(offer_ids):
                offer = self.offers[str(offer_ids[cursor])]
                team = self._team(offer.club_code)
                if offer.amount_cents > team.available_cents or not self._can_add_and_complete_roster(team, offer.player_id):
                    offer.status = OfferStatus.EXPIRED
                    cursor += 1
                    queue["cursor"] = cursor
                    continue
                if offer.club_code in human_clubs:
                    offer.status = OfferStatus.REASSIGNMENT_AVAILABLE
                    queue["cursor"] = cursor
                    queue["current_offer_id"] = offer.id
                    queue["status"] = "WAITING"
                    return {"player_id": offer.player_id, "offer_id": offer.id, "club_code": offer.club_code, "amount_cents": offer.amount_cents, "player": self._player(offer.player_id).model_dump()}
                self._accept_reassignment(offer)
                queue["status"] = "COMPLETE"
                break
            else:
                queue["status"] = "EXHAUSTED"
        return None

    def respond_reassignment(self, club_code: str, offer_id: str, accept: bool, operation_id: str) -> dict[str, object]:
        if offer_id in self.reassignment_responses:
            previous = self.reassignment_responses[offer_id]
            if previous.get("club_code") != club_code:
                raise MarketError("Esta segunda oportunidade pertence a outro clube.")
            return previous
        queue = next((item for item in self.reassignment if item.get("status") == "WAITING" and item.get("current_offer_id") == offer_id), None)
        offer = self.offers.get(offer_id)
        if queue is None or offer is None or offer.club_code != club_code or offer.status != OfferStatus.REASSIGNMENT_AVAILABLE:
            raise MarketError("Esta segunda oportunidade não está disponível para este clube.")
        if accept:
            team = self._team(club_code)
            if offer.amount_cents > team.available_cents or not self._can_add_and_complete_roster(team, offer.player_id):
                offer.status = OfferStatus.EXPIRED
                queue["cursor"] = int(queue["cursor"]) + 1
                queue["status"] = "PENDING"
                result = {"status": "SKIPPED", "offer_id": offer_id, "club_code": club_code, "reason": "Saldo ou vaga insuficiente."}
                self.reassignment_responses[offer_id] = result
                return result
            self._accept_reassignment(offer, operation_id)
            queue["status"] = "COMPLETE"
            result = {"status": "ACCEPTED", "offer_id": offer_id, "club_code": club_code, "player_id": offer.player_id, "amount_cents": offer.amount_cents, "balance_cents": team.budget_cents}
            self.reassignment_responses[offer_id] = result
            return result
        offer.status = OfferStatus.DECLINED
        queue["cursor"] = int(queue["cursor"]) + 1
        queue["status"] = "PENDING"
        result = {"status": "DECLINED", "offer_id": offer_id, "club_code": club_code}
        self.reassignment_responses[offer_id] = result
        return result

    def _accept_reassignment(self, offer: Offer, operation_id: str | None = None) -> None:
        team = self._team(offer.club_code)
        if offer.player_id in self._assigned_players():
            raise MarketError("O atleta já pertence a outro clube.")
        if offer.amount_cents > team.available_cents or not self._can_add_and_complete_roster(team, offer.player_id):
            raise MarketError("Saldo ou vaga insuficiente para aceitar a segunda oportunidade.")
        team.budget_cents -= offer.amount_cents
        team.spent_cents += offer.amount_cents
        team.roster.append(offer.player_id)
        offer.status = OfferStatus.CONFIRMED
        operation = operation_id or f"reassignment:{offer.id}:{offer.club_code}"
        self._record_transaction(team, {"operation_id": operation, "type": "PURCHASE", "offer_id": offer.id, "player_id": offer.player_id, "club_code": offer.club_code, "amount_cents": -offer.amount_cents, "balance_cents": team.budget_cents, "reassignment": True, "automatic": operation_id is None, "offer_sequence": offer.sequence})

    def _can_add_and_complete_roster(self, team: TeamMarketState, player_id: str) -> bool:
        if player_id in self._assigned_players() or len(team.roster) >= self.max_roster_size:
            return False
        counts = {position: self._position_count(team, position) for position in self.slots}
        position = self._player(player_id).position
        counts[position] += 1
        roster_size = len(team.roster) + 1
        assigned = self._assigned_players()
        available_by_position: dict[str, int] = {key: 0 for key in self.slots}
        for player in self.catalog.values():
            if player.club_code == team.club_code and player.id not in assigned and player.id != player_id:
                available_by_position[player.position] += 1
        for position, required in self.slots.items():
            available = min(max(0, required - counts[position]), available_by_position[position])
            counts[position] += available
            roster_size += available
        missing_starters = sum(max(0, required - counts[position]) for position, required in self.slots.items())
        return roster_size + missing_starters <= self.max_roster_size

    def finalize_rosters(self, room_id: str) -> None:
        if self.selection_complete:
            return
        used = self._assigned_players()
        for club, team in self.teams.items():
            original = sorted((player for player in self.catalog.values() if player.club_code == club and player.id not in used), key=lambda player: (player.position, player.id))
            for position, required in self.slots.items():
                missing = max(0, required - self._position_count(team, position))
                for player in [item for item in original if item.position == position][:missing]:
                    if len(team.roster) >= self.max_roster_size:
                        break
                    team.roster.append(player.id)
                    used.add(player.id)
            # Leave room for any still-missing starter positions before filling
            # the bench with club-owned players.
            missing_starters = sum(max(0, required - self._position_count(team, position)) for position, required in self.slots.items())
            fill_limit = max(len(team.roster), self.max_roster_size - missing_starters)
            for player in original:
                if len(team.roster) >= fill_limit:
                    break
                if player.id not in used:
                    team.roster.append(player.id)
                    used.add(player.id)
            while len(team.roster) < self.max_roster_size:
                missing_positions = [position for position, required in self.slots.items() if self._position_count(team, position) < required]
                position = missing_positions[0] if missing_positions else tuple(self.slots)[(len(team.roster) % len(self.slots))]
                index = len(team.roster) + 1
                seed = sum((offset + 1) * ord(char) for offset, char in enumerate(f"{room_id}:{club}:{index}"))
                overall = 48 + seed % 13
                player_id = f"GEN-{room_id[:8]}-{club}-{index:02d}"
                while player_id in self.catalog:
                    player_id += "X"
                player = CatalogPlayer(id=player_id, name=f"Genérico {club} {index:02d}", club_code=club, age=18 + seed % 12, position=position, overall=overall, potential=min(76, overall + seed % 12), market_value_cents=0, source="synthetic-career", source_version="generated-v1")
                self.catalog[player_id] = player
                generated = player.model_dump(mode="json")
                self.generated_players[player_id] = generated
                team.roster.append(player_id)
                used.add(player_id)
        for team in self.teams.values():
            if any(self._position_count(team, position) < required for position, required in self.slots.items()):
                raise MarketError(f"Não foi possível completar as posições titulares de {team.club_code}.")
        if any(len(team.roster) != self.max_roster_size for team in self.teams.values()):
            raise MarketError("Não foi possível completar todos os elencos.")
        self.selection_complete = True
        self.review = sorted((dict(item) for item in self.transactions if item.get("type") == "PURCHASE"), key=lambda item: (int(item.get("offer_sequence", 0)), str(item.get("player_id", ""))))

    def _record_transaction(self, team: TeamMarketState, transaction: dict[str, object]) -> None:
        operation_id = str(transaction["operation_id"])
        if any(str(item.get("operation_id")) == operation_id for item in team.financial_ledger):
            return
        team.financial_ledger.append(transaction)
        team.paid_operation_ids.add(operation_id)
        if transaction["type"] == "PURCHASE":
            self.transactions.append(dict(transaction))

    def _fill_bots_and_unfilled_teams(self) -> None:
        used = self._assigned_players()
        for team in self.teams.values():
            for position, required in self.slots.items():
                missing = required - self._position_count(team, position)
                for player in self._available_for_position(position, used)[:missing]:
                    if player.market_value_cents > team.budget_cents:
                        raise MarketError(f"{team.club_code} não consegue financiar um elenco válido.")
                    team.roster.append(player.id)
                    team.budget_cents -= player.market_value_cents
                    used.add(player.id)
            if len(team.roster) != sum(self.slots.values()):
                raise MarketError(f"Não foi possível completar o elenco de {team.club_code}.")

    def _available_for_position(self, position: str, used: set[str]) -> list[CatalogPlayer]:
        return sorted((player for player in self.catalog.values() if player.position == position and player.id not in used), key=lambda player: (player.market_value_cents, -player.overall, player.id))

    def _has_position_capacity(self, team: TeamMarketState, position: str) -> bool:
        committed = self._position_count(team, position)
        active = sum(self._player(offer.player_id).position == position for offer in self.offers.values() if offer.club_code == team.club_code and offer.status == OfferStatus.ACTIVE)
        return committed + active < self.slots[position]

    def _has_roster_capacity(self, team: TeamMarketState, position: str) -> bool:
        return self._position_count(team, position) < self.slots[position]

    def _position_count(self, team: TeamMarketState, position: str) -> int:
        return sum(self._player(player_id).position == position for player_id in team.roster)

    def _assigned_players(self) -> set[str]:
        return {player_id for team in self.teams.values() for player_id in team.roster}

    def _team(self, club_code: str) -> TeamMarketState:
        if club_code not in self.teams:
            raise MarketError("Clube não participa deste mercado.")
        return self.teams[club_code]

    def _player(self, player_id: str) -> CatalogPlayer:
        if player_id not in self.catalog:
            raise MarketError("Atleta não encontrado no catálogo.")
        return self.catalog[player_id]

    def _offer(self, offer_id: str, club_code: str) -> Offer:
        if offer_id not in self.offers or self.offers[offer_id].club_code != club_code:
            raise MarketError("Proposta não encontrada para este clube.")
        return self.offers[offer_id]


class MarketRegistry:
    """One market and one authoritative async lock per room in this MVP process."""

    def __init__(self) -> None:
        self._markets: dict[str, InitialMarket] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def create(self, room_id: str, catalog: PlayerCatalog, mode: str, teams: dict[str, int]) -> InitialMarket:
        if room_id in self._markets:
            return self._markets[room_id]
        market = InitialMarket(catalog, mode, teams)
        viability = market.viable()
        if not viability.viable:
            raise MarketError("Mercado inviável: " + " ".join(viability.reasons))
        self._markets[room_id] = market
        self._locks[room_id] = asyncio.Lock()
        return market

    async def submit_offer(self, room_id: str, club_code: str, player_id: str, amount_cents: int, idempotency_key: str) -> Offer:
        if room_id not in self._markets:
            raise MarketError("Mercado não iniciado para esta sala.")
        async with self._locks[room_id]:
            return self._markets[room_id].submit_offer(club_code, player_id, amount_cents, idempotency_key)

    async def resolve(self, room_id: str) -> dict[str, list[str]]:
        if room_id not in self._markets:
            raise MarketError("Mercado não iniciado para esta sala.")
        async with self._locks[room_id]:
            return self._markets[room_id].resolve()
