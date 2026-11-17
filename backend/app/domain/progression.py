"""Reproducible career development kept separate from the immutable player catalog."""

from __future__ import annotations

import math
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


# Expected overall change per season by age (before minutes and performance).
AGE_TREND = ((20, 2.0), (23, 1.4), (26, 0.5), (29, 0.0), (31, -0.8), (33, -1.6))
VETERAN_TREND = -2.4
MAX_GAIN, MAX_LOSS = 4, -4
REGULAR_MINUTES = 1_620  # 18 full matches: a regular starter's season


def _age_trend(age: int) -> float:
    for limit, trend in AGE_TREND:
        if age <= limit:
            return trend
    return VETERAN_TREND


def progress_player(
    *, player_id: str, season_number: int, age: int | None, overall: int,
    potential: int, original_market_value_cents: int, minutes_played: int,
    goals: int, seed: int, assists: int = 0, matches: int = 0,
    average_rating: float | None = None, catalog_overall: int | None = None,
) -> ProgressionRecord:
    """One season of development, consolidated once at the end of the season.

    * Age sets the trend: young players tend to grow, players in their prime hold
      or move slightly, veterans tend to decline.
    * Minutes scale growth (a young player who does not play grows much less) and
      too few minutes can cost a point.
    * Performance (average match rating, goals and assists per match) moves the
      expectation up or down by at most ~1.5 points.
    * Growth never goes past the potential; it is not promised either.
    * Unknown age: no age trend is invented - only performance moves the player,
      by at most one point (conservative rule).
    The result is reproducible: same inputs and seed, same outcome.
    """
    rng = random.Random(seed)
    before = min(99, max(1, overall))
    reasons: list[str] = []
    share = min(1.0, max(0, minutes_played) / REGULAR_MINUTES)
    performance = 0.0
    if matches >= 3 and average_rating is not None:
        performance += max(-1.0, min(1.0, (average_rating - 6.6) / 0.9))
    if matches >= 3:
        performance += min(0.5, (goals + assists) / max(1, matches) * 0.6)
    if age is None:
        expected = max(-1.0, min(1.0, performance))
        reasons.append("idade não confirmada: só o desempenho conta (±1)")
    else:
        trend = _age_trend(age)
        if trend > 0:
            # Growth needs playing time and room below the potential.
            room = max(0, potential - before)
            trend *= (0.3 + 0.7 * share) * min(1.0, room / 3)
            if trend > 0.4:
                reasons.append("desenvolvimento jovem")
        elif trend < 0:
            reasons.append("regressão física por idade")
        expected = trend + performance
        if minutes_played < 270 and age >= 24:
            expected -= 0.6
            reasons.append("pouca minutagem")
    if performance >= 0.5:
        reasons.append("temporada de destaque")
    elif performance <= -0.5:
        reasons.append("temporada abaixo do esperado")
    delta = round(expected + rng.uniform(-0.75, 0.75))
    delta = max(-1, min(1, delta)) if age is None else max(MAX_LOSS, min(MAX_GAIN, delta))
    if delta > 0:
        delta = min(delta, max(0, potential - before))
    after = min(99, max(1, before + delta))
    if not reasons:
        reasons.append("desempenho estável")
    # Game value follows the new level, measured from the catalog's own level, so the
    # changes of every season accumulate (same curve as the catalog prices).
    base_overall = catalog_overall if catalog_overall is not None else overall
    value = original_market_value_cents * math.exp(0.1275 * (after - base_overall))
    if age is not None and age >= 30:
        value *= max(0.5, 1 - 0.06 * (age - 29))
    internal_value = max(0, int(round(value / 1_000_000)) * 1_000_000)
    return ProgressionRecord(player_id, season_number, before, after, after - before, internal_value,
                             max(0, minutes_played), max(0, goals), tuple(reasons))
