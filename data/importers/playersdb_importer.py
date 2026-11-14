from __future__ import annotations

from pathlib import Path

from data.importers.common import read_rows


def import_export(path: Path, *, terms_reference: str | None = None) -> list[dict]:
    rows = read_rows(path)
    if not rows:
        raise ValueError("Exportação PlayersDB vazia.")
    # PlayersDB is an identity cross-reference source, not a ratings source.
    return [
        {
            **row,
            "rating_source": None,
            "source_ids": {
                "playersdb": row.get("id", ""),
                "transfermarkt": row.get("transfermarkt_id", ""),
                "eafc26": row.get("fifa_id", ""),
            },
            "terms_reference": terms_reference,
        }
        for row in rows
    ]
