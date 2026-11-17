"""Career layer: optional morale/conditioning, statistics, news, trophies, rivalries,
special events and the optional coach market - all derived from real data."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from app.domain.market import InitialMarket
from app.domain.rooms import RoomManager
from app.services import career_service
from app.services.season_service import SeasonService
from app.tests.fixtures.market_catalog import complete_test_market, synthetic_catalog

FOUR = ("FLA", "FLU", "PAL", "COR")  # two derbies inside a 4-club league


def small_season(morale: bool):
    now = [1_000.0]
    service = SeasonService(clock=lambda: now[0])
    market = InitialMarket(synthetic_catalog("FIVE_A_SIDE", teams=20), "FIVE_A_SIDE", dict.fromkeys(FOUR, 10**10))
    complete_test_market(market, f"career-{morale}")
    service.create("room", market, double_round_robin=False, rules={"morale_enabled": morale})
    for _ in range(3):
        if service._season("room").transfer_window_open:
            service.close_transfer_window("room")
        service.advance("room", market, set(), 60)
        now[0] += 200
        service.sync_live("room")
        assert service.finish_due("room")
    return service, market


def test_conditioning_and_morale_only_act_when_enabled_and_stay_moderate():
    off, market_off = small_season(False)
    season_off = off._season("room")
    assert season_off.fatigue == {} and season_off.morale == {}
    pid = market_off.teams["FLA"].roster[0]
    assert off.condition_adjustment(season_off, "FLA", pid) == 0
    on, market_on = small_season(True)
    season_on = on._season("room")
    assert season_on.morale and all(-3 <= value <= 3 for value in season_on.morale.values())
    adjustments = [on.condition_adjustment(season_on, club, pid) for club in FOUR for pid in market_on.teams[club].roster]
    assert all(-4 <= value <= 1 for value in adjustments)
    assert any(value != 0 for value in adjustments)
    # The same match inputs differ only through the (moderate) adjustment.
    raw = {p.id: p.overall for p in off._team_input("room", market_off, "FLA").starters}
    adjusted = {p.id: p.overall for p in on._team_input("room", market_on, "FLA").starters}
    assert all(abs(adjusted[k] - raw[k]) <= 4 for k in raw if k in adjusted)


def test_statistics_match_the_events_and_ignore_live_matches():
    service, market = small_season(False)
    season = service._season("room")
    stats = career_service.player_stats(season)
    goals_in_events = sum(1 for m in season.matches.values() for e in m["events"] if e["kind"] == "GOAL")
    assert sum(int(row["goals"]) for row in stats.values()) == goals_in_events
    assert all(row["apps"] <= 3 for row in stats.values())
    team = career_service.team_of_season(list(stats.values()), 1)
    assert [r["position"] for r in team].count("GK") <= 1


def test_news_come_from_real_events_and_rumours_never_reveal_amounts():
    service, market = small_season(False)
    season = service._season("room")
    names = {pid: p.name for pid, p in market.catalog.items()}
    rumour = {"id": "t1", "buyer_club": "PAL", "seller_club": "FLA", "incoming_player_id": market.teams["FLA"].roster[0],
              "offered_player_id": market.teams["PAL"].roster[0], "amount_cents": 123_456_789, "status": "PENDING", "origin": "BOT"}
    items = career_service.news(season, [], FOUR, {}, [rumour], names)
    kinds = {item["kind"] for item in items}
    assert "LEADER" in kinds and "RUMOR" in kinds
    assert "CLASSIC" in kinds  # Fla-Flu or Derby were played
    assert not any("1.234" in item["body"] or "123456789" in item["body"] or "R$" in item["body"] for item in items if item["kind"] == "RUMOR")
    played = {(m["home"], m["away"]) for m in season.matches.values()}
    for item in items:
        if item["kind"] in ("CLASSIC", "ROUT"):
            assert tuple(item["clubs"]) in played


def test_trophies_keep_club_and_coach_even_after_a_change():
    history = [{"season_number": 1, "champion": "FLA", "runner_up": "PAL", "cup_champion": "COR", "cup_runner_up": "SAO",
                "managers": {"FLA": {"user_id": "u1", "name": "Vitão"}}},
               {"season_number": 2, "champion": "PAL", "runner_up": "FLA", "managers": {"PAL": {"user_id": "u1", "name": "Vitão"}}}]
    items = career_service.trophies(history)
    titles = [(i["season_number"], i["competition"], i["club_code"], i["coach_name"]) for i in items if i["place"] == "CHAMPION"]
    assert (1, "BRASILEIRAO", "FLA", "Vitão") in titles and (2, "BRASILEIRAO", "PAL", "Vitão") in titles
    assert (1, "COPA_DO_BRASIL", "COR", None) in titles


def test_rivalries_head_to_head_and_special_events():
    assert career_service.rivalry("GRE", "INT") == "Gre-Nal" and career_service.rivalry("FLA", "REM") is None
    results = [{"home": "FLA", "away": "FLU", "home_goals": 2, "away_goals": 1},
               {"home": "FLU", "away": "FLA", "home_goals": 1, "away_goals": 1},
               {"home": "FLU", "away": "FLA", "home_goals": 0, "away_goals": 0, "home_penalties": 4, "away_penalties": 3}]
    h2h = career_service.head_to_head(results, "FLA", "FLU")
    assert h2h["meetings"] == 3 and h2h["wins"] == {"FLA": 1, "FLU": 1} and h2h["draws"] == 1
    service, market = small_season(False)
    events = career_service.special_events(service._season("room"), "FLA", "FLU", FOUR, None, None, None, None, ["Fulano"])
    assert {e["kind"] for e in events} >= {"CLASSIC", "FORMER_CLUB"}
    final = career_service.special_events(service._season("room"), "PAL", "COR", FOUR, "PLAYOFF", "FINAL", 2, 2, [])
    assert {e["kind"] for e in final} >= {"TITLE", "DECISIVE"}


def test_preview_carries_classic_history_and_events():
    service, market = small_season(False)
    service._season("room").state.results.clear()  # a fresh round 1 preview
    preview = service.preview("room", market, "FLA")
    assert preview["fixture"]["home"] in FOUR
    assert "head_to_head" in preview and "special_events" in preview


def test_season_summary_records_results_players_and_coaches():
    service, market = small_season(False)
    summary = career_service.season_summary(service._season("room"), FOUR, {"FLA": {"user_id": "u1", "name": "Vitão"}})
    assert len(summary["results"]) == 6 and summary["managers"]["FLA"]["name"] == "Vitão"
    assert summary["player_stats"] and summary["league_leader"] in FOUR


def test_coach_market_moves_a_human_to_a_free_club_never_onto_another_human():
    async def scenario():
        rooms = RoomManager()
        state = await rooms.create(user_id="h", display_name="Host", name="Liga", mode="FIVE_A_SIDE", initial_budget_cents=5_000_000_000,
                                   max_human_participants=3, privacy="PRIVATE", coach_moves_enabled=True)
        room_id = state["id"]
        await rooms.join(room_id, "g", "Guest")
        await rooms.select_club(room_id, "h", "FLA")
        await rooms.select_club(room_id, "g", "PAL")
        moved = await rooms.change_club_between_seasons(room_id, "h", "COR")
        assert next(p for p in moved["participants"] if p["user_id"] == "h")["selected_club_code"] == "COR"
        with pytest.raises(HTTPException):
            await rooms.change_club_between_seasons(room_id, "h", "PAL")  # another human's club
    asyncio.run(scenario())
