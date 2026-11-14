from __future__ import annotations

from datetime import date
from pathlib import Path

from data.importers.common import age_on, normalize_name, parse_date, read_rows

EAFC_SOURCE = "EAFC26_DATAHUB_KAGGLE_CC_BY_4_0"
EAFC_VERSION = "FC26 update 4 / 2025-09-19"
EAFC_REPO_URL = "https://github.com/ismailoksuz/EAFC26-DataHub"
REFERENCE_DATE = date(2025, 9, 19)
POSITION_ALIASES = {
    "GK": "GK",
    "CB": "DF",
    "LB": "DF",
    "RB": "DF",
    "LWB": "DF",
    "RWB": "DF",
    "CDM": "MF",
    "CM": "MF",
    "CAM": "MF",
    "LM": "MF",
    "RM": "MF",
    "ST": "ST",
    "CF": "ST",
    "LW": "ST",
    "RW": "ST",
    "LF": "ST",
    "RF": "ST",
}
ATTRIBUTE_COLUMNS = {
    "pace": "pace",
    "shooting": "shooting",
    "passing": "passing",
    "dribbling": "dribbling",
    "defending": "defending",
    "physic": "physic",
    "crossing": "attacking_crossing",
    "finishing": "attacking_finishing",
    "heading_accuracy": "attacking_heading_accuracy",
    "short_passing": "attacking_short_passing",
    "volleys": "attacking_volleys",
    "dribbling_detail": "skill_dribbling",
    "curve": "skill_curve",
    "fk_accuracy": "skill_fk_accuracy",
    "long_passing": "skill_long_passing",
    "ball_control": "skill_ball_control",
    "acceleration": "movement_acceleration",
    "sprint_speed": "movement_sprint_speed",
    "agility": "movement_agility",
    "reactions": "movement_reactions",
    "balance": "movement_balance",
    "shot_power": "power_shot_power",
    "jumping": "power_jumping",
    "stamina": "power_stamina",
    "strength": "power_strength",
    "long_shots": "power_long_shots",
    "aggression": "mentality_aggression",
    "interceptions": "mentality_interceptions",
    "positioning": "mentality_positioning",
    "vision": "mentality_vision",
    "penalties": "mentality_penalties",
    "composure": "mentality_composure",
    "defensive_awareness": "defending_marking_awareness",
    "standing_tackle": "defending_standing_tackle",
    "sliding_tackle": "defending_sliding_tackle",
    "gk_diving": "goalkeeping_diving",
    "gk_handling": "goalkeeping_handling",
    "gk_kicking": "goalkeeping_kicking",
    "gk_positioning": "goalkeeping_positioning",
    "gk_reflexes": "goalkeeping_reflexes",
    "gk_speed": "goalkeeping_speed",
}


def number(value: str | None) -> int | None:
    try:
        return int(float(value)) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def positions(value: str | None) -> tuple[str | None, list[str]]:
    parsed = [
        POSITION_ALIASES.get(item.strip().upper()) for item in (value or "").split(",")
    ]
    parsed = [item for item in parsed if item]
    return parsed[0] if parsed else None, list(dict.fromkeys(parsed[1:]))


def import_rows(path: Path) -> list[dict]:
    rows = read_rows(path)
    records = []
    for row in rows:
        primary, secondary = positions(row.get("player_positions"))
        raw_birth_date = row.get("dob") or None
        sentinel_birth_date = raw_birth_date == "1996-02-29"
        birth = parse_date(raw_birth_date) if not sentinel_birth_date else None
        overall, potential = number(row.get("overall")), number(row.get("potential"))
        records.append(
            {
                "player_id": f"eafc26:{row.get('player_id', '').strip()}",
                "source_player_id": row.get("player_id"),
                "full_name": row.get("long_name") or row.get("short_name") or "",
                "display_name": row.get("short_name") or row.get("long_name") or "",
                "name_normalized": normalize_name(
                    row.get("long_name") or row.get("short_name")
                ),
                "nationality": row.get("nationality_name") or None,
                "birth_date": birth.isoformat() if birth else None,
                "source_birth_date_raw": raw_birth_date,
                "age": number(row.get("age")),
                "age_at_reference_date": age_on(birth, REFERENCE_DATE),
                "height_cm": number(row.get("height_cm")),
                "weight_kg": number(row.get("weight_kg")),
                "preferred_foot": row.get("preferred_foot") or None,
                "current_club_id": row.get("club_team_id") or None,
                "current_club_name": row.get("club_name") or None,
                "club_position": row.get("club_position") or None,
                "league_name": row.get("league_name") or None,
                "primary_position": primary,
                "secondary_positions": secondary,
                "overall": overall,
                "potential": potential,
                "rating_source": EAFC_SOURCE,
                "rating_version": EAFC_VERSION,
                "value_eur": number(row.get("value_eur")),
                "market_value_currency": "EUR",
                "market_value_reference_date": row.get("fifa_update_date") or None,
                "financial_source": EAFC_SOURCE,
                "attributes": {
                    name: number(row.get(column))
                    for name, column in ATTRIBUTE_COLUMNS.items()
                },
                "source_ids": {"eafc26": row.get("player_id") or ""},
                "source_url": f"{EAFC_REPO_URL}#data/players.csv",
                "player_url": row.get("player_url") or None,
                "source_quality": {
                    "sentinel_birth_date": sentinel_birth_date,
                    "name_present": bool(row.get("long_name") or row.get("short_name")),
                    "overall_valid": overall is not None and 1 <= overall <= 99,
                    "potential_valid": potential is not None and 1 <= potential <= 99,
                },
                "distribution_license": "CC BY 4.0",
                "distribution_allowed": True,
                "verification_status": "EAFC_RATING_SOURCE;IDENTITY_REQUIRES_CROSSCHECK",
            }
        )
    return records


def import_local_dataset(path: Path, *, license_reference: str | None) -> list[dict]:
    if not license_reference:
        raise PermissionError(
            "EAFC26-DataHub não traz licença explícita; forneça licença/autorização aplicável."
        )
    rows = read_rows(path)
    if not rows:
        raise ValueError("Dataset EAFC26 vazio.")
    return [
        {
            **row,
            "rating_source": "EAFC26",
            "rating_version": "FC 26",
            "source_ids": {"eafc26": row.get("player_id", "")},
            "license_reference": license_reference,
        }
        for row in rows
    ]
