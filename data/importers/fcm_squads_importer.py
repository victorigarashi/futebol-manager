"""Build the operational catalog from the FC Mania squad CSVs supplied by the project owner.

Inputs (local files, no network access):
  * players CSV: team_id, team, formation, role, player_id, name, position_site, position,
    shirt_number, overall, potential, age, nationality, team_crest_url, player_photo_url, source
  * teams CSV:   team_id, team, formation, crest_url

Rules:
  * one catalog entry per FC Mania ``player_id`` (duplicates are rejected, never merged silently);
  * a player already in the previous catalog keeps the same game ID (matched by normalized
    name + club, then by a name that is unique in both files), so rooms and history stay valid;
    their editorial component attributes are kept, shifted by the overall difference;
  * every other player gets the stable ID ``FCM-<player_id>``;
  * synthetic "Genérico" fillers are dropped — each club has 16 real players;
  * photos and crests are stored as the URLs supplied in the CSV (not downloaded).

Usage (repository root):
  python3 -m data.importers.fcm_squads_importer \
      --players /path/brasileirao_fcm_titulares_reservas.csv --teams /path/brasileirao_fcm_times.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = ROOT / "data" / "catalogs" / "players.json"
CLUBS_PATH = ROOT / "data" / "catalogs" / "clubs.json"
SUMMARY_PATH = ROOT / "data" / "catalogs" / "fcm_import_summary.json"
FRONTEND_CLUBS_PATH = ROOT / "frontend" / "src" / "lib" / "clubMedia.ts"

SOURCE = "FC_MANIA_FCM27"
SOURCE_VERSION = "fcm27-2026-11-15"
CATALOG_VERSION = "brasileirao-fcm27-2026-11-15"

CLUB_CODES = {
    "Flamengo": "FLA", "Palmeiras": "PAL", "Corinthians": "COR", "São Paulo": "SAO",
    "Santos": "SAN", "Vasco da Gama": "VAS", "Vasco": "VAS", "Fluminense": "FLU",
    "Botafogo": "BOT", "Cruzeiro": "CRU", "Atlético-MG": "CAM", "Grêmio": "GRE",
    "Internacional": "INT", "Bahia": "BAH", "Vitória": "VIT", "Athletico-PR": "CAP",
    "Coritiba": "CFC", "RB Bragantino": "RBB", "Red Bull Bragantino": "RBB",
    "Mirassol": "MIR", "Chapecoense": "CHA", "Remo": "REM",
}
POSITIONS = {"GK": "GK", "DF": "DF", "MF": "MF", "FW": "ST", "ST": "ST"}
# Detailed site position -> game position. The game has four lines (GK/DF/MF/ST) and, like the
# previous importers (LW/RW -> ST), wide attackers and wide midfielders play on the "ST" line.
SITE_POSITIONS = {"GOL": "GK", "ZAG": "DF", "LD": "DF", "LE": "DF", "VOL": "MF", "MC": "MF",
                  "MEI": "MF", "MD": "ST", "ME": "ST", "PD": "ST", "PE": "ST", "ATA": "ST"}
MIN_STRIKERS = 3  # 11x11 market needs three "ST" per club
NATIONALITIES = {"Brasil": "Brazil", "Uruguai": "Uruguay", "Colômbia": "Colombia",
                 "Paraguai": "Paraguay", "Itália": "Italy", "Equador": "Ecuador",
                 "Venezuela": "Venezuela", "Peru": "Peru", "Bolívia": "Bolivia",
                 "Espanha": "Spain", "Portugal": "Portugal", "Alemanha": "Germany",
                 "França": "France", "Holanda": "Netherlands", "Bélgica": "Belgium",
                 "Inglaterra": "England", "Estados Unidos": "United States", "México": "Mexico"}
ATTRIBUTE_KEYS = ("pace", "shooting", "passing", "dribbling", "defending", "physical")


def price_cents(overall: int, potential: int, age: int, position: str) -> int:
    """Internal game price (never a real valuation), fitted to the previous catalog's curve:
    ~R$ 4,4 mi at 63, ~R$ 20 mi at 72, ~R$ 55 mi at 78 and ~R$ 150 mi at 84."""
    quality = 0.75 * overall + 0.25 * potential
    age_factor = max(0.70, min(1.20, 1.0 + (24 - age) / 100))
    position_factor = {"GK": 0.95, "DF": 1.0, "MF": 1.05, "ST": 1.10}[position]
    reais = 4_400_000 * math.exp(0.17 * (quality - 63)) * age_factor * position_factor
    return round(reais / 10_000) * 1_000_000  # rounded to R$ 10 mil


def normalize(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join(plain.lower().replace("-", " ").replace(".", " ").split())


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(handle)]


def _int(row: dict[str, str], field: str, low: int, high: int) -> int:
    value = int(row[field])
    if not low <= value <= high:
        raise ValueError(f"{row['name']}: {field}={value} fora de [{low}, {high}]")
    return value


def build(players_csv: Path, teams_csv: Path, previous: dict) -> tuple[dict, dict, dict]:
    rows = read_csv(players_csv)
    teams = read_csv(teams_csv)
    unknown = sorted({r["team"] for r in rows + teams} - set(CLUB_CODES))
    if unknown:
        raise ValueError(f"Clubes sem código no jogo: {unknown}")
    dup = [pid for pid, n in Counter(r["player_id"] for r in rows).items() if n > 1]
    if dup:
        raise ValueError(f"player_id duplicado no CSV: {dup}")

    old = [p for p in previous.get("players", []) if p.get("source") != "synthetic-career"]
    by_name_club = {(normalize(p["name"]), p["club_code"]): p for p in old}
    old_names = Counter(normalize(p["name"]) for p in old)
    new_names = Counter(normalize(r["name"]) for r in rows)
    by_unique_name = {normalize(p["name"]): p for p in old if old_names[normalize(p["name"])] == 1}

    players: list[dict] = []
    used_old: set[str] = set()
    kept_ids = 0
    for row in rows:
        club = CLUB_CODES[row["team"]]
        site = SITE_POSITIONS.get(row["position_site"].upper())
        position = site or POSITIONS[row["position"].upper()]
        key = normalize(row["name"])
        match = by_name_club.get((key, club))
        if match is None and new_names[key] == 1:
            match = by_unique_name.get(key)
        if match is not None and match["id"] in used_old:
            match = None
        overall = _int(row, "overall", 1, 99)
        potential = max(overall, _int(row, "potential", 1, 99))
        age = _int(row, "age", 14, 50)
        listed = POSITIONS[row["position"].upper()]
        secondary = [listed] if listed != position else []
        attributes: dict[str, int] = {}
        if match is not None:
            used_old.add(match["id"])
            kept_ids += 1
            shift = overall - int(match["overall"])
            attributes = {k: max(1, min(99, int(v) + shift)) for k, v in (match.get("attributes") or {}).items()}
            secondary = list(dict.fromkeys(secondary + [s for s in match.get("secondary_positions", []) if s != position]))
        players.append({
            "id": match["id"] if match else f"FCM-{row['player_id']}",
            "name": row["name"],
            "club_code": club,
            "age": age,
            "position": position,
            "nationality": NATIONALITIES.get(row["nationality"], row["nationality"]),
            "verification_status": "SUPPLIED_SQUAD_LIST",
            "secondary_positions": secondary,
            "overall": overall,
            "potential": potential,
            "attributes": attributes,
            "market_value_cents": price_cents(overall, potential, age, position),
            "source": SOURCE,
            "source_version": SOURCE_VERSION,
            "source_ids": {"fcmania": row["player_id"]},
            "shirt_number": int(row["shirt_number"]) if row["shirt_number"].isdigit() else None,
            "squad_role": "STARTER" if row["role"].upper() == "TITULAR" else "RESERVE",
            "photo_url": row["player_photo_url"] or None,
            "_site": row["position_site"].upper(),
        })

    # A club short of "ST" players gets its best attacking midfielders (MEI) on that line.
    promoted = []
    for club in sorted({p["club_code"] for p in players}):
        squad = [p for p in players if p["club_code"] == club]
        short = MIN_STRIKERS - sum(p["position"] == "ST" for p in squad)
        meias = sorted((p for p in squad if p["position"] == "MF" and p["_site"] == "MEI"), key=lambda p: -p["overall"])
        for player in meias[:max(0, short)]:
            player["position"], player["secondary_positions"] = "ST", ["MF"]
            player["market_value_cents"] = price_cents(player["overall"], player["potential"], player["age"], "ST")
            promoted.append(player["name"])
    for player in players:
        player.pop("_site")

    ids = Counter(p["id"] for p in players)
    if any(n > 1 for n in ids.values()):
        raise ValueError("IDs de jogo duplicados após a conciliação.")

    clubs = {}
    for team in teams:
        code = CLUB_CODES[team["team"]]
        clubs[code] = {"code": code, "name": team["team"], "formation": team["formation"],
                       "crest_url": team["crest_url"] or None, "source_ids": {"fcmania": team["team_id"]}}
    per_club = Counter(p["club_code"] for p in players)
    catalog = {"catalog_version": CATALOG_VERSION, "source": SOURCE, "source_version": SOURCE_VERSION, "players": players}
    summary = {
        "catalog_version": CATALOG_VERSION,
        "players": len(players),
        "clubs": len(clubs),
        "players_per_club": dict(sorted(per_club.items())),
        "kept_existing_ids": kept_ids,
        "new_ids": len(players) - kept_ids,
        "previous_real_players_not_in_list": len(old) - len(used_old),
        "synthetic_players_removed": sum(1 for p in previous.get("players", []) if p.get("source") == "synthetic-career"),
        "positions": dict(Counter(p["position"] for p in players)),
        "with_photo": sum(1 for p in players if p["photo_url"]),
        "attacking_midfielders_on_st_line": promoted,
    }
    return catalog, {"clubs": [clubs[c] for c in sorted(clubs)]}, summary


def write_frontend_media(clubs: dict) -> None:
    entries = ",\n".join(f'  {c["code"]}: {json.dumps(c["crest_url"])}' for c in clubs["clubs"] if c["crest_url"])
    FRONTEND_CLUBS_PATH.write_text(
        "// Generated by data/importers/fcm_squads_importer.py — do not edit by hand.\n"
        "export const CLUB_CREST_URLS: Record<string, string> = {\n" + entries + ",\n};\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--players", type=Path, required=True)
    parser.add_argument("--teams", type=Path, required=True)
    args = parser.parse_args()
    previous = json.loads(CATALOG_PATH.read_text(encoding="utf-8")) if CATALOG_PATH.exists() else {}
    catalog, clubs, summary = build(args.players, args.teams, previous)
    CATALOG_PATH.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    CLUBS_PATH.write_text(json.dumps(clubs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_frontend_media(clubs)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
