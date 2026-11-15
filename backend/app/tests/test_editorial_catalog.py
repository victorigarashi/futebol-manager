from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from app.domain.catalog import load_catalog
from app.domain.clubs import CLUBS
from app.domain.market import InitialMarket

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CATALOG = PROJECT_ROOT / "data" / "catalogs" / "players.json"


def test_squad_list_catalog_has_unique_real_players_with_photos() -> None:
    catalog = load_catalog(CATALOG)
    assert catalog is not None
    players = catalog.players
    assert len(players) == 320
    assert len({p.id for p in players}) == len(players)
    # No duplicated athlete: one entry per source ID and per name within a club.
    assert len({p.source_ids["fcmania"] for p in players}) == len(players)
    assert not [k for k, n in Counter((p.club_code, p.name) for p in players).items() if n > 1]
    assert not any(p.source == "synthetic-career" or p.name.startswith("Genérico ") for p in players)
    assert all(p.photo_url and p.photo_url.startswith("https://") for p in players)
    per_club = Counter(p.club_code for p in players)
    assert set(per_club) == {club.code for club in CLUBS}
    assert set(per_club.values()) == {16}
    assert all(Counter(p.position for p in players if p.club_code == club.code)["GK"] >= 2 for club in CLUBS)


def test_previous_catalog_ids_are_preserved_for_matched_players() -> None:
    catalog = load_catalog(CATALOG)
    assert catalog is not None
    kept = [p for p in catalog.players if p.id.startswith("BR26-")]
    assert len(kept) > 100
    assert all(p.attributes for p in kept)


def test_clubs_file_covers_every_club_with_a_crest() -> None:
    clubs = json.loads((PROJECT_ROOT / "data" / "catalogs" / "clubs.json").read_text(encoding="utf-8"))["clubs"]
    assert {c["code"] for c in clubs} == {club.code for club in CLUBS}
    assert all(c["crest_url"].startswith("https://") for c in clubs)


def test_catalog_is_viable_and_finishes_eleven_a_side_rosters() -> None:
    catalog = load_catalog(CATALOG)
    assert catalog is not None
    market = InitialMarket(catalog, "ELEVEN_A_SIDE", {club.code: 10_000_000_000 for club in CLUBS})
    assert market.viable().viable
    market.finalize_rosters("catalog-test")
    assert all(len(team.roster) == 16 for team in market.teams.values())
