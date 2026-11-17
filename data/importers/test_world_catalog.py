"""World catalog: original editorial ratings, provenance and no EA data."""

import json
from pathlib import Path

from data.importers.world_catalog_builder import age_on, editorial_rating, short_club

CATALOG = Path(__file__).resolve().parents[1] / "catalogs" / "world_players.json"


def test_editorial_rating_is_monotonic_bounded_and_age_aware():
    assert editorial_rating(1_000_000, 27)[0] == 68
    assert editorial_rating(200_000_000, 26)[0] > editorial_rating(20_000_000, 26)[0] > editorial_rating(5_000_000, 26)[0]
    young, veteran = editorial_rating(30_000_000, 19), editorial_rating(30_000_000, 34)
    assert young[0] < veteran[0] and young[1] > young[0]  # price includes the youngster's future
    assert 55 <= editorial_rating(10**10, 25)[0] <= 93 and editorial_rating(10, 25)[0] >= 55
    assert editorial_rating(10_000_000, None)[1] == editorial_rating(10_000_000, None)[0]  # no invented potential


def test_helpers():
    assert age_on("2000-12-01 00:00:00") == 25 and age_on("") is None
    assert short_club("Società Sportiva Lazio S.p.A.") == "Società Sportiva Lazio"


def test_shipped_catalog_has_provenance_and_no_ea_material():
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    provenance = catalog["provenance"]
    assert provenance["identity"]["license"] == "CC0-1.0"
    assert provenance["ratings"]["kind"] == "EDITORIAL_ESTIMATE" and "Não são ratings oficiais" in provenance["ratings"]["notice"]
    players = catalog["players"]
    assert len(players) > 1000 and len({p["id"] for p in players}) == len(players)
    assert all(p["club_code"] == "WLD" and p["club_name"] and not p.get("photo_url") and p["attributes"] == {} for p in players)
    assert all(55 <= p["overall"] <= p["potential"] <= 95 for p in players)
    assert not any("ea" == key.lower() or "fc26" in key.lower() for p in players for key in p["source_ids"])
