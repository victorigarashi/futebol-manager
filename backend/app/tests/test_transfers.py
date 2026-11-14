import asyncio

from app.domain.market import InitialMarket, MarketError
from app.services.market_service import MarketService, MarketSession
from app.services.season_service import SeasonService
from app.services.squad_service import SquadService
from app.services.transfer_service import TransferService
from app.tests.fixtures.market_catalog import complete_test_market, synthetic_catalog


def test_trade_counter_atomicity_and_bot_decision(monkeypatch) -> None:
    import app.services.transfer_service as transfer_module

    clubs = tuple(f"C{index:02}" for index in range(20))
    market = InitialMarket(synthetic_catalog("FIVE_A_SIDE", teams=20), "FIVE_A_SIDE", {club: 10_000_000_000 for club in clubs})
    complete_test_market(market, "transfers")
    market_manager = MarketService()
    market_manager.registry._markets["transfers"] = market
    market_manager.registry._locks["transfers"] = asyncio.Lock()
    market_manager.sessions["transfers"] = MarketSession("transfers", 0, market, finalized=True)
    seasons = SeasonService()
    room_season = seasons.create("transfers", market)
    room_season.transfer_window_open = True
    monkeypatch.setattr(transfer_module, "market_service", market_manager)
    monkeypatch.setattr(transfer_module, "season_service", seasons)
    monkeypatch.setattr(transfer_module, "squad_service", SquadService())
    service = TransferService()
    target = next(player for player in market.teams["C01"].roster if market.catalog[player].position == "DF")
    offered = next(player for player in market.teams["C00"].roster if market.catalog[player].position == "DF")
    buyer_balance, seller_balance = market.teams["C00"].budget_cents, market.teams["C01"].budget_cents
    offer = asyncio.run(service.create_offer("transfers", "C00", target, offered, 0, "offer-key-human-1", {"C00", "C01"}))
    assert offer.status == "PENDING"
    asyncio.run(service.counter("transfers", offer.id, "C01", 100))
    asyncio.run(service.accept("transfers", offer.id, "C00"))
    asyncio.run(service.accept("transfers", offer.id, "C01"))
    assert offer.status == "ACCEPTED"
    assert target in market.teams["C00"].roster and offered in market.teams["C01"].roster
    assert market.teams["C00"].budget_cents == buyer_balance - 100
    assert market.teams["C01"].budget_cents == seller_balance + 100
    assert len({player_id for team in market.teams.values() for player_id in team.roster}) == 160

    bot_target = next(player for player in market.teams["C02"].roster if market.catalog[player].position == "DF")
    bot_offer = next(player for player in market.teams["C00"].roster if market.catalog[player].position == "DF" and player != target)
    response = asyncio.run(service.create_offer("transfers", "C00", bot_target, bot_offer, 0, "offer-key-bot-0002", {"C00"}))
    assert response.status == "ACCEPTED"
    assert bot_target in market.teams["C00"].roster and bot_offer in market.teams["C02"].roster


def test_pending_transfer_offers_reserve_the_buyers_budget(monkeypatch) -> None:
    import app.services.transfer_service as transfer_module

    clubs = tuple(f"R{index:02}" for index in range(20))
    market = InitialMarket(synthetic_catalog("FIVE_A_SIDE", teams=20), "FIVE_A_SIDE", {club: 10_000_000_000 for club in clubs})
    complete_test_market(market, "reserve")
    manager = MarketService()
    manager.registry._markets["reserve"] = market
    manager.registry._locks["reserve"] = asyncio.Lock()
    manager.sessions["reserve"] = MarketSession("reserve", 0, market, finalized=True)
    seasons = SeasonService()
    seasons.create("reserve", market).transfer_window_open = True
    monkeypatch.setattr(transfer_module, "market_service", manager)
    monkeypatch.setattr(transfer_module, "season_service", seasons)
    monkeypatch.setattr(transfer_module, "squad_service", SquadService())
    service = TransferService()

    target = next(player for player in market.teams["R01"].roster if market.catalog[player].position == "DF")
    offered = next(player for player in market.teams["R00"].roster if market.catalog[player].position == "DF")
    market.teams["R00"].budget_cents = market.teams["R00"].reserved_cents + 1_000
    pending = asyncio.run(service.create_offer("reserve", "R00", target, offered, 700, "reserve-1", {"R00", "R01"}))
    try:
        asyncio.run(service.create_offer("reserve", "R00", target, offered, 400, "reserve-2", {"R00", "R01"}))
    except MarketError:
        pass
    else:
        raise AssertionError("A segunda oferta comprometeu saldo já reservado.")
    try:
        asyncio.run(service.counter("reserve", pending.id, "R01", 1_001))
    except MarketError:
        pass
    else:
        raise AssertionError("Contraproposta excedeu o saldo disponível.")
    assert pending.amount_cents == 700
