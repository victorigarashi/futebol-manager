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


def test_bots_do_not_take_human_seats_and_clubs_stay_exclusive():
    import asyncio

    from fastapi import HTTPException

    from app.domain.rooms import RoomManager

    async def scenario() -> None:
        rooms = RoomManager()
        state = await rooms.create(user_id="host", display_name="Host", name="Liga pequena", mode="ELEVEN_A_SIDE",
                                   initial_budget_cents=100, max_human_participants=2, privacy="PRIVATE",
                                   initial_market_duration_seconds=120, round_preparation_duration_seconds=300,
                                   withdrawal_penalty_percent=0, team_count=4, double_round_robin=False, market_mode="COINS")
        room_id = state["id"]
        await rooms.select_club(room_id, "host", "FLA")
        await rooms.add_bot(room_id, "host")
        await rooms.add_bot(room_id, "host")
        # Two bots already in: a friend can still join (bots are not human seats).
        joined = await rooms.join(room_id, "friend", "Amigo")
        assert joined["participant_count"] == 2 and joined["bot_count"] == 2
        with pytest.raises(HTTPException):
            await rooms.add_bot(room_id, "host", "FLA")  # club already taken
        with pytest.raises(HTTPException):
            await rooms.add_bot(room_id, "host")  # 4 of 4 places taken
        with pytest.raises(HTTPException):
            await rooms.join(room_id, "third", "Terceiro")  # no club place left
        bot_club = next(p["selected_club_code"] for p in joined["participants"] if p["role"] == "BOT")
        removed = await rooms.remove_bot(room_id, "host", bot_club)
        assert removed["bot_count"] == 1
    asyncio.run(scenario())


@pytest.mark.parametrize("count", (4, 10))
@pytest.mark.parametrize("double", (False, True))
def test_custom_league_survives_a_server_restart(count: int, double: bool):
    """A restart used to reject every league that was not 20 clubs with ida e volta,
    which made the whole server fail to boot from its snapshot."""
    import copy

    from app.domain.clubs import CLUBS
    from app.services.season_service import SeasonService

    clubs = [club.code for club in CLUBS][:count]
    market = InitialMarket(synthetic_catalog("FIVE_A_SIDE", teams=count), "FIVE_A_SIDE", dict.fromkeys(clubs, 100), market_mode="COINS")
    service = SeasonService(clock=lambda: 1_000.0)
    service.create("room", market, double_round_robin=double)
    snapshot = copy.deepcopy(service.export_room("room"))
    assert snapshot["double_round_robin"] is double
    restored = SeasonService(clock=lambda: 1_000.0)
    restored.restore_room("room", snapshot)
    season = restored._season("room")
    assert season.double_round_robin is double
    assert restored.view("room")["total_rounds"] == (count - 1) * (2 if double else 1)
