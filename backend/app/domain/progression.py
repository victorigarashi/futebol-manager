"""Reproducible career development kept separate from the immutable player catalog."""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ProgressionRecord:
    player_id: str
    season_number: int
    overall_before: int
    overall_after: int
    delta: int
    internal_market_value_cents: int
    minutes_played: int
    goals: int
    reasons: tuple[str, ...]

    def view(self) -> dict[str, object]:
        return asdict(self)


def progress_player(
    *, player_id: str, season_number: int, age: int | None, overall: int,
    potential: int, original_market_value_cents: int, minutes_played: int,
    goals: int, seed: int,
) -> ProgressionRecord:
    rng = random.Random(seed)
    before = min(99, max(1, overall))
    reasons: list[str] = []
    if age is None:
        delta = 0
        reasons.append("idade não confirmada; progressão etária pendente")
    elif age <= 23 and before < potential and minutes_played >= 540:
        delta = 1 if rng.random() < min(.78, .35 + (potential - before) * .045 + min(minutes_played, 2_700) / 10_000) else 0
        if delta:
            reasons.append("desenvolvimento jovem e potencial")
        if goals and minutes_played:
            reasons.append("contribuição ofensiva")
    elif age >= 30:
        delta = -1 if rng.random() < min(.62, .18 + (age - 30) * .045 + (0.12 if minutes_played < 900 else 0)) else 0
        if delta:
            reasons.append("regressão natural por idade")
    elif minutes_played < 540:
        delta = -1 if rng.random() < .12 else 0
        reasons.append("pouca minutagem")
    else:
        delta = 0
    if not reasons:
        reasons.append("desempenho estável")
    after = min(99, max(1, min(potential, before + delta) if delta > 0 else before + delta))
    applied_delta = after - before
    internal_value = max(0, round(original_market_value_cents * after / max(1, overall)))
    return ProgressionRecord(player_id, season_number, before, after, applied_delta, internal_value, max(0, minutes_played), max(0, goals), tuple(reasons))
