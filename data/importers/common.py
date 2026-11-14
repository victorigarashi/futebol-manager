from __future__ import annotations

import csv
import gzip
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any


def open_csv(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8-sig", newline="")
    return path.open("r", encoding="utf-8-sig", newline="")


def read_rows(path: Path) -> list[dict[str, str]]:
    with open_csv(path) as handle:
        return list(csv.DictReader(handle))


def normalize_name(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(
        character for character in text if not unicodedata.combining(character)
    )
    return " ".join(
        "".join(ch if ch.isalnum() else " " for ch in text.casefold()).split()
    )


def age_on(birth_date: date | None, reference: date) -> int | None:
    if birth_date is None:
        return None
    return (
        reference.year
        - birth_date.year
        - ((reference.month, reference.day) < (birth_date.month, birth_date.day))
    )


def integer_or_none(value: Any) -> int | None:
    if value is None or str(value).strip() in {"", "NA", "N/A", "null", "None"}:
        return None
    try:
        return int(float(str(value).replace(",", ".")))
    except (TypeError, ValueError, OverflowError):
        return None


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    raw = value.strip().split(" ", 1)[0]
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None
