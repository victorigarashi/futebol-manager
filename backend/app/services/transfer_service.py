"""Atomic transfers, cash purchases and one-season loans for the transfer windows.

Windows: after the middle of the league (round 19 of 38) and between seasons (the
pre-season window of the next season). Integrity rules, all checked under the room
lock: a player is in exactly one roster; cash is reserved by pending offers so
simultaneous bids cannot overspend; rosters stay between the minimum (starters + 2)
and the maximum of the mode; an expired or failed offer can never be accepted.

Loans (traditional career only): ownership and the club the player plays for are
tracked separately. The player moves to the borrower's roster for the season and
returns automatically when the next season is created; development keeps applying
to the player wherever he plays.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import asdict, dataclass

from app.domain.bot_coach import choose_lineup
from app.domain.custom_players import (
    MAX_PER_CLUB,
    CustomPlayerSpec,
    build_custom_player,
    custom_player_id,
)
from app.domain.market import InitialMarket, MarketError
from app.services.market_service import market_service
from app.services.season_service import season_service
from app.services.squad_service import squad_service


@dataclass
class TransferOffer:
    id: str
    idempotency_key: str
    buyer_club: str
    seller_club: str
    incoming_player_id: str
    offered_player_id: str
    amount_cents: int
    status: str = "PENDING"
    counter_cents: int | None = None
    # TRADE (player + cash), PURCHASE (cash only) or LOAN (fee for one season).
    kind: str = "TRADE"
    expires_at: float | None = None
    origin: str = "HUMAN"  # HUMAN or BOT (who sent it)
    reason: str | None = None

OFFER_TTL_SECONDS = 600
OPEN_STATUSES = {"PENDING", "COUNTERED"}
STATUSES = {"PENDING", "COUNTERED", "ACCEPTED", "REJECTED", "CANCELLED", "BOT_REJECTED", "EXPIRED", "FAILED"}


class TransferService:
    def __init__(self, clock=time.time) -> None:
        self.clock = clock
        # room -> player id -> {"owner", "holder", "season", "fee_cents"}
        self._loans: dict[str, dict[str, dict[str, object]]] = {}
        self._offers: dict[str, dict[str, TransferOffer]] = {}
        self._operations: dict[str, set[str]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._listings: dict[str, set[str]] = {}

    def _lock(self, room_id: str) -> asyncio.Lock:
        return self._locks.setdefault(room_id, asyncio.Lock())

    def _market(self, room_id: str) -> InitialMarket:
        if not season_service._season(room_id).transfer_window_open:
            raise MarketError("A janela de transferências está fechada.")
        return market_service._session(room_id).market

    def _reserved_offer_cents(self, room_id: str, club: str, *, exclude_offer: str | None = None) -> int:
        """Count pending cash commitments so simultaneous bids cannot overspend."""
        return sum(
            offer.amount_cents
            for offer in self._offers.get(room_id, {}).values()
            if offer.buyer_club == club
            and offer.id != exclude_offer
            and offer.status in OPEN_STATUSES
        )

    # ------------------------------------------------------------------ rules
    @staticmethod
    def roster_limits(market: InitialMarket) -> tuple[int, int]:
        starters = 11 if market.mode == "ELEVEN_A_SIDE" else 5
        return starters + 2, market.max_roster_size

    def loans(self, room_id: str) -> dict[str, dict[str, object]]:
        return self._loans.setdefault(room_id, {})

    def _expire(self, room_id: str) -> None:
        now = self.clock()
        for offer in self._offers.get(room_id, {}).values():
            if offer.status in OPEN_STATUSES and offer.expires_at is not None and now >= offer.expires_at:
                offer.status, offer.reason = "EXPIRED", "Prazo da proposta encerrado."

    def market_value(self, room_id: str, market: InitialMarket, player_id: str) -> int:
        """Dynamic value: development value x current-season form x demand (open offers)."""
        season = season_service._season(room_id)
        player = market.catalog[player_id]
        latest = next((record for record in reversed(season.development_records) if record["player_id"] == player_id), None)
        base = int(latest["internal_market_value_cents"]) if latest else int(player.market_value_cents)
        ratings = [p["rating"] for match in season.matches.values() for side in ("home", "away")
                   for p in (match.get("lineups") or {}).get(side, []) if p.get("id") == player_id and p.get("entered_tick") is not None
                   and isinstance(p.get("rating"), (int, float))]
        form = 1.0 if len(ratings) < 3 else max(0.85, min(1.25, 1 + (sum(ratings) / len(ratings) - 6.5) * 0.08))
        demand = sum(1 for o in self._offers.get(room_id, {}).values() if o.incoming_player_id == player_id and o.status in OPEN_STATUSES)
        return int(base * form * min(1.2, 1 + 0.05 * demand))

    def _ensure_offer_fits(self, room_id: str, market: InitialMarket, club: str, amount_cents: int, *, exclude_offer: str | None = None) -> None:
        team = market.teams[club]
        available = team.available_cents - self._reserved_offer_cents(room_id, club, exclude_offer=exclude_offer)
        if amount_cents < 0 or amount_cents > available:
            raise MarketError("Saldo insuficiente após considerar as propostas pendentes.")

    async def set_listing(self, room_id: str, club: str, player_id: str, listed: bool) -> dict[str, object]:
        async with self._lock(room_id):
            market = self._market(room_id)
            if player_id not in market.teams[club].roster:
                raise MarketError("O atleta não pertence ao seu clube.")
            listings = self._listings.setdefault(room_id, set())
            if listed:
                listings.add(player_id)
            else:
                listings.discard(player_id)
            return {"player_id": player_id, "listed": listed}

    async def close_window(self, room_id: str) -> None:
        async with self._lock(room_id):
            for offer in self._offers.get(room_id, {}).values():
                if offer.status in OPEN_STATUSES:
                    offer.status, offer.reason = "CANCELLED", "A janela de transferências foi encerrada."
            self._listings.pop(room_id, None)

    async def end_loans(self, room_id: str) -> list[dict[str, object]]:
        """Season over: every loaned player goes back to the club that owns him."""
        async with self._lock(room_id):
            market = market_service._session(room_id).market
            returned = []
            for player_id, loan in sorted(self.loans(room_id).items()):
                holder, owner = market.teams[str(loan["holder"])], market.teams[str(loan["owner"])]
                if player_id in holder.roster:
                    holder.roster.remove(player_id)
                if player_id not in owner.roster:
                    owner.roster.append(player_id)
                returned.append({"player_id": player_id, "owner": loan["owner"], "holder": loan["holder"]})
            self._loans[room_id] = {}
            return returned

    def player_view(self, room_id: str, market: InitialMarket, player_id: str) -> dict[str, object]:
        player = market.catalog[player_id]
        season = season_service._season(room_id)
        overall = season.current_overalls.get(player_id, player.overall)
        latest = next((record for record in reversed(season.development_records) if record["player_id"] == player_id), None)
        loan = self.loans(room_id).get(player_id)
        return {**player.model_dump(), "overall": overall, "base_overall": player.overall,
                "overall_delta": overall - player.overall,
                "internal_market_value_cents": latest["internal_market_value_cents"] if latest else player.market_value_cents,
                "market_value_cents": self.market_value(room_id, market, player_id),
                "loan": dict(loan) if loan else None,
                "for_sale": player_id in self._listings.get(room_id, set())}

    def career(self, room_id: str, club: str) -> dict[str, object]:
        market = market_service._session(room_id).market
        season = season_service._season(room_id)
        team = market.teams[club]
        reserved = self._reserved_offer_cents(room_id, club)
        return {"club_code": club, "season_number": season.season_number,
                "budget_cents": team.budget_cents, "reserved_transfer_cents": reserved,
                "available_transfer_cents": max(0, team.available_cents - reserved),
                "financial_ledger": list(team.financial_ledger), "transfers": self.view_for(room_id, club),
                "development_records": [record for record in season.development_records if record["player_id"] in team.roster],
                "season_history": season.season_history,
                "players": [self.player_view(room_id, market, player_id) for player_id in team.roster]}

    def available_players(self, room_id: str) -> list[dict[str, object]]:
        market = self._market(room_id)
        owned = {player_id for team in market.teams.values() for player_id in team.roster}
        return [self.player_view(room_id, market, player.id) for player in market.catalog.values() if player.id not in owned]

    def club_rosters(self, room_id: str, exclude_club: str) -> list[dict[str, object]]:
        market = self._market(room_id)
        return [{"club_code": club, "players": [self.player_view(room_id, market, player_id) for player_id in team.roster]} for club, team in market.teams.items() if club != exclude_club]

    async def buy_available(self, room_id: str, club: str, incoming_id: str, replace_id: str, amount_cents: int, operation_id: str) -> dict[str, object]:
        async with self._lock(room_id):
            market = self._market(room_id)
            operations = self._operations.setdefault(room_id, set())
            scoped_operation = f"{club}:{operation_id}"
            if scoped_operation in operations:
                return {"status": "COMPLETED", "operation_id": operation_id}
            team = market.teams.get(club)
            if team is None or replace_id not in team.roster:
                raise MarketError("O atleta de saída não pertence ao seu clube.")
            owned = {player_id for current in market.teams.values() for player_id in current.roster}
            if incoming_id in owned or incoming_id not in market.catalog:
                raise MarketError("Atleta disponível não encontrado.")
            incoming, outgoing = market.catalog[incoming_id], market.catalog[replace_id]
            if incoming.position != outgoing.position:
                raise MarketError("A troca precisa preservar a posição da escalação.")
            cost = max(amount_cents, int(self.player_view(room_id, market, incoming_id)["internal_market_value_cents"]))
            if cost <= 0:
                raise MarketError("Valor de contratação inválido.")
            self._ensure_offer_fits(room_id, market, club, cost)
            if cost > team.available_cents:
                raise MarketError("Saldo insuficiente para esta contratação.")
            lineup = squad_service.prepare_replacement(room_id, club, replace_id, incoming_id, market)
            index = team.roster.index(replace_id)
            team.roster[index] = incoming_id
            team.budget_cents -= cost
            team.financial_ledger.append({"operation_id": operation_id, "type": "PURCHASE", "amount_cents": -cost, "player_id": incoming_id, "released_player_id": replace_id})
            if lineup:
                squad_service.commit_lineup(room_id, club, lineup)
            operations.add(scoped_operation)
            self._listings.get(room_id, set()).discard(replace_id)
            return {"status": "COMPLETED", "operation_id": operation_id, "club_code": club, "incoming_player_id": incoming_id, "released_player_id": replace_id, "amount_cents": cost, "balance_cents": team.budget_cents}

    def _roster_editable_market(self, room_id: str) -> InitialMarket:
        """Squads may change while the transfer window is open, or in the pre-season of the first
        season (no match played, no round live): when the coaches build their teams."""
        season = season_service._season(room_id)
        preseason = not season.live_round and not season.matches and not season.state.results
        if not (season.transfer_window_open or preseason):
            raise MarketError("Jogadores personalizados só podem ser criados na pré-temporada ou com a janela de transferências aberta.")
        return market_service._session(room_id).market

    async def create_custom_player(self, room_id: str, club: str, spec: CustomPlayerSpec, replace_id: str, operation_id: str) -> dict[str, object]:
        """A coach's created athlete joins his club in place of one of the same position (squad
        size and balance unchanged; the released athlete becomes a free agent). Idempotent."""
        async with self._lock(room_id):
            market = self._roster_editable_market(room_id)
            operations = self._operations.setdefault(room_id, set())
            scoped_operation = f"{club}:custom:{operation_id}"
            team = market.teams.get(club)
            if team is None:
                raise MarketError("Clube não encontrado.")
            created = sorted(pid for pid in market.generated_players if pid.startswith(f"CUS-{room_id[:8]}-{club}-"))
            if scoped_operation in operations:
                existing = next((pid for pid in created if market.generated_players[pid].get("_operation") == scoped_operation), None)
                return {"status": "COMPLETED", "operation_id": operation_id, "player": self.player_view(room_id, market, existing) if existing else None}
            if replace_id not in team.roster:
                raise MarketError("O atleta de saída não pertence ao seu clube.")
            if replace_id in self.loans(room_id):
                raise MarketError("Atleta emprestado não pode ser substituído.")
            if sum(1 for pid in team.roster if pid in created) >= MAX_PER_CLUB:
                raise MarketError(f"Cada clube pode ter no máximo {MAX_PER_CLUB} jogadores personalizados no elenco.")
            if market.catalog[replace_id].position != spec.position:
                raise MarketError("O jogador criado precisa ter a mesma posição do atleta que sai (equilíbrio do elenco).")
            sequence = len(created) + 1
            player_id = custom_player_id(room_id, club, sequence)
            while player_id in market.catalog:
                sequence += 1
                player_id = custom_player_id(room_id, club, sequence)
            player = build_custom_player(spec, club, player_id)
            market.catalog[player_id] = player
            lineup = squad_service.prepare_replacement(room_id, club, replace_id, player_id, market)
            team.roster[team.roster.index(replace_id)] = player_id
            market.generated_players[player_id] = {**player.model_dump(mode="json"), "_operation": scoped_operation}
            team.financial_ledger.append({"operation_id": f"{room_id}:{scoped_operation}", "type": "CUSTOM_PLAYER", "amount_cents": 0,
                                          "player_id": player_id, "released_player_id": replace_id})
            if lineup:
                squad_service.commit_lineup(room_id, club, lineup)
            operations.add(scoped_operation)
            self._listings.get(room_id, set()).discard(replace_id)
            return {"status": "COMPLETED", "operation_id": operation_id, "released_player_id": replace_id, "player": self.player_view(room_id, market, player_id)}

    async def create_offer(self, room_id: str, buyer: str, incoming_id: str, offered_id: str, amount_cents: int, idempotency_key: str,
                           human_clubs: set[str], kind: str = "TRADE", origin: str = "HUMAN") -> TransferOffer:
        async with self._lock(room_id):
            return self._create_offer(room_id, buyer, incoming_id, offered_id, amount_cents, idempotency_key, human_clubs, kind, origin)

    def _create_offer(self, room_id: str, buyer: str, incoming_id: str, offered_id: str, amount_cents: int, idempotency_key: str,
                      human_clubs: set[str], kind: str = "TRADE", origin: str = "HUMAN") -> TransferOffer:
        market = self._market(room_id)
        self._expire(room_id)
        existing = next((offer for offer in self._offers.get(room_id, {}).values() if offer.buyer_club == buyer and offer.idempotency_key == idempotency_key), None)
        if existing:
            return existing
        if buyer not in market.teams:
            raise MarketError("Clube comprador não encontrado.")
        seller = next((code for code, team in market.teams.items() if incoming_id in team.roster), None)
        if seller is None or seller == buyer:
            raise MarketError("O atleta alvo não pertence a outro clube.")
        loans = self.loans(room_id)
        if incoming_id in loans or (offered_id and offered_id in loans):
            raise MarketError("Atleta emprestado não pode ser negociado até voltar ao clube de origem.")
        minimum, maximum = self.roster_limits(market)
        if kind == "LOAN":
            if str(season_service._season(room_id).rules.get("game_mode", "TRADITIONAL")) != "TRADITIONAL":
                raise MarketError("Empréstimos existem apenas no Modo Carreira Tradicional.")
            offered_id = ""
        if kind in {"LOAN", "PURCHASE"} or not offered_id:
            kind = "LOAN" if kind == "LOAN" else "PURCHASE"
            offered_id = ""
            if len(market.teams[seller].roster) - 1 < minimum:
                raise MarketError("O clube vendedor ficaria abaixo do elenco mínimo.")
            if len(market.teams[buyer].roster) + 1 > maximum:
                raise MarketError("Seu elenco já está no tamanho máximo: ofereça um atleta na troca.")
        else:
            kind = "TRADE"
            if offered_id not in market.teams[buyer].roster:
                raise MarketError("O atleta oferecido não pertence ao seu clube.")
            if market.catalog[incoming_id].position != market.catalog[offered_id].position:
                raise MarketError("A negociação deve preservar as posições dos dois elencos.")
        if kind == "PURCHASE" and amount_cents <= 0:
            raise MarketError("Uma compra em dinheiro precisa de valor positivo.")
        self._ensure_offer_fits(room_id, market, buyer, amount_cents)
        offer = TransferOffer(f"transfer-{len(self._offers.get(room_id, {})) + 1}", idempotency_key, buyer, seller, incoming_id,
                              offered_id, amount_cents, kind=kind, expires_at=self.clock() + OFFER_TTL_SECONDS, origin=origin)
        self._offers.setdefault(room_id, {})[offer.id] = offer
        if seller not in human_clubs:
            self._decide_bot(room_id, market, offer)
        return offer

    async def accept(self, room_id: str, offer_id: str, actor: str) -> TransferOffer:
        async with self._lock(room_id):
            market = self._market(room_id)
            offer = self._offer(room_id, offer_id)
            if actor not in {offer.seller_club, offer.buyer_club}:
                raise MarketError("Você não participa desta negociação.")
            if offer.status == "ACCEPTED":
                return offer
            self._expire(room_id)
            if offer.status == "EXPIRED":
                raise MarketError("O prazo desta proposta terminou.")
            recipient = offer.buyer_club if offer.status == "COUNTERED" else offer.seller_club
            if actor != recipient:
                raise MarketError("Somente quem recebeu a proposta pode aceitá-la.")
            if offer.status not in {"PENDING", "COUNTERED"}:
                raise MarketError("Esta proposta já foi encerrada.")
            self._commit(room_id, market, offer)
            offer.status = "ACCEPTED"
            return offer

    async def reject(self, room_id: str, offer_id: str, actor: str) -> TransferOffer:
        async with self._lock(room_id):
            self._market(room_id)
            offer = self._offer(room_id, offer_id)
            if actor not in {offer.buyer_club, offer.seller_club}:
                raise MarketError("Você não participa desta negociação.")
            if offer.status in OPEN_STATUSES:
                offer.status = "REJECTED"
            return offer

    async def counter(self, room_id: str, offer_id: str, seller: str, amount_cents: int) -> TransferOffer:
        async with self._lock(room_id):
            market = self._market(room_id)
            offer = self._offer(room_id, offer_id)
            self._expire(room_id)
            if seller != offer.seller_club or offer.status != "PENDING" or amount_cents <= offer.amount_cents:
                raise MarketError("Contraproposta inválida para esta negociação.")
            self._ensure_offer_fits(room_id, market, offer.buyer_club, amount_cents, exclude_offer=offer.id)
            offer.amount_cents = amount_cents
            offer.counter_cents = amount_cents
            offer.status = "COUNTERED"
            if offer.origin == "BOT":
                self._bot_answers_counter(room_id, market, offer)
            return offer

    def _bot_answers_counter(self, room_id: str, market: InitialMarket, offer: TransferOffer) -> None:
        """A bot buyer accepts a counter-offer up to its own ceiling, otherwise walks away."""
        difficulty = str(season_service._season(room_id).rules.get("bot_difficulty", "COMPETITIVE"))
        value = self.market_value(room_id, market, offer.incoming_player_id)
        if offer.kind == "LOAN":
            ceiling = value * {"CASUAL": 0.15, "COMPETITIVE": 0.12, "LEGENDARY": 0.10}[difficulty]
        else:
            offered = self.market_value(room_id, market, offer.offered_player_id) if offer.offered_player_id else 0
            ceiling = value * {"CASUAL": 1.25, "COMPETITIVE": 1.15, "LEGENDARY": 1.08}[difficulty] - offered
        if offer.amount_cents <= ceiling:
            try:
                self._commit(room_id, market, offer)
                offer.status = "ACCEPTED"
                return
            except MarketError as error:
                offer.status, offer.reason = "FAILED", str(error)
                return
        offer.status, offer.reason = "REJECTED", "O clube desistiu: valor acima do limite."

    async def cancel(self, room_id: str, offer_id: str, buyer: str) -> TransferOffer:
        async with self._lock(room_id):
            self._market(room_id)
            offer = self._offer(room_id, offer_id)
            if buyer != offer.buyer_club:
                raise MarketError("Somente quem enviou pode cancelar a proposta.")
            if offer.status in OPEN_STATUSES:
                offer.status = "CANCELLED"
            return offer

    def view_for(self, room_id: str, club: str) -> list[dict[str, object]]:
        self._expire(room_id)
        return [asdict(offer) for offer in self._offers.get(room_id, {}).values() if club in {offer.buyer_club, offer.seller_club}]

    @staticmethod
    def _offer_view(offer: TransferOffer) -> dict[str, object]:
        return asdict(offer)

    def export_room(self, room_id: str) -> dict[str, object]:
        return {"offers": [asdict(offer) for offer in self._offers.get(room_id, {}).values()], "operations": sorted(self._operations.get(room_id, set())),
                "listings": sorted(self._listings.get(room_id, set())), "loans": self.loans(room_id)}

    def restore_room(self, room_id: str, payload: dict[str, object]) -> None:
        offers = {}
        for raw in payload.get("offers", []):
            offer = TransferOffer(**raw)
            if offer.status not in STATUSES or offer.kind not in {"TRADE", "PURCHASE", "LOAN"}:
                raise ValueError("Snapshot contém estado de negociação desconhecido.")
            offers[offer.id] = offer
        self._offers[room_id] = offers
        self._operations[room_id] = set(map(str, payload.get("operations", [])))
        self._locks.setdefault(room_id, asyncio.Lock())
        self._listings[room_id] = set(map(str, payload.get("listings", [])))
        loans = payload.get("loans", {})
        if not isinstance(loans, dict) or any(not isinstance(v, dict) or not {"owner", "holder"}.issubset(v) for v in loans.values()):
            raise ValueError("Snapshot contém empréstimo inválido.")
        self._loans[room_id] = {str(k): dict(v) for k, v in loans.items()}

    def _offer(self, room_id: str, offer_id: str) -> TransferOffer:
        try:
            return self._offers[room_id][offer_id]
        except KeyError as error:
            raise MarketError("Proposta de transferência não encontrada.") from error

    def _commit(self, room_id: str, market: InitialMarket, offer: TransferOffer) -> None:
        if offer.kind == "TRADE":
            self._commit_trade(room_id, market, offer)
        else:
            self._commit_move(room_id, market, offer)
        # Every other open offer for the players that just moved can no longer happen.
        moved = {offer.incoming_player_id, offer.offered_player_id} - {""}
        for other in self._offers.get(room_id, {}).values():
            if other is not offer and other.status in OPEN_STATUSES and moved & {other.incoming_player_id, other.offered_player_id}:
                other.status, other.reason = "FAILED", "Negociação fracassou: o atleta acabou de ser negociado."

    def _commit_move(self, room_id: str, market: InitialMarket, offer: TransferOffer) -> None:
        """Cash purchase or loan: one player changes roster, money goes to the seller."""
        buyer, seller = market.teams[offer.buyer_club], market.teams[offer.seller_club]
        minimum, maximum = self.roster_limits(market)
        if offer.incoming_player_id not in seller.roster:
            raise MarketError("Os elencos mudaram e esta proposta não pode mais ser aceita.")
        if len(seller.roster) - 1 < minimum or len(buyer.roster) + 1 > maximum:
            raise MarketError("A negociação deixaria um elenco fora dos limites.")
        self._ensure_offer_fits(room_id, market, offer.buyer_club, offer.amount_cents, exclude_offer=offer.id)
        seller.roster.remove(offer.incoming_player_id)
        buyer.roster.append(offer.incoming_player_id)
        buyer.budget_cents -= offer.amount_cents
        seller.budget_cents += offer.amount_cents
        operation_id = f"{room_id}:{offer.id}:accepted"
        kind = "LOAN_FEE" if offer.kind == "LOAN" else "TRANSFER"
        buyer.financial_ledger.append({"operation_id": operation_id, "type": kind, "amount_cents": -offer.amount_cents, "player_id": offer.incoming_player_id})
        seller.financial_ledger.append({"operation_id": operation_id, "type": kind, "amount_cents": offer.amount_cents, "player_id": offer.incoming_player_id})
        buyer.paid_operation_ids.add(operation_id)
        seller.paid_operation_ids.add(operation_id)
        if offer.kind == "LOAN":
            self.loans(room_id)[offer.incoming_player_id] = {"owner": offer.seller_club, "holder": offer.buyer_club,
                                                              "season": season_service._season(room_id).season_number,
                                                              "fee_cents": offer.amount_cents}
        self._listings.get(room_id, set()).discard(offer.incoming_player_id)
        # The seller's saved line-up may contain the player: it is rebuilt automatically.
        lineup = squad_service.lineup_for(room_id, offer.seller_club)
        if lineup and offer.incoming_player_id in dict(lineup["assignments"]).values():
            squad_service.drop_lineup(room_id, offer.seller_club)

    def _commit_trade(self, room_id: str, market: InitialMarket, offer: TransferOffer) -> None:
        buyer, seller = market.teams[offer.buyer_club], market.teams[offer.seller_club]
        if offer.incoming_player_id not in seller.roster or offer.offered_player_id not in buyer.roster:
            raise MarketError("Os elencos mudaram e esta proposta não pode mais ser aceita.")
        self._ensure_offer_fits(room_id, market, offer.buyer_club, offer.amount_cents, exclude_offer=offer.id)
        buyer_lineup = squad_service.prepare_replacement(room_id, offer.buyer_club, offer.offered_player_id, offer.incoming_player_id, market)
        seller_lineup = squad_service.prepare_replacement(room_id, offer.seller_club, offer.incoming_player_id, offer.offered_player_id, market)
        buyer_index, seller_index = buyer.roster.index(offer.offered_player_id), seller.roster.index(offer.incoming_player_id)
        buyer.roster[buyer_index], seller.roster[seller_index] = offer.incoming_player_id, offer.offered_player_id
        buyer.budget_cents -= offer.amount_cents
        seller.budget_cents += offer.amount_cents
        operation_id = f"{room_id}:{offer.id}:accepted"
        buyer.financial_ledger.append({"operation_id": operation_id, "type": "TRANSFER", "amount_cents": -offer.amount_cents, "player_id": offer.incoming_player_id})
        seller.financial_ledger.append({"operation_id": operation_id, "type": "TRANSFER", "amount_cents": offer.amount_cents, "player_id": offer.offered_player_id})
        buyer.paid_operation_ids.add(operation_id)
        seller.paid_operation_ids.add(operation_id)
        self._listings.get(room_id, set()).difference_update({offer.incoming_player_id, offer.offered_player_id})
        if buyer_lineup:
            squad_service.commit_lineup(room_id, offer.buyer_club, buyer_lineup)
        if seller_lineup:
            squad_service.commit_lineup(room_id, offer.seller_club, seller_lineup)

    def _decide_bot(self, room_id: str, market: InitialMarket, offer: TransferOffer) -> None:
        """A bot seller answers at once: accept, counter or refuse, by value and squad need.

        Harder bots sell their starters only at a premium and counter closer to value."""
        difficulty = str(season_service._season(room_id).rules.get("bot_difficulty", "COMPETITIVE"))
        target_value = self.market_value(room_id, market, offer.incoming_player_id)
        seller_roster = [market.catalog[pid] for pid in market.teams[offer.seller_club].roster]
        overalls = season_service._season(room_id).current_overalls
        _, starters = choose_lineup(market.mode, seller_roster, overalls)
        is_starter = offer.incoming_player_id in starters.values()
        if offer.kind == "LOAN":
            fee_floor = target_value * {"CASUAL": 0.06, "COMPETITIVE": 0.08, "LEGENDARY": 0.10}[difficulty]
            if is_starter or offer.amount_cents < fee_floor:
                offer.status, offer.reason = "BOT_REJECTED", "O clube não libera este atleta por empréstimo."
                return
            self._commit(room_id, market, offer)
            offer.status = "ACCEPTED"
            return
        offered_value = self.market_value(room_id, market, offer.offered_player_id) if offer.offered_player_id else 0
        premium = {"CASUAL": 0.0, "COMPETITIVE": 0.05, "LEGENDARY": 0.12}[difficulty] + (0.15 if is_starter else 0.0)
        asked = int(target_value * (1 + premium))
        value_delta = offered_value + offer.amount_cents - asked
        seed = int(hashlib.sha256(f"{offer.idempotency_key}:{offer.seller_club}".encode()).hexdigest()[:8], 16)
        tolerance = int.from_bytes(hashlib.sha256(str(seed).encode()).digest()[:4], "big") % max(1, target_value // 12 + 1)
        if difficulty == "LEGENDARY":
            tolerance //= 3
        if value_delta >= -tolerance:
            try:
                self._commit(room_id, market, offer)
                offer.status = "ACCEPTED"
            except MarketError as error:
                offer.status, offer.reason = "FAILED", str(error)
        elif value_delta >= -asked // 4:
            counter = max(offer.amount_cents + 1, asked - offered_value)
            try:
                self._ensure_offer_fits(room_id, market, offer.buyer_club, counter, exclude_offer=offer.id)
            except MarketError:
                offer.status, offer.reason = "BOT_REJECTED", "O comprador não tem saldo para o valor pedido."
                return
            offer.amount_cents = counter
            offer.counter_cents = counter
            offer.status = "COUNTERED"
            if offer.origin == "BOT":
                self._bot_answers_counter(room_id, market, offer)
        else:
            offer.status, offer.reason = "BOT_REJECTED", "Proposta muito abaixo do valor do atleta."

    # ------------------------------------------------------------------ bots take the initiative
    async def bot_window_activity(self, room_id: str, human_clubs: set[str]) -> list[TransferOffer]:
        """Bots look for reinforcements when a window opens: proposals to humans (who
        answer in the window) and to other bots (answered at once). Deterministic."""
        async with self._lock(room_id):
            market = self._market(room_id)
            season = season_service._season(room_id)
            difficulty = str(season.rules.get("bot_difficulty", "COMPETITIVE"))
            overalls = season.current_overalls
            per_bot = {"CASUAL": 1, "COMPETITIVE": 2, "LEGENDARY": 3}[difficulty]
            stretch = {"CASUAL": 0.45, "COMPETITIVE": 0.6, "LEGENDARY": 0.8}[difficulty]
            bid = {"CASUAL": 0.92, "COMPETITIVE": 1.0, "LEGENDARY": 1.08}[difficulty]
            sent: list[TransferOffer] = []
            minimum, maximum = self.roster_limits(market)
            for club in sorted(c for c in market.teams if c not in human_clubs):
                team = market.teams[club]
                roster = [market.catalog[pid] for pid in team.roster]
                if len(roster) < minimum:
                    continue
                _, assignments = choose_lineup(market.mode, roster, overalls)
                starters = [market.catalog[pid] for pid in assignments.values()]
                # Weakest starting positions first: that is where a reinforcement matters.
                needs = sorted(starters, key=lambda p: overalls.get(p.id, p.overall))
                tag = f"bot-{season.season_number}-{season_service.current_round(room_id)}"
                made = 0
                for weak in needs:
                    if made >= per_bot:
                        break
                    floor = overalls.get(weak.id, weak.overall) + (1 if difficulty == "LEGENDARY" else 2)
                    budget = (team.available_cents - self._reserved_offer_cents(room_id, club)) * stretch
                    candidates = []
                    for other, other_team in market.teams.items():
                        if other == club:
                            continue
                        for pid in other_team.roster:
                            player = market.catalog[pid]
                            if player.position != weak.position or pid in self.loans(room_id):
                                continue
                            rating = overalls.get(pid, player.overall)
                            if rating < floor:
                                continue
                            value = self.market_value(room_id, market, pid)
                            candidates.append((rating * 1_000_000_000 - value, pid, other, value))
                    candidates.sort(reverse=True)
                    for _, pid, _other, value in candidates:
                        price = int(value * bid)
                        if len(team.roster) < maximum and price <= budget:
                            args = (pid, "", price, "PURCHASE")
                        elif price - self.market_value(room_id, market, weak.id) <= budget:
                            args = (pid, weak.id, max(0, price - self.market_value(room_id, market, weak.id)), "TRADE")
                        elif str(season.rules.get("game_mode", "TRADITIONAL")) == "TRADITIONAL" and len(team.roster) < maximum and value * 0.1 <= budget:
                            args = (pid, "", int(value * 0.1), "LOAN")
                        else:
                            continue
                        try:
                            offer = self._create_offer(room_id, club, args[0], args[1], args[2], f"{tag}-{club}-{pid}",
                                                       human_clubs, args[3], origin="BOT")
                        except MarketError:
                            continue
                        sent.append(offer)
                        made += 1
                        break
            return sent


transfer_service = TransferService()
