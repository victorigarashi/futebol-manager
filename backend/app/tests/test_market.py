import asyncio
import json
from pathlib import Path

import pytest

from app.domain.catalog import import_catalog
from app.domain.market import InitialMarket, MarketError, MarketRegistry, OfferStatus
from app.tests.fixtures.market_catalog import synthetic_catalog


def market(mode: str = "FIVE_A_SIDE") -> InitialMarket:
    return InitialMarket(synthetic_catalog(mode), mode, {"FLA": 1_000_000_000, "PAL": 1_000_000_000})


def test_secret_offers_reserve_balance_and_are_idempotent() -> None:
    game = market()
    player_id = game.search(position="GK")[0].id
    offer = game.submit_offer("FLA", player_id, 150_000_000, "request-1")
    repeated = game.submit_offer("FLA", player_id, 150_000_000, "request-1")
    assert repeated.id == offer.id
    assert game.teams["FLA"].reserved_cents == 150_000_000
    with pytest.raises(MarketError, match="Saldo"):
        game.submit_offer("FLA", game.search(position="DF")[0].id, 900_000_000, "request-2")


def test_higher_offer_wins_and_tie_is_first_valid_offer() -> None:
    game = market()
    player_id = game.search(position="GK")[0].id
    first = game.submit_offer("PAL", player_id, 200_000_000, "pal-1")
    second = game.submit_offer("FLA", player_id, 200_000_000, "fla-1")
    initial_pal = game.teams["PAL"].budget_cents
    game.resolve()
    assert first.status == OfferStatus.COMMITTED
    assert second.status == OfferStatus.LOST
    assert player_id not in game.teams["PAL"].roster
    assert game.teams["PAL"].budget_cents == initial_pal
    assert game.teams["PAL"].reserved_cents == 200_000_000
    assert game.teams["FLA"].reserved_cents == 0


def test_cancel_and_update_offer_release_and_re_reserve_money() -> None:
    game = market()
    offer = game.submit_offer("FLA", game.search(position="GK")[0].id, 100_000_000, "one")
    game.update_offer(offer.id, "FLA", 180_000_000)
    assert game.teams["FLA"].reserved_cents == 180_000_000
    game.cancel_offer(offer.id, "FLA")
    assert offer.status == OfferStatus.CANCELLED
    assert game.teams["FLA"].reserved_cents == 0


def test_market_completes_valid_rosters_and_distributes_remaining_players() -> None:
    game = market()
    game.resolve()
    for club in game.teams:
        game.confirm_selection(club, [], f"automatic:{club}", automatic=True)
    game.finalize_rosters("full-rosters")
    rosters = {club: team.roster for club, team in game.teams.items()}
    assert all(len(roster) == 8 for roster in rosters.values())
    assert len(set().union(*map(set, rosters.values()))) == 16


def test_viability_explains_missing_position_and_insufficient_budget() -> None:
    catalog = synthetic_catalog("FIVE_A_SIDE")
    catalog.players = [player for player in catalog.players if player.position != "GK"]
    game = InitialMarket(catalog, "FIVE_A_SIDE", {"FLA": 1})
    viability = game.viable()
    assert not viability.viable
    assert any("GK" in reason for reason in viability.reasons)
    assert any("orçamento" in reason for reason in viability.reasons)


def test_parallel_attempts_leave_only_one_winning_offer() -> None:
    async def scenario() -> list[str]:
        registry = MarketRegistry()
        game = registry.create("room-1", synthetic_catalog("FIVE_A_SIDE"), "FIVE_A_SIDE", {"FLA": 1_000_000_000, "PAL": 1_000_000_000})
        player_id = game.search(position="GK")[0].id

        async def bid(club: str) -> str:
            return (await registry.submit_offer("room-1", club, player_id, 100_000_000, club)).id

        await asyncio.gather(bid("FLA"), bid("PAL"))
        await registry.resolve("room-1")
        return [offer.status for offer in game.offers.values()]

    assert sorted(asyncio.run(scenario())) == [OfferStatus.COMMITTED, OfferStatus.LOST]


def test_authorized_json_and_csv_imports_report_duplicates_and_normalize_positions(tmp_path: Path) -> None:
    payload = {"catalog_version": "v1", "source": "authorized", "source_version": "1", "players": [{"id": "p1", "name": " Atleta ", "club_code": "fla", "age": 22, "position": "goleiro", "overall": 70, "potential": 75, "market_value_cents": 100, "source": "authorized", "source_version": "1"}]}
    json_path = tmp_path / "players.json"
    json_path.write_text(json.dumps(payload), encoding="utf-8")
    imported = import_catalog(json_path)
    assert imported.accepted
    assert imported.catalog and imported.catalog.players[0].position == "GK"
    assert imported.catalog.players[0].club_code == "FLA"

    duplicate = {**payload, "players": [*payload["players"], payload["players"][0]]}
    json_path.write_text(json.dumps(duplicate), encoding="utf-8")
    assert import_catalog(json_path).duplicate_ids == ["p1"]

    csv_path = tmp_path / "players.csv"
    csv_path.write_text("catalog_version,catalog_source,catalog_source_version,id,name,club_code,age,position,overall,potential,market_value_cents,source,source_version\nv1,authorized,1,p2,Atleta 2,PAL,23,ST,71,76,200,authorized,1\n", encoding="utf-8")
    assert import_catalog(csv_path).accepted


def test_active_offer_limit_is_enforced_for_each_mode() -> None:
    for mode, limit in (("FIVE_A_SIDE", 16), ("ELEVEN_A_SIDE", 48)):
        game = InitialMarket(synthetic_catalog(mode, teams=20), mode, {"PAL": 5_000_000_000})
        players = list(game.catalog.values())
        for index, player in enumerate(players[:limit]):
            game.submit_offer("PAL", player.id, player.market_value_cents, f"limit-offer-{index:03}")
        assert len(game.offers) == limit
        with pytest.raises(MarketError, match="Limite"):
            game.submit_offer("PAL", players[limit].id, players[limit].market_value_cents, "limit-overflow-001")


@pytest.mark.parametrize(("mode", "limit", "roster_size"), [("FIVE_A_SIDE", 16, 8), ("ELEVEN_A_SIDE", 48, 16)])
def test_selection_can_choose_roster_capacity_from_all_winning_offers(mode: str, limit: int, roster_size: int) -> None:
    game = InitialMarket(synthetic_catalog(mode, teams=20), mode, {"FLA": 10_000_000_000, "PAL": 10_000_000_000})
    by_position = {position: [player for player in game.catalog.values() if player.position == position] for position in game.slots}
    players = [by_position[position][index] for index in range(limit // len(game.slots)) for position in game.slots]
    players = players[:limit]
    for index, player in enumerate(players):
        game.submit_offer("FLA", player.id, player.market_value_cents, f"winning-{index}")
    game.resolve()

    assert len(game.commitments["FLA"]) + len(game.excess_offers["FLA"]) == limit
    assert len(game.commitments["FLA"]) == roster_size
    selection = game.commitments["FLA"]
    preview = game.selection_preview("FLA", selection)
    assert preview["purchase_cents"] == sum(game.offers[item].amount_cents for item in selection)
    result = game.confirm_selection("FLA", selection, f"confirm-{mode}")
    repeated = game.confirm_selection("FLA", [], f"different-retry-{mode}")
    assert result == repeated
    assert result["debit_cents"] == preview["debit_cents"]
    assert game.teams["FLA"].reserved_cents == 0
    assert len(game.teams["FLA"].roster) == roster_size


@pytest.mark.parametrize(("percent", "expected"), [(0, 0), (2, 2_000_000), (5, 5_000_000), (10, 10_000_000)])
def test_voluntary_committed_withdrawal_penalty_is_rounded_and_charged_once(percent: int, expected: int) -> None:
    game = InitialMarket(synthetic_catalog("FIVE_A_SIDE", teams=8), "FIVE_A_SIDE", {"FLA": 5_000_000_000, "PAL": 5_000_000_000}, percent)
    players = list(game.catalog.values())[:2]
    first = game.submit_offer("FLA", players[0].id, 100_000_000, "fine-first")
    game.submit_offer("FLA", players[1].id, 100_000_000, "fine-second")
    game.resolve()

    assert game.selection_preview("FLA", [first.id])["penalty_cents"] == expected
    result = game.confirm_selection("FLA", [first.id], "fine-operation")
    assert result["penalty_cents"] == expected
    assert sum(item["type"] == "WITHDRAWAL_PENALTY" for item in game.teams["FLA"].financial_ledger) == int(expected > 0)
    assert game.teams["FLA"].budget_cents == 5_000_000_000 - 100_000_000 - expected
    assert game.confirm_selection("FLA", [], "retry") == result


def test_excess_withdrawal_has_no_penalty_and_losing_offer_never_becomes_a_right() -> None:
    game = InitialMarket(synthetic_catalog("FIVE_A_SIDE", teams=8), "FIVE_A_SIDE", {"FLA": 5_000_000_000, "PAL": 5_000_000_000}, 10)
    by_position = {position: [player for player in game.catalog.values() if player.position == position] for position in game.slots}
    players = [by_position[position][index] for index in range(3) for position in game.slots][:10]
    for index, player in enumerate(players):
        game.submit_offer("FLA", player.id, player.market_value_cents, f"excess-{index}")
    game.resolve()
    assert len(game.commitments["FLA"]) == 8
    preview = game.selection_preview("FLA", game.commitments["FLA"])
    assert preview["penalty_cents"] == 0

    game = market()
    player = game.search(position="GK")[0]
    game.submit_offer("FLA", player.id, 200_000_000, "winner")
    game.submit_offer("PAL", player.id, 100_000_000, "loser")
    game.resolve()
    assert game.offers["offer-2"].status == OfferStatus.LOST
    assert game.commitments["PAL"] == []
    assert game.teams["PAL"].reserved_cents == 0


def test_selection_snapshot_state_has_single_owner_and_complete_financial_ledger() -> None:
    game = market()
    player = game.search(position="GK")[0]
    first = game.submit_offer("FLA", player.id, 100_000_000, "race-fla")
    second = game.submit_offer("PAL", player.id, 120_000_000, "race-pal")
    game.resolve()
    winner = "PAL" if second.status == OfferStatus.COMMITTED else "FLA"
    losing = first if winner == "PAL" else second
    assert losing.status == OfferStatus.LOST
    game.confirm_selection(winner, game.commitments[winner], f"winner:{winner}")
    assert player.id in game.teams[winner].roster
    assert player.id not in game.teams[losing.club_code].roster
