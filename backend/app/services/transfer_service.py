"""Atomic, position-preserving transfers for the midseason window."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import asdict, dataclass

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


class TransferService:
    def __init__(self) -> None:
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
            and offer.status in {"PENDING", "COUNTERED"}
        )

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
                if offer.status in {"PENDING", "COUNTERED"}:
                    offer.status = "CANCELLED"
            self._listings.pop(room_id, None)

    def player_view(self, room_id: str, market: InitialMarket, player_id: str) -> dict[str, object]:
        player = market.catalog[player_id]
        season = season_service._season(room_id)
        overall = season.current_overalls.get(player_id, player.overall)
        latest = next((record for record in reversed(season.development_records) if record["player_id"] == player_id), None)
        return {**player.model_dump(), "overall": overall, "base_overall": player.overall,
                "overall_delta": overall - player.overall,
                "internal_market_value_cents": latest["internal_market_value_cents"] if latest else player.market_value_cents,
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

    async def create_offer(self, room_id: str, buyer: str, incoming_id: str, offered_id: str, amount_cents: int, idempotency_key: str, human_clubs: set[str]) -> TransferOffer:
        async with self._lock(room_id):
            market = self._market(room_id)
            existing = next((offer for offer in self._offers.get(room_id, {}).values() if offer.buyer_club == buyer and offer.idempotency_key == idempotency_key), None)
            if existing:
                return existing
            seller = next((code for code, team in market.teams.items() if incoming_id in team.roster), None)
            if seller is None or seller == buyer:
                raise MarketError("O atleta alvo não pertence a outro clube.")
            if buyer not in market.teams:
                raise MarketError("Clube comprador não encontrado.")
            if offered_id not in market.teams[buyer].roster:
                raise MarketError("O atleta oferecido não pertence ao seu clube.")
            incoming, offered = market.catalog[incoming_id], market.catalog[offered_id]
            if incoming.position != offered.position:
                raise MarketError("A negociação deve preservar as posições dos dois elencos.")
            if buyer not in market.teams:
                raise MarketError("Clube comprador não encontrado.")
            self._ensure_offer_fits(room_id, market, buyer, amount_cents)
            offer = TransferOffer(f"transfer-{len(self._offers.get(room_id, {})) + 1}", idempotency_key, buyer, seller, incoming_id, offered_id, amount_cents)
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
            recipient = offer.buyer_club if offer.status == "COUNTERED" else offer.seller_club
            if actor != recipient:
                raise MarketError("Somente quem recebeu a proposta pode aceitá-la.")
            if offer.status not in {"PENDING", "COUNTERED"}:
                raise MarketError("Esta proposta já foi encerrada.")
            self._commit_trade(room_id, market, offer)
            offer.status = "ACCEPTED"
            return offer

    async def reject(self, room_id: str, offer_id: str, actor: str) -> TransferOffer:
        async with self._lock(room_id):
            self._market(room_id)
            offer = self._offer(room_id, offer_id)
            if actor not in {offer.buyer_club, offer.seller_club}:
                raise MarketError("Você não participa desta negociação.")
            if offer.status in {"PENDING", "COUNTERED"}:
                offer.status = "REJECTED"
            return offer

    async def counter(self, room_id: str, offer_id: str, seller: str, amount_cents: int) -> TransferOffer:
        async with self._lock(room_id):
            market = self._market(room_id)
            offer = self._offer(room_id, offer_id)
            if seller != offer.seller_club or offer.status != "PENDING" or amount_cents <= offer.amount_cents:
                raise MarketError("Contraproposta inválida para esta negociação.")
            self._ensure_offer_fits(room_id, market, offer.buyer_club, amount_cents, exclude_offer=offer.id)
            offer.amount_cents = amount_cents
            offer.counter_cents = amount_cents
            offer.status = "COUNTERED"
            return offer

    async def cancel(self, room_id: str, offer_id: str, buyer: str) -> TransferOffer:
        async with self._lock(room_id):
            self._market(room_id)
            offer = self._offer(room_id, offer_id)
            if buyer != offer.buyer_club:
                raise MarketError("Somente quem enviou pode cancelar a proposta.")
            if offer.status in {"PENDING", "COUNTERED"}:
                offer.status = "CANCELLED"
            return offer

    def view_for(self, room_id: str, club: str) -> list[dict[str, object]]:
        return [asdict(offer) for offer in self._offers.get(room_id, {}).values() if club in {offer.buyer_club, offer.seller_club}]

    @staticmethod
    def _offer_view(offer: TransferOffer) -> dict[str, object]:
        return asdict(offer)

    def export_room(self, room_id: str) -> dict[str, object]:
        return {"offers": [asdict(offer) for offer in self._offers.get(room_id, {}).values()], "operations": sorted(self._operations.get(room_id, set())), "listings": sorted(self._listings.get(room_id, set()))}

    def restore_room(self, room_id: str, payload: dict[str, object]) -> None:
        offers = {}
        for raw in payload.get("offers", []):
            offer = TransferOffer(**raw)
            if offer.status not in {"PENDING", "COUNTERED", "ACCEPTED", "REJECTED", "CANCELLED", "BOT_REJECTED"}:
                raise ValueError("Snapshot contém estado de negociação desconhecido.")
            offers[offer.id] = offer
        self._offers[room_id] = offers
        self._operations[room_id] = set(map(str, payload.get("operations", [])))
        self._locks.setdefault(room_id, asyncio.Lock())
        self._listings[room_id] = set(map(str, payload.get("listings", [])))

    def _offer(self, room_id: str, offer_id: str) -> TransferOffer:
        try:
            return self._offers[room_id][offer_id]
        except KeyError as error:
            raise MarketError("Proposta de transferência não encontrada.") from error

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
        target = market.catalog[offer.incoming_player_id]
        offered = market.catalog[offer.offered_player_id]
        target_value = int(self.player_view(room_id, market, target.id)["internal_market_value_cents"])
        offered_value = int(self.player_view(room_id, market, offered.id)["internal_market_value_cents"])
        value_delta = offered_value + offer.amount_cents - target_value
        seed = int(hashlib.sha256(f"{offer.idempotency_key}:{offer.seller_club}".encode()).hexdigest()[:8], 16)
        tolerance = int.from_bytes(hashlib.sha256(str(seed).encode()).digest()[:4], "big") % max(1, target_value // 12 + 1)
        if value_delta >= -tolerance:
            self._commit_trade(room_id, market, offer)
            offer.status = "ACCEPTED"
        elif value_delta >= -target_value // 5:
            counter = max(offer.amount_cents, target_value - offered_value)
            try:
                self._ensure_offer_fits(room_id, market, offer.buyer_club, counter, exclude_offer=offer.id)
            except MarketError:
                offer.status = "BOT_REJECTED"
                return
            offer.amount_cents = counter
            offer.counter_cents = offer.amount_cents
            offer.status = "COUNTERED"
        else:
            offer.status = "BOT_REJECTED"


transfer_service = TransferService()
