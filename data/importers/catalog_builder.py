from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from data.importers.common import read_rows
from data.importers.eafc26_importer import import_rows
from data.importers.transfermarkt_importer import import_players
from data.importers.validation import CLUB_ALIASES, club_code, generate_reports

VALIDATION_STATUSES = {
    "VERIFIED",
    "NEEDS_REVIEW",
    "STALE_CLUB",
    "INVALID_IDENTITY",
    "LICENSE_BLOCKED",
}


def load_official_club_reference(path: Path | None) -> dict[str, dict]:
    """Load an explicitly supplied official export; never scrape CBF implicitly."""
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("players", payload) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise TypeError(
            "A referência oficial deve ser uma lista ou objeto com players."
        )
    index = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in ("eafc_player_id", "source_player_id", "player_id"):
            value = row.get(key)
            if value:
                index[str(value)] = row
    return index


def classify_candidate(
    row: dict, official_reference: dict[str, dict] | None = None
) -> tuple[str, str]:
    """Classify EAFC identity independently of the optional historical dataset."""
    quality = row.get("source_quality", {})
    if not row.get("full_name") or not row.get("source_player_id"):
        return "INVALID_IDENTITY", "nome ou identificador EAFC ausente"
    if quality.get("sentinel_birth_date"):
        return "INVALID_IDENTITY", "data de nascimento sentinela não é uma data real"
    if not quality.get("overall_valid") or not quality.get("potential_valid"):
        return "INVALID_IDENTITY", "overall ou potencial fora do intervalo 1-99"
    if not row.get("primary_position") or not row.get("current_club_name"):
        return "NEEDS_REVIEW", "posição ou clube ausente no registro EAFC"
    if not row.get("distribution_allowed", False):
        return "LICENSE_BLOCKED", "a licença não autoriza a distribuição deste registro"
    if official_reference is None:
        return (
            "STALE_CLUB",
            "clube da fonte EAFC é histórico e não foi confirmado por exportação oficial atual",
        )
    official = official_reference.get(str(row.get("source_player_id")))
    if not official:
        return "NEEDS_REVIEW", "atleta não encontrado na referência oficial fornecida"
    official_club = official.get("current_club_name") or official.get("club_name")
    if official_club and club_code(official_club) == club_code(
        row.get("current_club_name")
    ):
        return (
            "VERIFIED",
            "identidade EAFC e vínculo atual confirmados pela referência oficial",
        )
    return (
        "NEEDS_REVIEW",
        "identidade encontrada, mas o clube atual diverge da fonte EAFC",
    )


def build_transfermarkt_staging(source_dir: Path, output: Path) -> list[dict]:
    records = import_players(
        source_dir / "players.csv.gz",
        source_dir / "player_valuations.csv.gz",
        source_dir / "appearances.csv.gz",
    )
    files = {}
    for name in (
        "players.csv.gz",
        "player_valuations.csv.gz",
        "clubs.csv.gz",
        "appearances.csv.gz",
    ):
        source = source_dir / name
        files[name] = {
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "source_url": f"https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data/{name}",
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "catalog_version": "transfermarkt-cc0-2026-07-06-staging",
                "source": "dcaribou/transfermarkt-datasets",
                "source_url": "https://github.com/dcaribou/transfermarkt-datasets",
                "license": "CC0-1.0",
                "source_version": "snapshot-2026-07-06",
                "retrieved_at": "2026-11-13",
                "reference_date": "2026-07-06",
                "valuation_cutoff": "2026-06-12",
                "source_files": files,
                "production_ready": False,
                "players": records,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (output.parent / "SOURCE_MANIFEST.json").write_text(
        json.dumps(
            {
                "source": "dcaribou/transfermarkt-datasets",
                "license": "CC0-1.0",
                "snapshot_date": "2026-07-06",
                "retrieved_at": "2026-11-13",
                "files": files,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    clubs = [
        row
        for row in read_rows(source_dir / "clubs.csv.gz")
        if row.get("domestic_competition_id") == "BRA1"
    ]
    import csv

    club_output = output.parent / "transfermarkt_bra1_clubs.csv"
    with club_output.open("w", encoding="utf-8", newline="") as handle:
        fields = ["club_id", "name", "domestic_competition_id", "last_season", "url"]
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(clubs)
    return records


def build_eafc26_staging(
    source_file: Path,
    historical_file: Path,
    output: Path,
    reports: Path,
    official_club_reference: Path | None = None,
) -> dict:
    """Build staging and classify Série A independently of historical coverage."""
    eafc_records = import_rows(source_file)
    historical = json.loads(historical_file.read_text(encoding="utf-8"))["players"]
    by_name = {}
    for item in historical:
        by_name.setdefault(item.get("full_name", "").casefold(), []).append(item)
    official = (
        load_official_club_reference(official_club_reference)
        if official_club_reference
        else None
    )
    brazil_rows = []
    matches = []
    status_counts = {status: 0 for status in VALIDATION_STATUSES}
    historical_counts = {"HIGH_CONFIDENCE": 0, "NEEDS_REVIEW": 0, "UNMATCHED": 0}
    for row in eafc_records:
        candidates = by_name.get(row["full_name"].casefold(), [])
        linked = candidates[0] if candidates else None
        if linked:
            row["historical_player_id"] = linked.get("player_id")
            row["historical_market_value"] = linked.get(
                "original_market_value_history", []
            )
            if (
                row.get("birth_date")
                and row.get("birth_date") == linked.get("birth_date")
                and row.get("nationality") == linked.get("nationality")
            ):
                historical_status, historical_reason = (
                    "HIGH_CONFIDENCE",
                    "nome, nascimento e nacionalidade coincidem",
                )
            else:
                historical_status, historical_reason = (
                    "NEEDS_REVIEW",
                    "nome coincide, mas a evidência histórica é incompleta",
                )
        else:
            historical_status, historical_reason = (
                "UNMATCHED",
                "nenhum perfil histórico correspondente",
            )
        historical_counts[historical_status] += 1
        validation_status, validation_reason = classify_candidate(row, official)
        row["identity_match_status"] = historical_status
        row["identity_match_reason"] = historical_reason
        row["validation_status"] = validation_status
        row["validation_reason"] = validation_reason
        row["official_club_reference_status"] = (
            "CONFIRMED"
            if official and row.get("source_player_id") in official
            else ("NOT_SUPPLIED" if official is None else "NOT_FOUND")
        )
        row["current_game_club_code_candidate"] = club_code(
            row.get("current_club_name")
        )
        row["production_eligible"] = validation_status == "VERIFIED"
        status_counts[validation_status] += 1
        if row.get("league_name") == "Série A":
            brazil_rows.append(row)
        matches.append(
            {
                "eafc_player_id": row["player_id"],
                "name": row["full_name"],
                "historical_status": historical_status,
                "validation_status": validation_status,
                "validation_reason": validation_reason,
                "league": row.get("league_name", ""),
                "club": row.get("current_club_name", ""),
                "overall": row.get("overall"),
                "potential": row.get("potential"),
            }
        )
    reports.mkdir(parents=True, exist_ok=True)
    with (reports / "EAFC_CROSS_MATCH.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(matches[0]))
        writer.writeheader()
        writer.writerows(matches)
    candidate_fields = [
        "player_id",
        "source_player_id",
        "full_name",
        "display_name",
        "nationality",
        "birth_date",
        "source_birth_date_raw",
        "current_club_name",
        "current_game_club_code_candidate",
        "primary_position",
        "secondary_positions",
        "overall",
        "potential",
        "rating_source",
        "rating_version",
        "value_eur",
        "market_value_currency",
        "market_value_reference_date",
        "historical_player_id",
        "identity_match_status",
        "validation_status",
        "validation_reason",
        "official_club_reference_status",
        "production_eligible",
    ]
    with (reports / "EAFC_BRAZIL_CANDIDATES.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle, fieldnames=candidate_fields, extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(brazil_rows)
    club_rows = []
    for code in CLUB_ALIASES:
        subset = [
            row
            for row in brazil_rows
            if row.get("current_game_club_code_candidate") == code
        ]
        verified = [row for row in subset if row["validation_status"] == "VERIFIED"]
        positions = {
            position: sum(row.get("primary_position") == position for row in verified)
            for position in ("GK", "DF", "MF", "ST")
        }
        club_rows.append(
            {
                "club_code": code,
                "eafc_rows": len(subset),
                "verified_rows": len(verified),
                "goalkeepers": positions["GK"],
                "defenders": positions["DF"],
                "midfielders": positions["MF"],
                "forwards": positions["ST"],
                "five_a_side_complete": len(verified) >= 8 and positions["GK"] >= 1,
                "eleven_a_side_complete": len(verified) >= 16 and positions["GK"] >= 1,
            }
        )
    with (reports / "EAFC_BRAZIL_COVERAGE_BY_CLUB.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(club_rows[0]))
        writer.writeheader()
        writer.writerows(club_rows)
    position_rows = [
        {
            "position": position,
            "candidates": sum(
                row.get("primary_position") == position for row in brazil_rows
            ),
            "verified": sum(
                row.get("primary_position") == position
                and row["validation_status"] == "VERIFIED"
                for row in brazil_rows
            ),
        }
        for position in ("GK", "DF", "MF", "ST")
    ]
    with (reports / "EAFC_BRAZIL_COVERAGE_BY_POSITION.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(position_rows[0]))
        writer.writeheader()
        writer.writerows(position_rows)
    brazil_status_counts = {
        status: sum(row["validation_status"] == status for row in brazil_rows)
        for status in VALIDATION_STATUSES
    }
    report = {
        "source": "EAFC26 DataHub -> Kaggle rovnez/fc-26-fifa-26-player-data",
        "license": "CC BY 4.0",
        "source_version": "FC26 update 4 / 2025-09-19",
        "total_records": len(eafc_records),
        "overall_count": sum(row["overall"] is not None for row in eafc_records),
        "potential_count": sum(row["potential"] is not None for row in eafc_records),
        "both_count": sum(
            row["overall"] is not None and row["potential"] is not None
            for row in eafc_records
        ),
        "eafc_game_value_count": sum(
            row["value_eur"] is not None for row in eafc_records
        ),
        "historical_match_counts": historical_counts,
        "validation_counts_all_eafc": status_counts,
        "brazilian_series_a_rows": len(brazil_rows),
        "brazilian_validation_counts": brazil_status_counts,
        "verified_ready_for_integration": sum(
            row["validation_status"] == "VERIFIED" for row in brazil_rows
        ),
        "clubs_complete_5x5": sum(row["five_a_side_complete"] for row in club_rows),
        "clubs_complete_11x11": sum(row["eleven_a_side_complete"] for row in club_rows),
        "official_reference_supplied": official is not None,
        "production_catalog_generated": False,
        "license_note": "CC BY 4.0 é a licença declarada pelo dataset; direitos subjacentes EA/Sofifa continuam sujeitos à verificação. value_eur é valor interno do jogo, não cotação Transfermarkt.",
    }
    (reports / "EAFC_BRAZIL_TOTAL_REPORT.md").write_text(
        "# Candidatos brasileiros EAFC26\n\n"
        + "\n".join(f"- {key}: **{value}**" for key, value in report.items())
        + "\n\nA validação histórica é enriquecimento opcional. Sem exportação oficial atual de clubes, candidatos limpos ficam em `STALE_CLUB`; não são promovidos ao catálogo operacional.\n",
        encoding="utf-8",
    )
    (reports / "EAFC_TOTAL_REPORT.md").write_text(
        "# EAFC26 ratings — relatório de staging\n\n"
        + "\n".join(f"- {key}: **{value}**" for key, value in report.items())
        + "\n",
        encoding="utf-8",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "catalog_version": "eafc26-datahub-staging-2025-09-19",
                "source": "EAFC26 DataHub",
                "source_url": "https://github.com/ismailoksuz/EAFC26-DataHub",
                "kaggle_url": "https://www.kaggle.com/datasets/rovnez/fc-26-fifa-26-player-data",
                "license": "CC BY 4.0",
                "attribution": "Dataset FC 26 (FIFA 26) Player Data by rovnez, Kaggle; DataHub by ismailoksuz",
                "production_ready": False,
                "players": eafc_records,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (reports / "EAFC_COVERAGE.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build auditable catalog staging; never writes players.json."
    )
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/catalogs/staging/transfermarkt_players.json"),
    )
    parser.add_argument("--reports", type=Path, default=Path("data/catalogs/reports"))
    parser.add_argument("--eafc26-csv", type=Path)
    parser.add_argument("--historical-staging", type=Path)
    parser.add_argument(
        "--eafc26-output",
        type=Path,
        default=Path("data/catalogs/staging/eafc26_players.json"),
    )
    parser.add_argument(
        "--official-club-reference",
        type=Path,
        help="JSON export autorizado e atual com source_player_id e current_club_name.",
    )
    args = parser.parse_args()
    records = build_transfermarkt_staging(args.source_dir, args.output)
    report = generate_reports(records, args.reports)
    eafc_report = None
    if args.eafc26_csv and args.historical_staging:
        eafc_report = build_eafc26_staging(
            args.eafc26_csv,
            args.historical_staging,
            args.eafc26_output,
            args.reports,
            args.official_club_reference,
        )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "reports": str(args.reports),
                "record_count": len(records),
                "valid_structure": report["valid"],
                "production_ready": False,
                "eafc26": eafc_report,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
