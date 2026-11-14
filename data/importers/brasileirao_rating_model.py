"""Transparent internal rating model for Brazilian players.

This module never fabricates missing performance indicators. It only returns a
rating when a caller supplies a complete, normalized evidence record.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

MODEL_VERSION = "BRASILEIRAO_MANAGER_RATING_V1"
POSITIONS = {"GK", "DF", "MF", "ST"}


@dataclass(frozen=True)
class RatingResult:
    overall: int
    potential: int
    attributes: dict[str, int]
    confidence: str
    inputs: tuple[str, ...]


def _bounded(value: float) -> int:
    return max(1, min(99, round(value)))


def _complete_evidence(position: str, evidence: Mapping[str, float]) -> bool:
    required = {"age", "minutes", "appearances", "regularity"}
    if position == "GK":
        required |= {"saves", "goals_conceded_rate"}
    elif position == "DF":
        required |= {"tackles", "interceptions", "duels"}
    elif position == "MF":
        required |= {"passes", "key_passes", "assists"}
    elif position == "ST":
        required |= {"shots", "goals", "assists"}
    else:
        return False
    return all(key in evidence for key in required)


def rate_player(position: str, evidence: Mapping[str, float]) -> RatingResult | None:
    """Return a bounded rating only when positional evidence is complete.

    Inputs are expected to be normalized to 0..100, except age. No defaults are
    applied to absent statistics, so a missing provider record remains pending.
    """
    position = position.upper()
    if not _complete_evidence(position, evidence):
        return None
    minutes = min(100.0, max(0.0, float(evidence["minutes"])))
    appearances = min(100.0, max(0.0, float(evidence["appearances"])))
    regularity = min(100.0, max(0.0, float(evidence["regularity"])))
    if position == "GK":
        components = {
            "diving": evidence["saves"],
            "handling": 100.0 - evidence["goals_conceded_rate"],
            "positioning": regularity,
            "reflexes": evidence["saves"],
            "kicking": minutes,
        }
        overall = (
            0.30 * evidence["saves"]
            + 0.25 * (100 - evidence["goals_conceded_rate"])
            + 0.20 * regularity
            + 0.15 * minutes
            + 0.10 * appearances
        )
    elif position == "DF":
        components = {
            "defending": evidence["interceptions"],
            "standing_tackle": evidence["tackles"],
            "strength": evidence["duels"],
            "stamina": minutes,
            "positioning": regularity,
        }
        overall = (
            0.30 * evidence["interceptions"]
            + 0.25 * evidence["tackles"]
            + 0.20 * evidence["duels"]
            + 0.15 * minutes
            + 0.10 * regularity
        )
    elif position == "MF":
        components = {
            "short_passing": evidence["passes"],
            "vision": evidence["key_passes"],
            "stamina": minutes,
            "positioning": regularity,
            "assists": evidence["assists"],
        }
        overall = (
            0.30 * evidence["passes"]
            + 0.20 * evidence["key_passes"]
            + 0.20 * evidence["assists"]
            + 0.20 * minutes
            + 0.10 * regularity
        )
    else:
        components = {
            "finishing": evidence["goals"],
            "shot_power": evidence["shots"],
            "positioning": regularity,
            "stamina": minutes,
            "assists": evidence["assists"],
        }
        overall = (
            0.35 * evidence["goals"]
            + 0.20 * evidence["shots"]
            + 0.15 * evidence["assists"]
            + 0.20 * minutes
            + 0.10 * regularity
        )
    age = float(evidence["age"])
    age_factor = max(-5.0, min(7.0, (24.0 - age) * 0.8))
    potential = _bounded(overall + age_factor)
    return RatingResult(
        _bounded(overall),
        potential,
        {name: _bounded(value) for name, value in components.items()},
        "INTERNAL_ESTIMATE",
        tuple(sorted(evidence)),
    )
