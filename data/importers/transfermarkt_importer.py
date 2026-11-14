from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from data.importers.common import age_on, integer_or_none, parse_date, read_rows
from data.importers.validation import club_code

SOURCE = "TRANSFERMARKT_DATASETS_CC0"
SOURCE_URL = "https://github.com/dcaribou/transfermarkt-datasets"
SNAPSHOT_DATE = date(2026, 7, 6)
VALUATION_CUTOFF = date(2026, 6, 12)


def position(value: str | None) -> str | None:
    return {"Goalkeeper": "GK", "Defender": "DF", "Midfield": "MF", "Attack": "ST"}.get(
        value or ""
    )


def market_value_cents(eur: str | None) -> int | None:
    if not eur:
        return None
    try:
        return int((Decimal(eur) * 100).quantize(Decimal(1)))
    except (InvalidOperation, ValueError):
        return None


def import_players(
    players_path: Path, valuations_path: Path, appearances_path: Path
) -> list[dict]:
    """Normalize the published snapshot; never claims its club field is current in 2026."""
    valuations: dict[str, list[tuple[date, int]]] = defaultdict(list)
    for row in read_rows(valuations_path):
        valuation_date = parse_date(row.get("date"))
        value = market_value_cents(row.get("market_value_in_eur"))
        if valuation_date and valuation_date <= VALUATION_CUTOFF and value is not None:
            valuations[row.get("player_id", "")].append((valuation_date, value))

    usage: dict[str, dict[str, int]] = defaultdict(
        lambda: {"appearances": 0, "minutes": 0, "goals": 0, "assists": 0}
    )
    saw_brazilian_league_appearances = False
    for row in read_rows(appearances_path):
        if row.get("competition_id") == "BRA1":
            saw_brazilian_league_appearances = True
        match_date = parse_date(row.get("date"))
        if (
            not match_date
            or match_date.year != 2025
            or row.get("competition_id") != "BRA1"
        ):
            continue
        stats = usage[row.get("player_id", "")]
        stats["appearances"] += 1
        for field in ("minutes_played", "goals", "assists"):
            stats[field.replace("_played", "")] += integer_or_none(row.get(field)) or 0

    records = []
    for row in read_rows(players_path):
        if row.get("current_club_domestic_competition_id") != "BRA1":
            continue
        pid = row.get("player_id", "").strip()
        if not pid:
            continue
        birth = parse_date(row.get("date_of_birth"))
        history = sorted(valuations.get(pid, []))
        latest_value = history[-1] if history else None
        category_position = position(row.get("position"))
        source_position = row.get("sub_position") or row.get("position") or None
        records.append(
            {
                "player_id": f"tm:{pid}",
                "full_name": row.get("name") or "",
                "display_name": row.get("name") or "",
                "known_as": [],
                "nationality": row.get("country_of_citizenship") or None,
                "second_nationality": None,
                "birth_date": birth.isoformat() if birth else None,
                "age_at_reference_date": age_on(birth, SNAPSHOT_DATE),
                "height_cm": integer_or_none(row.get("height_in_cm")),
                "weight_kg": None,
                "preferred_foot": row.get("foot") or None,
                "current_club_id": row.get("current_club_id") or None,
                "current_club_name": row.get("current_club_name") or None,
                "current_game_club_code_candidate": club_code(
                    row.get("current_club_name")
                ),
                "club_link_status": "HISTORICAL_CANDIDATE_UNVERIFIED",
                "original_club_id": None,
                "original_club_name": None,
                "competition": row.get("current_club_domestic_competition_id") or None,
                "season_reference": row.get("last_season") or None,
                "source_reference_date": SNAPSHOT_DATE.isoformat(),
                "primary_position": source_position,
                "normalized_game_position": category_position,
                "secondary_positions": [],
                "positional_compatibility": [],
                "overall": None,
                "potential": None,
                "rating_version": None,
                "rating_source": None,
                "attributes": {
                    key: None
                    for key in (
                        "acceleration",
                        "sprint_speed",
                        "agility",
                        "balance",
                        "reactions",
                        "stamina",
                        "strength",
                        "aggression",
                        "vision",
                        "short_passing",
                        "long_passing",
                        "crossing",
                        "curve",
                        "finishing",
                        "shot_power",
                        "long_shots",
                        "positioning",
                        "volleys",
                        "penalties",
                        "dribbling",
                        "ball_control",
                        "composure",
                        "interceptions",
                        "defensive_awareness",
                        "standing_tackle",
                        "sliding_tackle",
                        "jumping",
                        "heading_accuracy",
                        "gk_diving",
                        "gk_handling",
                        "gk_kicking",
                        "gk_reflexes",
                        "gk_speed",
                        "gk_positioning",
                    )
                },
                "external_market_value": str(Decimal(latest_value[1]) / 100)
                if latest_value
                else None,
                "market_value_currency": "EUR" if latest_value else None,
                "market_value_reference_date": latest_value[0].isoformat()
                if latest_value
                else None,
                "market_value_source": SOURCE if latest_value else None,
                "original_market_value_history": [
                    {
                        "date": day.isoformat(),
                        "value_cents": cents,
                        "currency": "EUR",
                        "source": SOURCE,
                    }
                    for day, cents in history
                ],
                "game_starting_value_cents": None,
                "player_photo_source_url": None,
                "player_photo_license": None,
                "player_photo_allowed_for_redistribution": False,
                "club_crest_source_url": None,
                "club_crest_license": None,
                "club_crest_allowed_for_redistribution": False,
                "release_season": None,
                "relevance_score": None,
                "relevance_evidence": usage.get(pid)
                if saw_brazilian_league_appearances
                else None,
                "relevance_evidence_status": "SOURCE_HAS_NO_BRA1_APPEARANCES"
                if not saw_brazilian_league_appearances
                else "BRA1_2025_APPEARANCES",
                "starter_status": "UNVERIFIED",
                "squad_priority": None,
                "source_ids": {"transfermarkt": pid},
                "field_provenance": {
                    "identity": SOURCE,
                    "birth_date": SOURCE,
                    "nationality": SOURCE,
                    "club": SOURCE,
                    "position": SOURCE,
                    "market_value": SOURCE if latest_value else None,
                },
                "verification_status": "HISTORICAL_CANDIDATE_UNVERIFIED_FOR_2026",
                "data_version": "dcaribou-snapshot-2026-07-06",
                "reviewed_at": None,
                "missing_fields": [
                    "overall",
                    "potential",
                    "attributes",
                    "current_2026_club_validation",
                    "release_season",
                    "licensed_photo",
                    "licensed_crest",
                ],
                "source_url": row.get("url") or SOURCE_URL,
            }
        )
    return records
