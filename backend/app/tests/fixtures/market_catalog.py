from app.domain.catalog import CatalogPlayer, PlayerCatalog
from app.domain.market import FORMATION_SLOTS, InitialMarket


def synthetic_catalog(mode: str, teams: int = 2, price_cents: int = 100_000_000) -> PlayerCatalog:
    """Synthetic test-only records; never loaded from data/catalogs in production."""
    players: list[CatalogPlayer] = []
    sequence = 0
    for position, per_team in FORMATION_SLOTS[mode].items():
        for _ in range(per_team * teams):
            sequence += 1
            players.append(CatalogPlayer(id=f"test-{position}-{sequence}", name=f"Teste {position} {sequence}", club_code="FLA", age=24, position=position, overall=70, potential=75, market_value_cents=price_cents, source="test-fixture", source_version="1"))
    return PlayerCatalog(catalog_version="test", source="test-fixture", source_version="1", players=players)


def complete_test_market(market: InitialMarket, room_id: str = "test-room") -> None:
    """Run deterministic automatic choices for fixtures that need full squads."""
    market.resolve()
    for club in market.teams:
        market.confirm_selection(club, list(market.commitments[club]), f"{room_id}:auto:{club}", automatic=True)
    market.prepare_reassignment()
    while market.current_reassignment(set()) is not None:
        pass
    market.finalize_rosters(room_id)
