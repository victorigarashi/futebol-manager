"""Explicitly synthetic, local-only catalog for development and tests."""

from app.domain.catalog import CatalogPlayer, PlayerCatalog
from app.domain.clubs import CLUBS


def create_demo_catalog() -> PlayerCatalog:
    players = []
    positions = ("GK", "GK", "DF", "DF", "DF", "DF", "DF", "MF", "MF", "MF", "MF", "ST", "ST", "ST", "ST", "ST", "MF", "DF", "ST", "GK")
    for club in CLUBS:
        for index, position in enumerate(positions, 1):
            overall = 55 + (club.sort_order * 7 + index * 3) % 23
            players.append(CatalogPlayer(id=f"demo-{club.code}-{index:02}", name=f"DEMO {club.code} {index:02}", club_code=club.code, age=19 + index % 15, position=position, overall=overall, potential=min(90, overall + 5), market_value_cents=10_000_000, source="synthetic-demo", source_version="1"))
    return PlayerCatalog(catalog_version="demo-1", source="synthetic-demo", source_version="1", players=players)
