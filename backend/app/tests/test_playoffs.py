from app.domain.market import InitialMarket
from app.domain.playoffs import (
    KnockoutMatch,
    create_bracket,
    quarterfinal_pairings,
    resolve_penalties,
    semifinal_pairings,
)
from app.domain.progression import progress_player
from app.domain.season import MatchResult
from app.services.season_service import SeasonService
from app.tests.fixtures.market_catalog import complete_test_market, synthetic_catalog


def test_bracket_pairings_are_fixed_from_table_order() -> None:
    table = [{"club_code": f"C{index}"} for index in range(20)]
    bracket = create_bracket(table)
    assert quarterfinal_pairings(bracket) == (("C0", "C7"), ("C3", "C4"), ("C1", "C6"), ("C2", "C5"))
    bracket.quarterfinals = [KnockoutMatch(f"q{index}", "QF", "H", "A", 1, 0, f"Q{index}") for index in range(4)]
    assert semifinal_pairings(bracket) == (("Q0", "Q1"), ("Q2", "Q3"))


def test_penalties_are_seeded_and_return_a_winner_and_audit_trail() -> None:
    first = resolve_penalties("HOME", "AWAY", (90, 88, 86), (72, 74, 76), 123)
    second = resolve_penalties("HOME", "AWAY", (90, 88, 86), (72, 74, 76), 123)
    assert first == second
    winner, home, away, kicks = first
    assert winner in {"HOME", "AWAY"}
    assert len(kicks) >= 10
    assert home == sum(kick["scored"] for kick in kicks if kick["team"] == "HOME")
    assert away == sum(kick["scored"] for kick in kicks if kick["team"] == "AWAY")


def test_playoff_progression_and_awards_are_idempotent() -> None:
    clubs = tuple(f"C{index:02}" for index in range(20))
    market = InitialMarket(synthetic_catalog("FIVE_A_SIDE", teams=20), "FIVE_A_SIDE", {club: 2_000_000_000 for club in clubs})
    complete_test_market(market, "playoff-room")
    balances_after_market = {club: team.budget_cents for club, team in market.teams.items()}
    service = SeasonService()
    season = service.create("playoff-room", market)
    for fixture in season.state.fixtures:
        season.state.record(MatchResult(fixture.id, 0, 0))
    first = service.advance("playoff-room", market, set())
    second = service.advance("playoff-room", market, set())
    final = service.advance("playoff-room", market, set())
    assert len(first["playoffs"]["quarterfinals"]) == 4
    assert len(second["playoffs"]["semifinals"]) == 2
    assert final["season_complete"] is True
    assert final["progression_applied"] is True
    champion = final["champion"]
    assert champion is not None
    assert market.teams[champion].budget_cents == balances_after_market[champion] + 8_000_000_000
    service.advance("playoff-room", market, set())
    assert sum(entry["type"] == "AWARD" for entry in market.teams[champion].financial_ledger) == 3
    development_count = len(service.view("playoff-room")["development_records"])
    next_season = service.create_next_season("playoff-room", market)
    assert next_season["season_number"] == 2
    assert next_season["current_round"] == 1
    assert next_season["match_count"] == 0
    assert len(next_season["development_records"]) == development_count
    assert len(next_season["season_history"]) == 1


def test_player_progression_is_deterministic_bounded_and_keeps_catalog_input_unchanged() -> None:
    source = {"overall": 72, "potential": 91, "value": 250_000_000}
    arguments = {"player_id": "young", "season_number": 2, "age": 19, "overall": source["overall"], "potential": source["potential"], "original_market_value_cents": source["value"], "minutes_played": 2_700, "goals": 12, "seed": 35}
    first = progress_player(**arguments)
    second = progress_player(**arguments)
    veteran = progress_player(player_id="veteran", season_number=1, age=38, overall=84, potential=84, original_market_value_cents=500_000_000, minutes_played=2_700, goals=2, seed=9)
    assert first == second
    assert source == {"overall": 72, "potential": 91, "value": 250_000_000}
    assert first.overall_before <= first.overall_after <= first.overall_before + 4
    assert first.overall_after <= 91
    assert veteran.overall_after <= veteran.overall_before
    assert first.internal_market_value_cents >= 0
