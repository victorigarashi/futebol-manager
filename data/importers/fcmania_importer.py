from __future__ import annotations

from pathlib import Path

from data.importers.common import read_rows


def import_authorized_export(
    path: Path, *, permission_reference: str | None
) -> list[dict]:
    if not permission_reference:
        raise PermissionError(
            "FC Mania exige referência de autorização/exportação fornecida pelo responsável."
        )
    rows = read_rows(path)
    if not rows:
        raise ValueError("Exportação FC Mania vazia.")
    return [
        {
            **row,
            "rating_source": "FC_MANIA",
            "source_ids": {"fcmania": row.get("id", "")},
            "permission_reference": permission_reference,
        }
        for row in rows
    ]
