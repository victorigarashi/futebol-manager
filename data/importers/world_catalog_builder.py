"""International catalog for the Draft "Mundial": identity from a CC0 source, ratings our own.

Why not EA SPORTS FC 26 ratings
-------------------------------
EA's ratings are EA's editorial work. Public mirrors (e.g. a Kaggle upload declaring
CC BY 4.0) cannot grant rights the uploader does not hold, and the official ratings
site offers no redistribution licence. So no EA rating, attribute, image, logo or
"FC 26" branding is imported.

What is imported
----------------
Factual identity only — name, citizenship, date of birth, position, current club
(as of the source snapshot) and market value — from dcaribou/transfermarkt-datasets
(CC0-1.0). The file checksums must match ``data/catalogs/staging/SOURCE_MANIFEST.json``.

Editorial rating model (BRASILEIRAO_MANAGER_WORLD_RATING_V1)
------------------------------------------------------------
An original, documented estimate — explicitly *not* an EA rating:

* base = 68 + 9.5 · log10(market value / €1 m)   (€1 m ≈ 68, €20 m ≈ 80, €100 m ≈ 87)
* age: young players' prices carry their future (−1.2 per year under 23);
  veterans' prices fall faster than their level (+1.0 per year over 30, max +5)
* overall = clamp(base + age adjustment, 55, 93)
* potential = overall + 1.5 per year under 24 (max 95)
* face attributes are left empty: the game derives a transparent per-position
  profile at run time and marks it as estimated.

Run offline:  python -I -m data.importers.world_catalog_builder <source dir> <output json>
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
import sys
from datetime import date
from pathlib import Path

MODEL_VERSION = "BRASILEIRAO_MANAGER_WORLD_RATING_V1"
SOURCE = "TRANSFERMARKT_DATASETS_CC0_IDENTITY+EDITORIAL_RATING_V1"
SNAPSHOT = "2026-07-06"
REFERENCE_DATE = date(2026, 11, 17)
MIN_VALUE_EUR = 5_000_000
EUR_TO_BRL = 6  # fixed editorial conversion (documented), not a live exchange rate
POSITIONS = {"Goalkeeper": "GK", "Defender": "DF", "Midfield": "MF", "Attack": "ST"}
SECONDARY = {
    "Defensive Midfield": ["DF"], "Attacking Midfield": ["ST"], "Left Winger": ["MF"], "Right Winger": ["MF"],
    "Left Midfield": ["ST"], "Right Midfield": ["ST"], "Second Striker": ["MF"],
}
LEGAL_SUFFIXES = (" S.p.A.", " SpA", " S.A.D.", " SAD", " e.V.", " FC", " F.C.", " Football Club", " AFC", " A.F.C.")


def age_on(birth: str, reference: date = REFERENCE_DATE) -> int | None:
    if not birth:
        return None
    born = date.fromisoformat(birth[:10])
    return reference.year - born.year - ((reference.month, reference.day) < (born.month, born.day))


def editorial_rating(value_eur: float, age: int | None) -> tuple[int, int]:
    base = 68 + 9.5 * math.log10(max(value_eur, 100_000) / 1_000_000)
    adjust = 0.0
    if age is not None:
        if age < 23:
            adjust -= (23 - age) * 1.2
        elif age > 30:
            adjust += min(5.0, (age - 30) * 1.0)
    overall = max(55, min(93, round(base + adjust)))
    potential = overall if age is None else min(95, max(overall, round(overall + max(0, 24 - age) * 1.5)))
    return overall, potential


def short_club(name: str) -> str:
    for suffix in LEGAL_SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return " ".join(name.split())[:80]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(source_dir: Path, manifest_path: Path) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    players_file = source_dir / "players.csv.gz"
    expected = manifest["files"]["players.csv.gz"]["sha256"]
    if sha256(players_file) != expected:
        raise ValueError("players.csv.gz não confere com o checksum do manifesto auditado.")
    clubs = {}
    with gzip.open(source_dir / "clubs.csv.gz", "rt", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            clubs[row["club_id"]] = row["name"]
    players = []
    issues = []
    with gzip.open(players_file, "rt", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if not row["last_season"] or int(row["last_season"]) < 2025 or not row["market_value_in_eur"]:
                continue
            value = float(row["market_value_in_eur"])
            position = POSITIONS.get(row["position"])
            if value < MIN_VALUE_EUR or not position:
                continue
            age = age_on(row["date_of_birth"])
            if age is not None and not 15 <= age <= 45:
                issues.append(f"{row['player_id']}: idade fora do intervalo ({age}).")
                continue
            overall, potential = editorial_rating(value, age)
            club = short_club(clubs.get(row["current_club_id"]) or row["current_club_name"] or "Sem clube")
            players.append({
                "id": f"WLD-TM-{row['player_id']}", "name": " ".join(row["name"].split()), "club_code": "WLD",
                "club_name": club, "age": age, "nationality": row["country_of_citizenship"] or None,
                "verification_status": f"IDENTITY_SOURCE_SNAPSHOT_{SNAPSHOT}",
                "position": position, "secondary_positions": SECONDARY.get(row["sub_position"], []),
                "overall": overall, "potential": potential, "attributes": {},
                "market_value_cents": int(value * EUR_TO_BRL * 100), "source": SOURCE,
                "source_version": f"{MODEL_VERSION}/{SNAPSHOT}",
                "source_ids": {"transfermarkt": row["player_id"], "competition": row["current_club_domestic_competition_id"]},
            })
    players.sort(key=lambda p: (-p["overall"], p["id"]))
    return {
        "catalog_version": f"world-{SNAPSHOT}-{MODEL_VERSION}",
        "source": SOURCE, "source_version": SNAPSHOT,
        "provenance": {
            "identity": {"source": "dcaribou/transfermarkt-datasets", "license": "CC0-1.0", "snapshot": SNAPSHOT,
                         "sha256": expected, "fields": ["name", "nationality", "date_of_birth", "position", "club", "market_value"]},
            "ratings": {"model": MODEL_VERSION, "kind": "EDITORIAL_ESTIMATE",
                        "notice": "Estimativas editoriais próprias do Brasileirão Manager. Não são ratings oficiais da EA SPORTS FC."},
            "excluded": ["EA SPORTS FC ratings e atributos", "imagens e fotos", "escudos e marcas"],
            "distribution": "AUTHORIZED: dados de identidade CC0 + avaliação original do projeto",
            "review_status": "AUTOMATED_IMPORT_PENDING_EDITORIAL_REVIEW",
            "issues": issues,
        },
        "players": players,
    }


def main(argv: list[str]) -> None:
    source_dir, output = Path(argv[1]), Path(argv[2])
    manifest = Path(__file__).resolve().parents[1] / "catalogs" / "staging" / "SOURCE_MANIFEST.json"
    catalog = build(source_dir, manifest)
    output.write_text(json.dumps(catalog, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"{len(catalog['players'])} atletas -> {output}")


if __name__ == "__main__":
    main(sys.argv)
