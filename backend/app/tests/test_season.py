import pytest

from app.domain.market import InitialMarket, MarketError
from app.domain.season import Fixture, MatchResult, SeasonState, generate_calendar, standings
from app.domain.simulation import TeamStrength, expected_goals, simulate
from app.services.season_service import RoomSeason, SeasonService
from app.tests.fixtures.clock import finish_round
from app.tests.fixtures.market_catalog import complete_test_market, synthetic_catalog

CLUBS = tuple(f"C{number:02}" for number in range(20))


def test_calendar_has_all_brasileirao_invariants() -> None:
    fixtures = generate_calendar(CLUBS)
    assert len(fixtures) == 380
    assert {fixture.round_number for fixture in fixtures} == set(range(1, 39))
    assert all(sum(fixture.round_number == round_number and club in (fixture.home, fixture.away) for fixture in fixtures) == 1 for club in CLUBS for round_number in range(1, 39))
    pairs = {(fixture.home, fixture.away) for fixture in fixtures}
    assert all((away, home) in pairs for home, away in pairs)


def test_results_are_idempotent_and_table_is_sorted() -> None:
    state = SeasonState(generate_calendar(CLUBS))
    fixture = state.fixtures[0]
    result = MatchResult(fixture.id, 2, 0)
    state.record(result)
    state.record(result)
    table = standings(CLUBS, state.fixtures, state.results)
    assert table[0]["club_code"] == fixture.home and table[0]["points"] == 3


def test_top_scorers_come_from_persisted_match_events() -> None:
    fixture = Fixture("r1-1", 1, "A", "B")
    season = RoomSeason(SeasonState([fixture]), "FIVE_A_SIDE")
    season.matches[fixture.id] = {
        "events": [
            {"kind": "GOAL", "player_id": "player-1", "player_name": "Atleta Um", "team": "A"},
            {"kind": "GOAL", "player_id": "player-1", "player_name": "Atleta Um", "team": "A"},
            {"kind": "SHOT", "player_id": "player-2", "player_name": "Atleta Dois", "team": "B"},
        ]
    }
    assert SeasonService._top_scorers(season) == [{"player_id": "player-1", "player_name": "Atleta Um", "club_code": "A", "goals": 2}]


def test_seeded_simulation_is_reproducible_and_favorites_do_not_win_every_time() -> None:
    strong = TeamStrength("A", 90, 90, 90, 90)
    weak = TeamStrength("B", 55, 55, 55, 55)
    assert simulate(strong, weak, "ELEVEN_A_SIDE", 12) == simulate(strong, weak, "ELEVEN_A_SIDE", 12)
    results = [simulate(strong, weak, "ELEVEN_A_SIDE", seed) for seed in range(2_000)]
    wins = sum(result.home_goals > result.away_goals for result in results)
    assert 1_000 < wins < 2_000
    assert sum(result.home_goals == result.away_goals for result in results) > 0


def test_match_events_reconcile_goals_stats_and_coordinates() -> None:
    home = TeamStrength("A", 88, 81, 74, 77, player_ids=("a1", "a2"))
    away = TeamStrength("B", 70, 68, 71, 72, player_ids=("b1", "b2"))
    result = simulate(home, away, "ELEVEN_A_SIDE", 90210, match_id="fixture-1")
    assert [event.event_id for event in result.events] == [event.event_id for event in simulate(home, away, "ELEVEN_A_SIDE", 90210, match_id="fixture-1").events]
    assert sum(event.kind == "GOAL" and event.team == "A" for event in result.events) == result.home_goals
    assert sum(event.kind == "GOAL" and event.team == "B" for event in result.events) == result.away_goals
    assert result.statistics["A"]["goals"] == result.home_goals
    assert result.statistics["B"]["goals"] == result.away_goals
    assert all(0 <= event.x <= 1 and 0 <= event.y <= 1 for event in result.events)
    assert all(event.match_id == "fixture-1" for event in result.events)
    assert result.events[0].kind == "MATCH_START" and result.events[-1].kind == "MATCH_END"


def test_tactical_styles_change_strengths_and_have_tradeoffs() -> None:
    balanced = TeamStrength("A", 80, 80, 80, 80)
    attacking = TeamStrength("A", 80, 80, 80, 80, strategy="ATTACKING")
    defensive = TeamStrength("A", 80, 80, 80, 80, strategy="DEFENSIVE")
    opponent = TeamStrength("B", 80, 80, 80, 80)
    balanced_xg = expected_goals(balanced, opponent, "ELEVEN_A_SIDE")
    attacking_xg = expected_goals(attacking, opponent, "ELEVEN_A_SIDE")
    defensive_xg = expected_goals(defensive, opponent, "ELEVEN_A_SIDE")
    assert attacking_xg[0] > balanced_xg[0]
    assert attacking_xg[1] > balanced_xg[1]
    assert defensive_xg[0] < balanced_xg[0]
    assert defensive_xg[1] < balanced_xg[1]
    counter = TeamStrength("A", 80, 80, 80, 80, strategy="COUNTER")
    press_opponent = TeamStrength("B", 80, 80, 80, 80, strategy="HIGH_PRESS")
    counter_vs_press, counter_away = expected_goals(counter, press_opponent, "FIVE_A_SIDE")
    balanced_vs_press, _ = expected_goals(balanced, press_opponent, "FIVE_A_SIDE")
    assert counter_vs_press > balanced_vs_press
    assert counter_away < balanced_vs_press


def test_season_service_requires_humans_ready_and_advances_once() -> None:
    market = InitialMarket(synthetic_catalog("FIVE_A_SIDE", teams=20), "FIVE_A_SIDE", {club: 1_000_000_000 for club in CLUBS})
    complete_test_market(market, "integration-five")
    service = SeasonService()
    service.create("room", market)
    service.ready("room", "C00")
    result = service.advance("room", market, {"C00"})
    assert result["current_round"] == 1
    result = finish_round(service, "room")
    assert result["current_round"] == 2
    assert len(result["table"]) == 20
    assert result["match_count"] == 10
    match = service.match("room", result["matches"][0]["id"])
    assert len(match["events"]) > 100
    assert sum(event["kind"] == "GOAL" for event in match["events"]) == match["home_goals"] + match["away_goals"]


def test_season_service_builds_live_events_in_both_modes() -> None:
    for mode in ("FIVE_A_SIDE", "ELEVEN_A_SIDE"):
        market = InitialMarket(synthetic_catalog(mode, teams=20), mode, {club: 10_000_000_000 for club in CLUBS})
        complete_test_market(market, f"round-{mode}")
        service = SeasonService()
        service.create(f"room-{mode}", market)
        service.ready(f"room-{mode}", "C00")
        season = service.advance(f"room-{mode}", market, {"C00"})
        assert season["current_round"] == 1
        season = finish_round(service, f"room-{mode}")
        assert season["current_round"] == 2
        match = service.match(f"room-{mode}", season["matches"][0]["id"])
        expected = 5 if mode == "FIVE_A_SIDE" else 11
        assert len(match["home_players"]) == len(match["away_players"]) == expected
        assert len(set(match["home_players"])) == len(set(match["away_players"])) == expected
        assert match["events"][0]["kind"] == "MATCH_START"
        assert match["events"][-1]["kind"] == "MATCH_END"


def test_transfer_window_blocks_round_twenty_until_host_closes_it() -> None:
    market = InitialMarket(synthetic_catalog("FIVE_A_SIDE", teams=20), "FIVE_A_SIDE", {club: 10_000_000_000 for club in CLUBS})
    complete_test_market(market, "transfer-window")
    service = SeasonService()
    season = service.create("window-room", market)
    for fixture in season.state.fixtures:
        if fixture.round_number <= 19:
            season.state.record(MatchResult(fixture.id, 0, 0))
    season.transfer_window_open = True
    with pytest.raises(MarketError, match="janela de transferências"):
        service.advance("window-room", market, set())
    closed = service.close_transfer_window("window-room")
    assert closed["transfer_window_open"] is False
    assert service.advance("window-room", market, set())["current_round"] == 20
    assert finish_round(service, "window-room")["current_round"] == 21
