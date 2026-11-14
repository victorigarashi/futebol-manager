from __future__ import annotations

import csv
import json
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

from data.importers.common import normalize_name

CLUB_ALIASES = {
    "FLA": ("flamengo",),
    "PAL": ("palmeiras",),
    "COR": ("corinthians",),
    "SAO": ("sao paulo",),
    "SAN": ("santos",),
    "FLU": ("fluminense",),
    "BOT": ("botafogo",),
    "VAS": ("vasco",),
    "CRU": ("cruzeiro",),
    "CAM": ("atletico mineiro", "atletico-mg"),
    "GRE": ("gremio",),
    "INT": ("internacional",),
    "BAH": ("bahia",),
    "VIT": ("vitoria",),
    "CAP": ("athletico paranaense",),
    "CFC": ("coritiba",),
    "RBB": ("red bull bragantino", "bragantino"),
    "MIR": ("mirassol", "mirasol"),
    "CHA": ("chapecoense",),
    "REM": ("remo",),
}


def club_code(name: str | None) -> str | None:
    normalized = normalize_name(name)
    hits = [
        code
        for code, aliases in CLUB_ALIASES.items()
        if any(alias in normalized for alias in aliases)
    ]
    return hits[0] if len(hits) == 1 else None


def validate_records(records: list[dict]) -> dict:
    ids = [record.get("player_id") for record in records]
    dup_ids = sorted(
        value for value, count in Counter(ids).items() if value and count > 1
    )
    names = Counter(
        normalize_name(row.get("full_name")) for row in records if row.get("full_name")
    )
    dup_names = sorted(name for name, count in names.items() if count > 1)
    issues = []
    if dup_ids:
        issues.append("IDs duplicados detectados.")
    for record in records:
        if not record.get("full_name"):
            issues.append(f"Nome ausente: {record.get('player_id')}")
        if record.get("overall") is not None and not 1 <= record["overall"] <= 99:
            issues.append(f"Overall fora do intervalo: {record.get('player_id')}")
        if record.get("potential") is not None and not 1 <= record["potential"] <= 99:
            issues.append(f"Potencial fora do intervalo: {record.get('player_id')}")
        if (
            record.get("market_value_cents") is not None
            and record["market_value_cents"] < 0
        ):
            issues.append(f"Valor negativo: {record.get('player_id')}")
        external_value = record.get("external_market_value")
        if external_value is not None:
            try:
                if Decimal(external_value) < 0:
                    issues.append(f"Valor externo negativo: {record.get('player_id')}")
            except (InvalidOperation, TypeError, ValueError):
                issues.append(f"Valor externo inválido: {record.get('player_id')}")
    return {
        "valid": not issues,
        "record_count": len(records),
        "duplicate_ids": dup_ids,
        "duplicate_normalized_names": dup_names,
        "issues": issues,
    }


def runtime_compatible(record: dict) -> bool:
    """Mirror required fields in backend.app.domain.catalog.CatalogPlayer."""
    required = (
        "id",
        "name",
        "club_code",
        "age",
        "position",
        "overall",
        "potential",
        "market_value_cents",
        "source",
        "source_version",
    )
    return all(record.get(field) is not None for field in required)


def _write_csv(path: Path, rows: list[dict], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = list(dict.fromkeys(key for row in rows for key in row)) or [
            "player_id"
        ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def generate_reports(records: list[dict], report_dir: Path) -> dict:
    report_dir.mkdir(parents=True, exist_ok=True)
    stats = validate_records(records)
    club_counts = Counter(
        row.get("current_game_club_code_candidate")
        or club_code(row.get("current_club_name"))
        for row in records
        if row.get("current_game_club_code_candidate")
        or club_code(row.get("current_club_name"))
    )
    position_counts = Counter(
        row.get("normalized_game_position") or "MISSING" for row in records
    )
    _write_csv(
        report_dir / "COVERAGE_BY_CLUB.csv",
        [
            {
                "club_code": code,
                "historical_candidates": club_counts.get(code, 0),
                "status": "historical source club only; 2026 affiliation unverified",
            }
            for code in CLUB_ALIASES
        ],
    )
    _write_csv(
        report_dir / "COVERAGE_BY_POSITION.csv",
        [
            {"position": key, "players": count}
            for key, count in sorted(position_counts.items())
        ],
    )
    _write_csv(
        report_dir / "MISSING_ATTRIBUTES.csv",
        [
            {
                "player_id": row["player_id"],
                "name": row["full_name"],
                "missing_attributes": ";".join(
                    key for key, value in row["attributes"].items() if value is None
                ),
            }
            for row in records
        ],
    )
    _write_csv(
        report_dir / "MISSING_POTENTIAL.csv",
        [
            {"player_id": row["player_id"], "name": row["full_name"], "potential": ""}
            for row in records
        ],
    )
    _write_csv(
        report_dir / "MISSING_BIRTH_DATE.csv",
        [
            {"player_id": row["player_id"], "name": row["full_name"]}
            for row in records
            if row.get("birth_date") is None
        ],
    )
    _write_csv(
        report_dir / "MISSING_NATIONALITY.csv",
        [
            {"player_id": row["player_id"], "name": row["full_name"]}
            for row in records
            if row.get("nationality") is None
        ],
    )
    _write_csv(
        report_dir / "MISSING_OVERALL.csv",
        [
            {
                "player_id": row["player_id"],
                "name": row["full_name"],
                "overall": "",
                "reason": "source does not provide EA/FC Mania ratings",
            }
            for row in records
            if row.get("overall") is None
        ],
    )
    _write_csv(
        report_dir / "MISSING_MARKET_VALUES.csv",
        [
            {
                "player_id": row["player_id"],
                "name": row["full_name"],
                "valuation_date": "",
                "reason": "no valuation up to 2026-06-12",
            }
            for row in records
            if row["external_market_value"] is None
        ],
    )
    _write_csv(
        report_dir / "DUPLICATES.csv",
        [
            {
                "normalized_name": name,
                "player_id": row["player_id"],
                "full_name": row["full_name"],
                "birth_date": row["birth_date"],
                "club_id": row["current_club_id"],
                "resolution": "review; never auto-merge by name",
            }
            for name in stats["duplicate_normalized_names"]
            for row in records
            if normalize_name(row.get("full_name")) == name
        ],
    )
    _write_csv(
        report_dir / "IDENTITY_MATCH_REVIEW.csv",
        [
            {
                "player_id": row["player_id"],
                "name": row["full_name"],
                "confidence": "UNMATCHED",
                "review_reason": "no external identity dataset supplied",
            }
            for row in records
        ],
    )
    _write_csv(
        report_dir / "CONFLICTING_SOURCES.csv",
        [],
        [
            "player_id",
            "field",
            "value_a",
            "source_a",
            "value_b",
            "source_b",
            "chosen_value",
            "reason",
        ],
    )
    _write_csv(
        report_dir / "LICENSE_AUDIT.csv",
        [
            {
                "source": "dcaribou/transfermarkt-datasets",
                "license": "CC0-1.0 (repository dataset license)",
                "use": "derived player metadata and valuation history",
                "redistribution": "allowed by stated dataset license; retain source and caveat underlying third-party rights",
                "assets": "no photos or crests included",
            },
            {
                "source": "EAFC26-DataHub / Kaggle dataset",
                "license": "Attribution 4.0 International (CC BY 4.0), Kaggle dataset rovnez/fc-26-fifa-26-player-data, version 3",
                "use": "ratings/attributes imported to staging only, with attribution",
                "redistribution": "permitted with CC BY attribution; underlying EA/Sofifa rights and identity quality remain caveats",
                "assets": "none",
            },
            {
                "source": "FC Mania patch database",
                "license": "terms limit patch to personal, individual and non-transferable use",
                "use": "not imported",
                "redistribution": "blocked pending explicit written authorization",
                "assets": "none",
            },
            {
                "source": "CBF 2026 listings",
                "license": "site terms; page says all rights reserved",
                "use": "reference only; no bulk scrape",
                "redistribution": "requires permission/export terms",
                "assets": "none",
            },
            {
                "source": "PlayersDB",
                "license": "terms grant no license to third-party data/IP; access via official download only",
                "use": "not imported (local CSV absent)",
                "redistribution": "third-party rights/permission unresolved",
                "assets": "none",
            },
            {
                "source": "Transfermarkt player images",
                "license": "not licensed for redistribution by dataset CC0 alone",
                "use": "URLs excluded",
                "redistribution": "blocked",
                "assets": "none",
            },
        ],
    )
    _write_csv(
        report_dir / "SEASON_RELEASE_REPORT.csv",
        [
            {
                "release_season": season,
                "players": 0,
                "candidate_records_unassigned": len(records),
                "status": "not assigned; product release mapping and current squads require verification",
            }
            for season in (1, 2, 3)
        ],
    )
    _write_csv(
        report_dir / "ASSET_MANIFEST.csv",
        [],
        [
            "entity_id",
            "asset_type",
            "source_url",
            "copyright_owner",
            "license",
            "attribution_required",
            "allowed_for_redistribution",
            "local_path",
            "checksum",
        ],
    )
    market_count = sum(row["external_market_value"] is not None for row in records)
    overall_count = sum(row.get("overall") is not None for row in records)
    potential_count = sum(row.get("potential") is not None for row in records)
    attrs_count = sum(
        all(value is not None for value in row["attributes"].values())
        for row in records
    )
    runtime_count = sum(runtime_compatible(row) for row in records)
    birth_date_count = sum(row.get("birth_date") is not None for row in records)
    nationality_count = sum(row.get("nationality") is not None for row in records)
    position_count = sum(
        row.get("normalized_game_position") is not None for row in records
    )
    club_candidate_count = sum(
        row.get("current_game_club_code_candidate") is not None for row in records
    )
    report = {
        **stats,
        "overall_confirmed": overall_count,
        "potential_confirmed": potential_count,
        "all_attributes_confirmed": attrs_count,
        "market_value_confirmed": market_count,
        "birth_date_confirmed": birth_date_count,
        "nationality_confirmed": nationality_count,
        "position_confirmed": position_count,
        "historical_game_club_candidate": club_candidate_count,
        "players_with_photo_permission": 0,
        "club_2026_validated": 0,
        "release_season_assigned": 0,
        "runtime_compatible_count": runtime_count,
        "coverage_by_historical_club": dict(club_counts),
        "coverage_by_position": dict(position_counts),
        "valuation_reference_cutoff": "2026-06-12",
        "source_snapshot": "2026-07-06",
        "production_catalog_generated": False,
    }
    (report_dir / "TOTAL_PLAYERS_REPORT.md").write_text(
        "# Relatório do catálogo de jogadores (staging)\n\n"
        f"- Registros normalizados: **{len(records)}**.\n- Overall confirmado: **{overall_count}**.\n- Potencial confirmado: **{potential_count}**.\n"
        f"- Ficha completa de atributos: **{attrs_count}**.\n- Valores financeiros com histórico disponível até 2026-06-12: **{market_count}**.\n"
        f"- Data de nascimento: **{birth_date_count}**; nacionalidade: **{nationality_count}**; posições normalizadas para o jogo: **{position_count}**.\n"
        f"- Clube associado no snapshot (não confirmado para 2026): **{club_candidate_count}**.\n"
        f"- Compatíveis com os campos obrigatórios de `CatalogPlayer` do backend: **{runtime_count}**.\n"
        "- Fotos com permissão de redistribuição: **0**.\n- Clubes validados para a Série A 2026: **0**.\n- Evidências de aparições da Série A 2025 disponíveis nesta fonte: **0** (o snapshot de aparições não contém a competição BRA1).\n\n"
        "Fonte principal: dcaribou/transfermarkt-datasets, licença CC0-1.0, snapshot encerrado em 2026-07-06. O próprio projeto informa que não cobre os elencos 2026/27 e que avaliações param em 2026-06-12. Os vínculos são candidatos históricos; não foram promovidos ao catálogo oficial. O dataset não contém overall, potencial nem atributos FC Mania/EAFC. Imagens foram deliberadamente excluídas.\n",
        encoding="utf-8",
    )
    (report_dir / "coverage.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report
