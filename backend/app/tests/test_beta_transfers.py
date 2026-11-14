"""Financial and role regressions uncovered in the beta audit."""

import asyncio

import pytest

import app.services.transfer_service as transfer_module
from app.domain.market import InitialMarket, MarketError
from app.services.market_service import MarketService, MarketSession
from app.services.season_service import SeasonService
from app.services.squad_service import SquadService
from app.services.transfer_service import TransferService
from app.tests.fixtures.market_catalog import complete_test_market, synthetic_catalog


@pytest.fixture
def transfer_game(monkeypatch):
    clubs = tuple(f"C{i:02}" for i in range(20))
    market = InitialMarket(synthetic_catalog("FIVE_A_SIDE", teams=20), "FIVE_A_SIDE",
                           dict.fromkeys(clubs, 10_000_000_000))
    complete_test_market(market, "beta-transfers")
    manager = MarketService()
    manager.sessions["room"] = MarketSession("room", 0, market, finalized=True)
    seasons = SeasonService()
    seasons.create("room", market).transfer_window_open = True
    monkeypatch.setattr(transfer_module, "market_service", manager)
    monkeypatch.setattr(transfer_module, "season_service", seasons)
    monkeypatch.setattr(transfer_module, "squad_service", SquadService())
    service = TransferService()
    incoming = next(p for p in market.teams["C01"].roster if market.catalog[p].position == "DF")
    outgoing = next(p for p in market.teams["C00"].roster if market.catalog[p].position == "DF")
    return service, market, seasons, incoming, outgoing


def test_pending_cash_prevents_overspending_via_free_agent_purchase(transfer_game):
    service, market, _, incoming, outgoing = transfer_game
    free = market.catalog[incoming].model_copy(update={"id": "test-free-agent", "market_value_cents": 400})
    market.catalog[free.id] = free
    market.teams["C00"].budget_cents = 1000
    roster = list(market.teams["C00"].roster)
    asyncio.run(service.create_offer("room", "C00", incoming, outgoing, 700, "reserved-first", {"C00", "C01"}))
    with pytest.raises(MarketError, match="Saldo"):
        asyncio.run(service.buy_available("room", "C00", free.id, outgoing, 400, "buy-after-reservation"))
    assert market.teams["C00"].roster == roster
    assert market.teams["C00"].budget_cents == 1000
    assert service.career("room", "C00")["available_transfer_cents"] == 300


def test_counter_only_buyer_accepts_and_retries_are_financially_idempotent(transfer_game):
    service, market, _, incoming, outgoing = transfer_game
    offer = asyncio.run(service.create_offer("room", "C00", incoming, outgoing, 100, "counter-roles", {"C00", "C01"}))
    asyncio.run(service.counter("room", offer.id, "C01", 250))
    before = {club: market.teams[club].budget_cents for club in ("C00", "C01")}
    with pytest.raises(MarketError):
        asyncio.run(service.accept("room", offer.id, "C01"))
    assert market.teams["C00"].budget_cents == before["C00"]
    asyncio.run(service.accept("room", offer.id, "C00"))
    asyncio.run(service.accept("room", offer.id, "C00"))
    asyncio.run(service.accept("room", offer.id, "C01"))
    with pytest.raises(MarketError):
        asyncio.run(service.accept("room", offer.id, "C02"))
    assert market.teams["C00"].budget_cents == before["C00"] - 250
    assert market.teams["C01"].budget_cents == before["C01"] + 250
    assert len([entry for entry in market.teams["C00"].financial_ledger if entry["type"] == "TRANSFER"]) == 1
    assert len(set(pid for team in market.teams.values() for pid in team.roster)) == 160


def test_listing_marks_only_own_player_and_snapshot_preserves_it(transfer_game):
    service, market, _, incoming, outgoing = transfer_game
    with pytest.raises(MarketError):
        asyncio.run(service.set_listing("room", "C00", incoming, True))
    marked = asyncio.run(service.set_listing("room", "C00", outgoing, True))
    assert marked["listed"] is True
    assert service.player_view("room", market, outgoing)["for_sale"] is True
    assert outgoing in market.teams["C00"].roster
    restored = TransferService()
    restored.restore_room("room", service.export_room("room"))
    assert restored.player_view("room", market, outgoing)["for_sale"] is True
    assert restored.player_view("room", market, incoming)["for_sale"] is False


def test_closing_window_cancels_cash_commitments_and_listings(transfer_game):
    service, market, _, incoming, outgoing = transfer_game
    offer = asyncio.run(service.create_offer("room", "C00", incoming, outgoing, 100, "close-window", {"C00", "C01"}))
    asyncio.run(service.set_listing("room", "C00", outgoing, True))
    assert service.career("room", "C00")["reserved_transfer_cents"] == 100
    asyncio.run(service.close_window("room"))
    assert offer.status == "CANCELLED"
    assert service.career("room", "C00")["reserved_transfer_cents"] == 0
    assert not service.player_view("room", market, outgoing)["for_sale"]


def test_concurrent_acceptances_cannot_trade_the_same_outgoing_player_twice(transfer_game):
    service, market, _, incoming, outgoing = transfer_game
    other_target = next(pid for pid in market.teams["C02"].roster if market.catalog[pid].position == "DF")
    balances = {club: market.teams[club].budget_cents for club in ("C00", "C01", "C02")}

    async def race():
        first = await service.create_offer("room", "C00", incoming, outgoing, 100,
                                           "trade-race-one", {"C00", "C01", "C02"})
        second = await service.create_offer("room", "C00", other_target, outgoing, 100,
                                            "trade-race-two", {"C00", "C01", "C02"})
        return await asyncio.gather(service.accept("room", first.id, "C01"),
                                    service.accept("room", second.id, "C02"), return_exceptions=True)

    results = asyncio.run(race())
    assert sum(isinstance(result, MarketError) for result in results) == 1
    assert sum(getattr(result, "status", None) == "ACCEPTED" for result in results) == 1
    assert market.teams["C00"].budget_cents == balances["C00"] - 100
    assert sum(market.teams[club].budget_cents - balances[club] for club in ("C01", "C02")) == 100
    rosters = [pid for team in market.teams.values() for pid in team.roster]
    assert len(rosters) == len(set(rosters)) == 160
