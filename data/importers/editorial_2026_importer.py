"""Import the user-supplied 2026 editorial player CSV without inventing facts.

The source's ratings and internal values are editorial estimates. Records with
corroborated identity, current club and position become operational entries;
age and nationality remain optional metadata and are never inferred. Every
other source row is retained in a review file. Synthetic supplements are
visibly marked and are never presented as real players.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path


CATALOG_VERSION = "brasileirao-editorial-2026-11-14"
EDITORIAL_SOURCE = "EDITORIAL_ESTIMATE"
EDITORIAL_SOURCE_VERSION = "editorial-2026-11-14"
INTERNAL_EUR_TO_BRL = Decimal("5.50")

CLUB_CODES = {
    "Flamengo": "FLA", "Palmeiras": "PAL", "Corinthians": "COR",
    "São Paulo": "SAO", "Santos": "SAN", "Vasco": "VAS",
    "Fluminense": "FLU", "Botafogo": "BOT", "Cruzeiro": "CRU",
    "Atlético-MG": "CAM", "Grêmio": "GRE", "Internacional": "INT",
    "Bahia": "BAH", "Vitória": "VIT", "Athletico-PR": "CAP",
    "Coritiba": "CFC", "Red Bull Bragantino": "RBB", "Mirassol": "MIR",
    "Chapecoense": "CHA", "Remo": "REM",
}
POSITION_ALIASES = {
    "GK": "GK", "CB": "DF", "LB": "DF", "RB": "DF", "DF": "DF",
    "DM": "MF", "CM": "MF", "AM": "MF", "MF": "MF", "LW": "ST",
    "RW": "ST", "ST": "ST", "FW": "ST",
}
TARGET_BY_POSITION = {"GK": 2, "DF": 6, "MF": 4, "ST": 4}
MINIMUM_BY_POSITION = {"GK": 2, "DF": 4, "MF": 3, "ST": 3}
REQUIRED_FIELDS = {
    "id", "name", "club", "age", "nationality", "position",
    "secondary_positions", "overall", "potential", "pace", "shooting",
    "passing", "dribbling", "defending", "physical", "gk_diving",
    "gk_handling", "gk_reflexes", "gk_positioning", "market_value_eur",
    "rating_source",
}


@dataclass(frozen=True)
class EditorialImport:
    catalog: dict[str, object]
    approved_attributes: list[dict[str, object]]
    review_rows: list[dict[str, str]]
    summary: dict[str, object]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _position(value: str) -> str:
    try:
        return POSITION_ALIASES[value.strip().upper()]
    except KeyError as error:
        raise ValueError(f"posição não suportada: {value}") from error


def _secondary(value: str, primary: str) -> list[str]:
    positions = []
    for item in (value or "").split("|"):
        if item.strip():
            normalized = _position(item)
            if normalized != primary and normalized not in positions:
                positions.append(normalized)
    return positions


def _integer(value: str, field: str, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise ValueError(f"{field} inválido: {value}") from error
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{field} fora do intervalo: {value}")
    return parsed


def _value_cents(value_eur: str) -> int:
    try:
        value = Decimal(value_eur)
    except Exception as error:  # Decimal errors vary by Python implementation.
        raise ValueError(f"market_value_eur inválido: {value_eur}") from error
    if value < 0:
        raise ValueError("market_value_eur negativo")
    return int((value * INTERNAL_EUR_TO_BRL * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _review_index(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    indexed = {row.get("id", ""): row for row in rows}
    if "" in indexed or len(indexed) != len(rows):
        raise ValueError("arquivo de revisão contém IDs ausentes ou duplicados")
    return indexed


def _evidence_index(path: Path) -> dict[str, dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("players", [])
    if not isinstance(rows, list):
        raise ValueError("evidência precisa ter uma lista players")
    indexed = {str(row.get("id", "")): row for row in rows if isinstance(row, dict)}
    if len(indexed) != len(rows):
        raise ValueError("evidência contém IDs ausentes ou duplicados")
    return indexed


def _review_reason(row: dict[str, str], flags: set[str], evidence: dict[str, object] | None) -> str | None:
    reasons: list[str] = []
    if row.get("rating_source") != EDITORIAL_SOURCE:
        reasons.append("rating_source deve ser EDITORIAL_ESTIMATE")
    if row.get("age") and not 14 <= int(row["age"]) <= 50:
        reasons.append("idade fora do intervalo")
    if evidence is None or evidence.get("status") != "CORROBORATED":
        reasons.append("clube/identidade sem evidência corroborada")
    return "; ".join(reasons) if reasons else None


def import_editorial_2026(
    players_path: Path, review_path: Path, evidence_path: Path
) -> EditorialImport:
    players = _read_csv(players_path)
    reviews = _review_index(_read_csv(review_path))
    evidence = _evidence_index(evidence_path)
    if not players:
        raise ValueError("CSV editorial sem jogadores")
    if set(players[0]) != REQUIRED_FIELDS:
        missing = sorted(REQUIRED_FIELDS - set(players[0]))
        extra = sorted(set(players[0]) - REQUIRED_FIELDS)
        raise ValueError(f"colunas editoriais divergentes; faltam={missing}; extras={extra}")
    ids = [row.get("id", "") for row in players]
    if not all(ids) or len(ids) != len(set(ids)):
        raise ValueError("CSV editorial contém IDs ausentes ou duplicados")
    if set(ids) != set(reviews):
        raise ValueError("CSV editorial e CSV de revisão têm conjuntos de IDs diferentes")

    approved: list[dict[str, object]] = []
    attributes: list[dict[str, object]] = []
    pending: list[dict[str, str]] = []
    for row in players:
        if row["club"] not in CLUB_CODES:
            raise ValueError(f"clube não mapeado: {row['club']}")
        flags = {flag for flag in reviews[row["id"]].get("review_flags", "").split(";") if flag}
        reason = _review_reason(row, flags, evidence.get(row["id"]))
        try:
            primary = _position(row["position"])
            overall = _integer(row["overall"], "overall", 1, 99)
            potential = _integer(row["potential"], "potential", 1, 99)
            values = {field: _integer(row[field], field, 1, 99) for field in (
                "pace", "shooting", "passing", "dribbling", "defending", "physical"
            )}
            goalkeeper_values = {
                field: _integer(row[field], field, 1, 99)
                for field in ("gk_diving", "gk_handling", "gk_reflexes", "gk_positioning")
                if row.get(field)
            }
            value_cents = _value_cents(row["market_value_eur"])
        except ValueError as error:
            reason = "; ".join(filter(None, [reason, str(error)]))
        if reason:
            pending.append({**row, "review_flags": ";".join(sorted(flags)), "decision": "NEEDS_REVIEW", "reason": reason})
            continue
        age = _integer(row["age"], "age", 14, 50) if row.get("age") else None
        nationality = row["nationality"] or None
        # This review flag marks an assumed default, not a verified nationality.
        if "nationality_assumed_default_Brazil" in flags:
            nationality = None
        player = {
            "id": row["id"], "name": row["name"], "club_code": CLUB_CODES[row["club"]],
            "age": age, "position": primary, "nationality": nationality,
            "verification_status": "CORROBORATED_IDENTITY_CLUB_POSITION",
            "secondary_positions": _secondary(row["secondary_positions"], primary),
            "overall": overall, "potential": potential, "attributes": {**values, **goalkeeper_values},
            "market_value_cents": value_cents, "source": EDITORIAL_SOURCE,
            "source_version": EDITORIAL_SOURCE_VERSION,
        }
        approved.append(player)
        attributes.append({
            "id": row["id"], "name": row["name"], "club_code": CLUB_CODES[row["club"]],
            "age": age, "age_status": "CONFIRMED" if age is not None else "UNKNOWN",
            "nationality": nationality,
            "nationality_status": "SUPPLIED" if nationality else "UNKNOWN",
            "rating_source": EDITORIAL_SOURCE,
            "rating_status": "EDITORIAL_ESTIMATE", "overall": overall, "potential": potential,
            "market_value_eur_internal": row["market_value_eur"], "attributes": values,
            "goalkeeper_attributes": goalkeeper_values,
            "evidence": evidence[row["id"]],
        })

    catalog = {
        "catalog_version": CATALOG_VERSION,
        "source": "EDITORIAL_ESTIMATE_WITH_SYNTHETIC_SUPPLEMENTS",
        "source_version": EDITORIAL_SOURCE_VERSION,
        "players": supplement_with_synthetic(approved),
    }
    summary = {
        "catalog_version": CATALOG_VERSION, "input_rows": len(players),
        "real_players_approved": len(approved), "players_needing_review": len(pending),
        "synthetic_supplements": len(catalog["players"]) - len(approved),
        "total_operational_players": len(catalog["players"]),
        "approved_by_club": dict(sorted(Counter(player["club_code"] for player in approved).items())),
        "review_by_club": dict(sorted(Counter(row["club"] for row in pending).items())),
        "note": "Ratings reais aprovados são EDITORIAL_ESTIMATE; jogadores synthetic-career não são atletas reais. Idades e nacionalidades ausentes permanecem null e não habilitam progressão etária.",
    }
    return EditorialImport(catalog, attributes, pending, summary)


def supplement_with_synthetic(players: list[dict[str, object]]) -> list[dict[str, object]]:
    """Fill each club to an explicit 16-player 11x11-safe roster."""
    result = list(players)
    for club in CLUB_CODES.values():
        club_players = [row for row in result if row["club_code"] == club]
        if len(club_players) > 16:
            raise ValueError(f"{club} possui mais de 16 jogadores reais confirmados; revisão manual necessária")
        counts = Counter(str(row["position"]) for row in club_players)
        desired = dict(MINIMUM_BY_POSITION)
        minimum_total = sum(max(counts[position], desired[position]) for position in desired)
        if minimum_total > 16:
            raise ValueError(f"{club} não cabe em 16 atletas mantendo as vagas mínimas")
        remaining = 16 - minimum_total
        for position in ("DF", "MF", "ST", "GK"):
            desired[position] = max(counts[position], desired[position])
            add = min(remaining, max(0, TARGET_BY_POSITION[position] - desired[position]))
            desired[position] += add
            remaining -= add
        for position in ("DF", "MF", "ST", "GK"):
            if remaining <= 0:
                break
            desired[position] += remaining
            remaining = 0
        for position, target in desired.items():
            for index in range(counts[position] + 1, target + 1):
                seed = sum((offset + 1) * ord(char) for offset, char in enumerate(f"{club}:{position}:{index}"))
                result.append({
                    "id": f"SYN-2026-{club}-{position}-{index:02}",
                    "name": f"Genérico {club} {position} {index:02}",
                    "club_code": club, "age": 18 + seed % 12, "position": position,
                    "secondary_positions": [], "overall": 48 + seed % 13,
                    "potential": min(76, 55 + seed % 18), "market_value_cents": 0,
                    "source": "synthetic-career", "source_version": "generated-v1",
                })
    return result


def write_import(result: EditorialImport, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "players.json").write_text(json.dumps(result.catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "editorial_2026_approved_attributes.json").write_text(json.dumps({"rating_source": EDITORIAL_SOURCE, "players": result.approved_attributes}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "editorial_2026_import_summary.json").write_text(json.dumps(result.summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    review_dir = output_dir / "review"
    review_dir.mkdir(exist_ok=True)
    fields = list(result.review_rows[0]) if result.review_rows else ["id", "decision", "reason"]
    with (review_dir / "editorial_2026_needs_review.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(result.review_rows)
    report_dir = output_dir / "reports"
    report_dir.mkdir(exist_ok=True)
    coverage = []
    for club in CLUB_CODES.values():
        club_players = [player for player in result.catalog["players"] if player["club_code"] == club]
        real = [player for player in club_players if player["source"] == EDITORIAL_SOURCE]
        positions = Counter(player["position"] for player in club_players)
        coverage.append({
            "club_code": club,
            "editorial_real_players": len(real),
            "synthetic_players": len(club_players) - len(real),
            "total_players": len(club_players),
            "GK": positions["GK"], "DF": positions["DF"], "MF": positions["MF"], "ST": positions["ST"],
            "five_a_side_complete": len(club_players) >= 8 and all(positions[position] >= required for position, required in {"GK": 1, "DF": 2, "MF": 1, "ST": 1}.items()),
            "eleven_a_side_complete": len(club_players) >= 16 and all(positions[position] >= required for position, required in {"GK": 1, "DF": 4, "MF": 3, "ST": 3}.items()),
        })
    with (report_dir / "EDITORIAL_2026_COVERAGE.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(coverage[0]))
        writer.writeheader()
        writer.writerows(coverage)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--players", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    write_import(import_editorial_2026(args.players, args.review, args.evidence), args.output_dir)


if __name__ == "__main__":
    main()
