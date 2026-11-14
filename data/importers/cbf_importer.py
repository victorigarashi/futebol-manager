from __future__ import annotations

from pathlib import Path

from data.importers.common import read_rows


def import_authorized_export(
    path: Path, *, permission_reference: str | None
) -> list[dict]:
    if not permission_reference:
        raise PermissionError(
            "CBF exige exportação autorizada e referência de permissão."
        )
    return read_rows(path)
