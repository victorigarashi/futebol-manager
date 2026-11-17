"""Advanced market: cash purchases, loans, disputes, deadlines, dynamic value and bot initiative."""

import asyncio

import pytest

from app.api.schemas import RoomCreate
from app.domain.market import InitialMarket, MarketError
from app.services.market_service import MarketService, MarketSession
from app.services.season_service import SeasonService
from app.services.squad_service import SquadService
from app.services.transfer_service import TransferService
from app.tests.fixtures.market_catalog import complete_test_market, synthetic_catalog

CLUBS = tuple(f"C{index:02}" for index in range(20))


@pytest.fixture
def window(monkeypatch):
    import app.services.transfer_service as transfer_module

    market = InitialMarket(synthetic_catalog("FIVE_A_SIDE", teams=20), "FIVE_A_SIDE", dict.fromkeys(CLUBS, 10_000_000_000))
    complete_test_market(market, "v2")
    manager = MarketService()
    manager.registry._markets["v2"] = market
    manager.registry._locks["v2"] = asyncio.Lock()
    manager.sessions["v2"] = MarketSession("v2", 0, market, finalized=True)
    seasons = SeasonService()
    seasons.create("v2", market, rules={"bot_difficulty": "COMPETITIVE"}).transfer_window_open = True
    monkeypatch.setattr(transfer_module, "market_service", manager)
    monkeypatch.setattr(transfer_module, "season_service", seasons)
    monkeypatch.setattr(transfer_module, "squad_service", SquadService())
    now = [1000.0]
    service = TransferService(clock=lambda: now[0])
    # Make room in two rosters (8 is the 5-a-side maximum) so cash moves are possible.
    for club in ("C00", "C03"):
        market.teams[club].roster.pop()
    return service, market, seasons, now


def owned(market):
    return [pid for team in market.teams.values() for pid in team.roster]


def money(market):
    return sum(team.budget_cents for team in market.teams.values())


def run(coro):
    return asyncio.run(coro)


def test_starting_budgets_up_to_one_billion():
    for cents in (30_000_000_000, 40_000_000_000, 50_000_000_000, 100_000_000_000):
        assert RoomCreate(name="Liga", mode="ELEVEN_A_SIDE", max_human_participants=2, initial_budget_cents=cents).initial_budget_cents == cents
    with pytest.raises(ValueError):
        RoomCreate(name="Liga", mode="ELEVEN_A_SIDE", max_human_participants=2, initial_budget_cents=12_345)


def test_cash_purchase_moves_one_player_and_respects_roster_limits(window):
    service, market, _, _ = window
    total, cash = len(owned(market)), money(market)
    target = market.teams["C01"].roster[3]
    offer = run(service.create_offer("v2", "C00", target, "", 900_000_000, "cash-key-0001", {"C00", "C01"}))
    assert offer.kind == "PURCHASE" and offer.status == "PENDING"
    run(service.accept("v2", offer.id, "C01"))
    assert target in market.teams["C00"].roster and target not in market.teams["C01"].roster
    assert len(owned(market)) == len(set(owned(market))) == total and money(market) == cash
    full = market.teams["C02"].roster[0]
    with pytest.raises(MarketError):  # C00 is full again (8)
        run(service.create_offer("v2", "C00", full, "", 1, "cash-key-0002", {"C00", "C02"}))


def test_loan_keeps_ownership_plays_for_the_borrower_and_returns(window, monkeypatch):
    import app.services.transfer_service as transfer_module

    service, market, seasons, _ = window
    target = market.teams["C01"].roster[4]
    offer = run(service.create_offer("v2", "C03", target, "", 50_000_000, "loan-key-0001", {"C03", "C01"}, "LOAN"))
    run(service.accept("v2", offer.id, "C01"))
    assert target in market.teams["C03"].roster  # plays for the borrower
    assert service.loans("v2")[target]["owner"] == "C01"
    with pytest.raises(MarketError):  # cannot be sold on while on loan
        run(service.create_offer("v2", "C00", target, "", 1, "loan-key-0002", {"C00", "C03"}))
    monkeypatch.setattr(transfer_module.market_service, "_session", lambda room: MarketSession("v2", 0, market, finalized=True))
    returned = run(service.end_loans("v2"))
    assert returned == [{"player_id": target, "owner": "C01", "holder": "C03"}]
    assert target in market.teams["C01"].roster and target not in market.teams["C03"].roster
    assert len(owned(market)) == len(set(owned(market)))
    seasons._season("v2").rules["game_mode"] = "DRAFT"
    with pytest.raises(MarketError):
        run(service.create_offer("v2", "C03", target, "", 1, "loan-key-0003", {"C03", "C01"}, "LOAN"))


def test_dispute_for_the_same_player_fails_the_other_offers_and_deadlines_expire(window):
    service, market, _, now = window
    target = market.teams["C05"].roster[2]
    market.catalog[target] = market.catalog[target].model_copy(update={"market_value_cents": 1_000_000_000})
    first = run(service.create_offer("v2", "C00", target, "", 500_000_000, "dispute-a-001", {"C00", "C03", "C05"}))
    second = run(service.create_offer("v2", "C03", target, "", 600_000_000, "dispute-b-001", {"C00", "C03", "C05"}))
    value_with_demand = service.market_value("v2", market, target)
    assert value_with_demand > 1_000_000_000  # two open offers raise the price
    run(service.accept("v2", second.id, "C05"))
    assert second.status == "ACCEPTED" and first.status == "FAILED"
    assert service.market_value("v2", market, target) < value_with_demand  # demand fell back
    late_target = market.teams["C06"].roster[2]
    late = run(service.create_offer("v2", "C00", late_target, "", 500_000_000, "late-key-0001", {"C00", "C06"}))
    now[0] += 10_000
    with pytest.raises(MarketError):
        run(service.accept("v2", late.id, "C06"))
    assert late.status == "EXPIRED"


def test_bots_take_the_initiative_without_breaking_integrity(window):
    service, market, _, _ = window
    total, cash = len(owned(market)), money(market)
    offers = run(service.bot_window_activity("v2", {"C00"}))
    assert offers and all(o.origin == "BOT" for o in offers)
    to_human = [o for o in offers if o.seller_club == "C00"]
    assert all(o.status in {"PENDING", "COUNTERED"} for o in to_human)  # humans answer in the window
    assert all(o.status not in {"PENDING"} for o in offers if o.seller_club != "C00")  # bots answer at once
    assert len(owned(market)) == len(set(owned(market))) == total
    assert money(market) == cash
    assert all(team.budget_cents >= 0 for team in market.teams.values())
    again = run(service.bot_window_activity("v2", {"C00"}))  # idempotent keys: no duplicate proposals
    assert {o.id for o in again} <= {o.id for o in service._offers["v2"].values()}
