"""Live knockouts: pot draw, two legs with aggregate, cumulative prizes and Copa do Brasil."""

import copy

from app.domain.knockout import KnockoutState, Tie, pot_draw
from app.domain.market import InitialMarket
from app.domain.season import MatchResult
from app.services.season_service import SeasonService
from app.tests.fixtures.clock import finish_round, play_knockouts
from app.tests.fixtures.market_catalog import complete_test_market, synthetic_catalog

CLUBS = tuple(f"C{index:02}" for index in range(20))


def season_with(rules, room="ko"):
    market = InitialMarket(synthetic_catalog("FIVE_A_SIDE", teams=20), "FIVE_A_SIDE", dict.fromkeys(CLUBS, 2_000_000_000))
    complete_test_market(market, room)
    service = SeasonService()
    service.create(room, market, rules=rules)
    return service, market


def test_pot_draw_pairs_each_top_four_club_with_a_bottom_four_club_reproducibly():
    pot1, pot2 = ["A", "B", "C", "D"], ["E", "F", "G", "H"]
    first = pot_draw("seed", pot1, pot2)
    assert first == pot_draw("seed", pot1, pot2)
    assert [high for high, _ in first] == pot1 and sorted(low for _, low in first) == pot2
    assert any(pot_draw(f"seed-{i}", pot1, pot2) != first for i in range(10))  # really random


def test_two_legs_use_the_aggregate_without_away_goals_and_record_each_leg_once():
    tie = Tie("po-qf-1", "PLAYOFF", "QF", "HIGH", "LOW", 2, 1)
    assert tie.fixture(1) == ("LOW", "HIGH") and tie.fixture(2) == ("HIGH", "LOW")  # better seed hosts leg 2
    tie.record_leg(1, 2, 1)  # LOW 2 x 1 HIGH
    tie.record_leg(1, 9, 9)  # replayed notification: ignored
    tie.record_leg(2, 1, 0)  # HIGH 1 x 0 LOW
    assert tie.aggregate() == (2, 2)  # level: away goals do not count, penalties decide


def test_two_legged_playoffs_are_live_pay_cumulative_prizes_once_and_crown_a_champion():
    service, market = season_with({"playoff_format": "TWO_LEGS"})
    before = {club: team.budget_cents for club, team in market.teams.items()}
    season = service._season("ko")
    for fixture in season.state.fixtures:
        season.state.record(MatchResult(fixture.id, 0, 0))
    service.advance("ko", market, set())  # nothing live is due: the draw happens now
    draw = season.knockout.draws[-1]
    assert draw["kind"] == "POTS" and len(draw["pot1"]) == len(draw["pot2"]) == 4
    qualifiers = set(draw["pot1"]) | set(draw["pot2"])
    assert all(market.teams[c].budget_cents == before[c] + 5_000_000_000 for c in qualifiers)
    first_leg = service.advance("ko", market, set())
    assert first_leg["live_round"]["kind"] == "PLAYOFF" and first_leg["live_round"]["leg"] == 1
    assert len(first_leg["live_round"]["match_ids"]) == 4
    finish_round(service, "ko")
    final = play_knockouts(service, "ko", market)
    ties = season.knockout.ties
    assert sum(1 for t in ties.values() if t.competition == "PLAYOFF") == 7
    assert all(len(t.leg_scores) == 2 for t in ties.values())
    champion, runner_up = final["champion"], final["knockout"]["playoff_runner_up"]
    assert market.teams[champion].budget_cents == before[champion] + 35_000_000_000
    assert market.teams[runner_up].budget_cents == before[runner_up] + 30_000_000_000
    paid = market.teams[champion].budget_cents
    service._settle_knockout("ko", market, season)
    assert market.teams[champion].budget_cents == paid
    assert season.progression_applied


def test_copa_do_brasil_is_interleaved_live_and_has_its_own_champion():
    service, market = season_with({"copa_enabled": True}, room="cup")
    season = service._season("cup")
    knockout = season.knockout
    prelim = knockout.stage_ties("CUP", "PRELIM")
    assert len(prelim) == 4 and {c for t in prelim for c in (t.high, t.low)} == set(knockout.cup_seeds[12:])
    played_cup = []
    for _ in range(120):
        view = service.view("cup")
        if view["regular_season_complete"] and knockout.cup_champion:
            break
        if season.transfer_window_open:
            service.close_transfer_window("cup")
        state = service.advance("cup", market, set())
        if state["live_round"]:
            if state["live_round"]["kind"] == "CUP":
                played_cup.append((state["live_round"]["stage"], state["live_round"]["round_number"]))
            finish_round(service, "cup")
    stages = [stage for stage, _ in played_cup]
    assert stages == ["PRELIM", "R16", "QF", "SF", "FINAL"]
    rounds = [number for _, number in played_cup]
    assert rounds == sorted(rounds) and rounds[-1] < 38  # played between league rounds
    r16 = knockout.stage_ties("CUP", "R16")
    assert len(r16) == 8 and len({c for t in r16 for c in (t.high, t.low)}) == 16
    assert knockout.cup_champion and knockout.cup_runner_up and knockout.cup_champion != knockout.cup_runner_up
    league_ids = {f.id for f in season.state.fixtures}
    assert len([m for m in season.matches if m.startswith("cup-")]) == 4 + 8 + 4 + 2 + 1
    assert set(season.state.results) == league_ids  # Copa results never enter the league table


def test_snapshot_restores_a_live_knockout_round():
    service, market = season_with({"playoff_format": "TWO_LEGS"}, room="snap")
    season = service._season("snap")
    for fixture in season.state.fixtures:
        season.state.record(MatchResult(fixture.id, 1, 0))
        season.matches[fixture.id] = {"id": fixture.id, "home": fixture.home, "away": fixture.away, "home_goals": 1, "away_goals": 0,
                                      "status": "FINISHED", "events": [{"event_id": f"{fixture.id}:1", "match_id": fixture.id,
                                                                        "kind": "GOAL", "team": fixture.home, "x": .9, "y": .5}]}
    service.advance("snap", market, set())
    live = service.advance("snap", market, set())["live_round"]
    snapshot = copy.deepcopy(service.export_room("snap"))
    restored = SeasonService(clock=service.clock)
    restored.restore_room("snap", snapshot)
    again = restored._season("snap")
    assert again.live_round["knockout_round_id"] == live["knockout_round_id"]
    assert isinstance(again.knockout, KnockoutState) and len(again.knockout.ties) == 4
    again.market_ref = market
    finish_round(restored, "snap")
    assert all(len(t.leg_scores) == 1 for t in again.knockout.ties.values())
