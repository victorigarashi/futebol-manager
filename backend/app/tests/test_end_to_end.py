from app.domain.market import InitialMarket
from app.services.season_service import SeasonService
from app.tests.fixtures.clock import finish_round
from app.tests.fixtures.market_catalog import complete_test_market, synthetic_catalog


def test_full_regular_season_playoffs_and_career_restart_in_both_modes() -> None:
    clubs = tuple(f"C{index:02}" for index in range(20))
    for mode in ("FIVE_A_SIDE", "ELEVEN_A_SIDE"):
        room_id = f"e2e-{mode}"
        market = InitialMarket(synthetic_catalog(mode, teams=20), mode, {club: 10_000_000_000 for club in clubs})
        complete_test_market(market, room_id)
        service = SeasonService()
        service.create(room_id, market)
        for round_number in range(1, 39):
            service.ready(room_id, "C00")
            service.advance(room_id, market, {"C00"})
            state = finish_round(service, room_id)
            if round_number == 19:
                assert state["transfer_window_open"] is True
                service.close_transfer_window(room_id)
        assert service.view(room_id)["match_count"] == 380
        quarterfinals = service.advance(room_id, market, {"C00"})
        semifinals = service.advance(room_id, market, {"C00"})
        champion_state = service.advance(room_id, market, {"C00"})
        assert len(quarterfinals["playoffs"]["quarterfinals"]) == 4
        assert len(semifinals["playoffs"]["semifinals"]) == 2
        assert champion_state["season_complete"] is True
        assert champion_state["progression_applied"] is True
        assert champion_state["champion"] in market.teams

        serialized = service.export_room(room_id)
        restored = SeasonService()
        restored.restore_room(room_id, serialized)
        assert restored.view(room_id)["champion"] == champion_state["champion"]
        next_season = restored.create_next_season(room_id, market)
        assert next_season["season_number"] == 2
        assert next_season["current_round"] == 1
        assert next_season["match_count"] == 0
        assert len(next_season["season_history"]) == 1
