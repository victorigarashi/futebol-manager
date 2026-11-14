import asyncio

from app.domain.market import InitialMarket
from app.services.market_service import MarketService, MarketSession
from app.tests.fixtures.market_catalog import synthetic_catalog


async def _noop(*_args: object) -> None:
    return None


def _selection_service() -> tuple[MarketService, MarketSession, str]:
    catalog = synthetic_catalog("FIVE_A_SIDE", teams=20)
    market = InitialMarket(catalog, "FIVE_A_SIDE", {"FLA": 5_000_000_000}, withdrawal_penalty_percent=5)
    player = market.search(position="GK")[0]
    offer = market.submit_offer("FLA", player.id, player.market_value_cents, "lifecycle-offer")
    market.resolve()
    service = MarketService()
    service.registry._markets["lifecycle"] = market
    service.registry._locks["lifecycle"] = asyncio.Lock()
    session = MarketSession(
        "lifecycle", 1_900_000_000, market, finalized=True, human_clubs={"FLA"},
        managers={"FLA": "Técnico"}, selection_ends_at=1_800_000_000,
        market_phase="MARKET_SELECTION", on_progressed=_noop,
    )
    service.sessions["lifecycle"] = session
    return service, session, offer.id


def test_two_concurrent_confirmations_charge_and_transfer_once() -> None:
    async def scenario() -> tuple[dict[str, object], dict[str, object], MarketSession]:
        service, session, offer_id = _selection_service()
        results = await asyncio.gather(
            service.confirm_selection("lifecycle", "FLA", [offer_id], "same-request"),
            service.confirm_selection("lifecycle", "FLA", [offer_id], "same-request"),
        )
        return results[0], results[1], session

    first, second, session = asyncio.run(scenario())
    assert first == second
    assert len([item for item in session.market.teams["FLA"].financial_ledger if item["type"] == "PURCHASE"]) == 1
    assert session.market.teams["FLA"].reserved_cents == 0
    assert session.market_phase == "MARKET_REVIEW"


def test_snapshot_restoration_preserves_unconfirmed_rights_and_charges_once() -> None:
    async def scenario() -> tuple[dict[str, object], MarketSession]:
        service, session, offer_id = _selection_service()
        payload = service.export_room("lifecycle")
        restored = MarketService()
        restored_session = restored.restore_room(payload, _noop, on_progressed=_noop)
        result = await restored.confirm_selection("lifecycle", "FLA", [offer_id], "restored-confirm")
        if restored_session.timer_task:
            restored_session.timer_task.cancel()
        return result, restored_session

    result, session = asyncio.run(scenario())
    team = session.market.teams["FLA"]
    assert result["status"] == "COMPLETED"
    assert team.reserved_cents == 0
    assert len([item for item in team.financial_ledger if item["type"] == "PURCHASE"]) == 1
    assert session.market.selection_complete
    assert session.market_phase == "MARKET_REVIEW"


def test_absent_coach_is_confirmed_at_controlled_deadline_without_penalty() -> None:
    async def scenario() -> MarketSession:
        now = [100.0]

        async def advance(seconds: float) -> None:
            now[0] += seconds

        catalog = synthetic_catalog("FIVE_A_SIDE", teams=20)
        market = InitialMarket(catalog, "FIVE_A_SIDE", {"FLA": 5_000_000_000}, withdrawal_penalty_percent=10)
        for index, player in enumerate(list(market.catalog.values())[:2]):
            market.submit_offer("FLA", player.id, player.market_value_cents, f"absent-{index}")
        market.resolve()
        service = MarketService(clock=lambda: now[0], sleep=advance)
        service.registry._markets["absent"] = market
        service.registry._locks["absent"] = asyncio.Lock()
        session = MarketSession(
            "absent", 90.0, market, finalized=True, human_clubs={"FLA"},
            managers={"FLA": "Ausente"}, selection_ends_at=105.0,
            selection_duration_seconds=5, market_phase="MARKET_SELECTION", on_progressed=_noop,
        )
        service.sessions["absent"] = session
        session.timer_task = asyncio.create_task(service._phase_deadline_loop(session))
        await asyncio.wait_for(session.timer_task, timeout=1)
        return session

    session = asyncio.run(scenario())
    assert session.market_phase == "MARKET_REVIEW"
    assert session.market.confirmations["FLA"]["automatic"] is True
    assert session.market.confirmations["FLA"]["penalty_cents"] == 0
    assert not any(item["type"] == "WITHDRAWAL_PENALTY" for item in session.market.teams["FLA"].financial_ledger)
