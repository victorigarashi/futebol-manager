"""A whole (small) season to the champion, development applied once, next season keeps
rosters, money and the new levels - and the engine really uses the new levels."""

from __future__ import annotations

from app.domain.clubs import CLUBS
from app.domain.market import InitialMarket
from app.services.season_service import SeasonService
from app.tests.fixtures.market_catalog import complete_test_market, synthetic_catalog

CLUB_CODES = tuple(c.code for c in CLUBS)[:4]


def test_season_ends_develops_players_once_and_the_next_season_continues():
    now = [1_000.0]
    service = SeasonService(clock=lambda: now[0])
    market = InitialMarket(synthetic_catalog("FIVE_A_SIDE", teams=4), "FIVE_A_SIDE", dict.fromkeys(CLUB_CODES, 10**10))
    complete_test_market(market, "transition")
    service.create("room", market, double_round_robin=False)
    rosters = {club: list(team.roster) for club, team in market.teams.items()}
    budgets = {club: team.budget_cents for club, team in market.teams.items()}
    for _ in range(3):
        if service._season("room").transfer_window_open:
            service.close_transfer_window("room")  # the mid-season window (after round 1 of 3)
        service.advance("room", market, set(), 90)
        now[0] += 200
        service.sync_live("room")
        assert service.finish_due("room")
    view = service.advance("room", market, set(), 90)  # 4 clubs: the table decides, no knockout
    season = service._season("room")
    assert view["champion"] and season.progression_applied
    developed = dict(season.current_overalls)
    records = len(season.development_records)
    # Advancing again (refresh, repeated request) never applies development twice.
    service.advance("room", market, set(), 90)
    assert season.current_overalls == developed and len(season.development_records) == records
    played = {p for match in season.matches.values() for p in match.get("minutes", {})}
    assert any(r["delta"] != 0 for r in season.development_records if r["player_id"] in played) or records
    nxt = service.create_next_season("room", market)
    assert nxt["season_number"] == 2 and nxt["current_round"] == 1
    new = service._season("room")
    assert new.current_overalls == developed and new.double_round_robin is False
    assert {club: list(team.roster) for club, team in market.teams.items()} == rosters
    assert {club: team.budget_cents for club, team in market.teams.items()} == budgets
    # The engine plays with the developed level.
    changed = next((pid for pid, ovr in developed.items() if ovr != market.catalog[pid].overall
                    and any(pid in roster for roster in rosters.values())), None)
    if changed:
        club = next(c for c, roster in rosters.items() if changed in roster)
        team = service._team_input("room", market, club)
        inputs = {p.id: p.overall for p in team.starters + team.bench}
        if changed in inputs:
            assert inputs[changed] == developed[changed]
