"""Regression bounds for goal calibration in deterministic match simulation."""

from statistics import mean

import pytest

from app.domain.match_engine import MatchEngine, PlayerInput, TeamInput
from app.domain.squad import formation_slots


def _team(code: str, mode: str) -> TeamInput:
    formation = "4-3-3" if mode == "ELEVEN_A_SIDE" else "2-1-1"
    starters = tuple(
        PlayerInput(f"{code}-{index}", f"{code} {index}", slot.position, slot.position, slot.x, slot.y, 72, {}, index + 1)
        for index, slot in enumerate(formation_slots(mode, formation))
    )
    bench = tuple(
        PlayerInput(f"{code}-b{index}", f"{code} banco {index}", position, position, 50, 50, 69, {}, index + 20)
        for index, position in enumerate(("GK", "DF", "MF", "ST", "ST"))
    )
    return TeamInput(code, formation, starters, bench)


@pytest.mark.parametrize(
    ("mode", "minimum", "maximum"),
    (("ELEVEN_A_SIDE", 1.4, 3.0), ("FIVE_A_SIDE", 3.5, 8.0)),
)
def test_goal_rate_stays_in_a_playable_mode_specific_band(mode: str, minimum: float, maximum: float):
    """Protect against score explosions while keeping the short-side mode lively."""
    goals = []
    for seed in range(16):
        match = MatchEngine(f"balance-{mode}-{seed}", mode, _team("HOME", mode), _team("AWAY", mode), seed)
        match.run_to_end()
        goals.append(sum(match.score))

    assert minimum <= mean(goals) <= maximum
