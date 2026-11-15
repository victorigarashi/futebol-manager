"""Contracts for coin auctions and configurable round-robin leagues."""

import pytest

from app.domain.market import InitialMarket, MarketError
from app.domain.season import generate_calendar
from app.tests.fixtures.market_catalog import synthetic_catalog


def _market() -> InitialMarket:
    return InitialMarket(synthetic_catalog("FIVE_A_SIDE", teams=4), "FIVE_A_SIDE", {"FLA": 100, "PAL": 100, "COR": 100, "SAO": 100}, market_mode="COINS")


def test_coin_market_starts_equal_and_keeps_bids_secret_until_resolution():
    market = _market()
    target = next(player for player in market.catalog.values() if player.position == "ST")
    first = market.submit_offer("FLA", target.id, 20, "coin-first-001")
    second = market.submit_offer("PAL", target.id, 35, "coin-second-001")
    assert market.teams["FLA"].available_cents == 80
    assert market.teams["PAL"].available_cents == 65
    market.resolve()
    assert first.status.value == "LOST"
    assert second.status.value == "COMMITTED"
    assert market.teams["FLA"].reserved_cents == 0
    assert market.teams["PAL"].reserved_cents == 35


def test_coin_market_updates_only_reserve_the_difference_and_never_overspends():
    market = _market()
    target = next(player for player in market.catalog.values() if player.position == "GK")
    offer = market.submit_offer("FLA", target.id, 20, "coin-change-001")
    market.update_offer(offer.id, "FLA", 50)
    assert market.teams["FLA"].reserved_cents == 50
    market.update_offer(offer.id, "FLA", 10)
    assert market.teams["FLA"].reserved_cents == 10
    with pytest.raises(MarketError, match="Saldo insuficiente"):
        market.update_offer(offer.id, "FLA", 101)
    market.cancel_offer(offer.id, "FLA")
    assert market.teams["FLA"].reserved_cents == 0


@pytest.mark.parametrize("count", (4, 6, 8, 10, 12, 16, 20))
@pytest.mark.parametrize("double", (False, True))
def test_calendar_covers_each_club_once_per_round_and_each_pair_correctly(count: int, double: bool):
    clubs = tuple(f"C{index:02}" for index in range(count))
    fixtures = generate_calendar(clubs, double_round_robin=double)
    rounds = count - 1 if not double else (count - 1) * 2
    assert len(fixtures) == count * rounds // 2
    assert {fixture.round_number for fixture in fixtures} == set(range(1, rounds + 1))
    for round_number in range(1, rounds + 1):
        seen = [club for fixture in fixtures if fixture.round_number == round_number for club in (fixture.home, fixture.away)]
        assert sorted(seen) == sorted(clubs)
    pairs = [(fixture.home, fixture.away) for fixture in fixtures]
    if double:
        assert all((away, home) in pairs for home, away in pairs)
    else:
        assert len({frozenset(pair) for pair in pairs}) == len(pairs)
