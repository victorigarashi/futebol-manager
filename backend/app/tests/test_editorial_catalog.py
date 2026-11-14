from __future__ import annotations

from pathlib import Path

from app.domain.catalog import load_catalog
from app.domain.clubs import CLUBS
from app.domain.market import InitialMarket

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_editorial_catalog_keeps_real_and_synthetic_players_distinct() -> None:
    catalog = load_catalog(PROJECT_ROOT / "data" / "catalogs" / "players.json")
    assert catalog is not None
    editorial = [player for player in catalog.players if player.source == "EDITORIAL_ESTIMATE"]
    synthetic = [player for player in catalog.players if player.source == "synthetic-career"]
    assert len(editorial) == 176
    assert len(synthetic) == 144
    assert {player.id for player in editorial}.isdisjoint({player.id for player in synthetic})
    assert all(player.name.startswith("Genérico ") for player in synthetic)
    assert all(not player.name.startswith("Genérico ") for player in editorial)
    assert all(player.verification_status == "CORROBORATED_IDENTITY_CLUB_POSITION" for player in editorial)
    assert any(player.age is None for player in editorial)
    assert any(player.attributes for player in editorial)


def test_editorial_catalog_is_viable_and_finishes_eleven_a_side_rosters() -> None:
    catalog = load_catalog(PROJECT_ROOT / "data" / "catalogs" / "players.json")
    assert catalog is not None
    market = InitialMarket(
        catalog,
        "ELEVEN_A_SIDE",
        {club.code: 10_000_000_000 for club in CLUBS},
    )
    assert market.viable().viable
    market.finalize_rosters("editorial-catalog-test")
    assert all(len(team.roster) == 16 for team in market.teams.values())
    assert all(
        any(market.catalog[player_id].source == "synthetic-career" for player_id in team.roster)
        for team in market.teams.values()
    )
