from __future__ import annotations

from dataclasses import dataclass

from data.importers.common import normalize_name


@dataclass(frozen=True)
class Match:
    confidence: str
    reason: str
    left_id: str | None = None
    right_id: str | None = None


def match_identity(left: dict, right: dict) -> Match:
    """Conservative cross-source matching; ambiguous text never merges records."""
    left_ids, right_ids = left.get("source_ids", {}), right.get("source_ids", {})
    shared = [
        (key, value)
        for key, value in left_ids.items()
        if value and right_ids.get(key) == value
    ]
    if shared:
        key, value = min(shared)
        return Match(
            "EXACT_ID", f"ID externo coincidente: {key}", str(value), str(value)
        )
    conflicts = [
        key
        for key, value in left_ids.items()
        if value and right_ids.get(key) and right_ids[key] != value
    ]
    if conflicts:
        return Match(
            "NEEDS_REVIEW", f"IDs externos divergem: {', '.join(sorted(conflicts))}."
        )
    left_birth, right_birth = left.get("birth_date"), right.get("birth_date")
    left_name, right_name = (
        normalize_name(left.get("full_name") or left.get("name")),
        normalize_name(right.get("full_name") or right.get("name")),
    )
    if not left_name or not right_name or left_name != right_name:
        return Match("UNMATCHED", "Nome normalizado diferente ou ausente.")
    if left_birth and right_birth and left_birth == right_birth:
        if (
            left.get("nationality")
            and right.get("nationality")
            and left["nationality"] != right["nationality"]
        ):
            return Match(
                "NEEDS_REVIEW", "Nome e nascimento coincidem, nacionalidades divergem."
            )
        return Match("HIGH_CONFIDENCE", "Nome completo e data de nascimento coincidem.")
    same_nat = left.get("nationality") and left.get("nationality") == right.get(
        "nationality"
    )
    same_club = left.get("current_club_id") and left.get(
        "current_club_id"
    ) == right.get("current_club_id")
    if same_nat and same_club:
        return Match(
            "NEEDS_REVIEW",
            "Nome, nacionalidade e clube coincidem; falta data de nascimento.",
        )
    return Match(
        "NEEDS_REVIEW", "Nome coincide, mas evidências adicionais são insuficientes."
    )
