"""Regression bounds for goal calibration in deterministic match simulation."""

from dataclasses import replace
from statistics import mean

import pytest

from app.domain.match_engine import MatchEngine, PlayerInput, TeamInput
from app.domain.squad import formation_slots
from app.domain.tactics import Tactics


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
    # Identical 72-rated sides playing a possession mirror are deliberately cagey since
    # the 2D/realism calibration (docs/DIAGNOSTICO_2D.md); the production-like mix
    # below is the band players actually experience.
    (("ELEVEN_A_SIDE", 0.6, 3.0), ("FIVE_A_SIDE", 2.0, 8.0)),
)
def test_goal_rate_stays_in_a_playable_mode_specific_band(mode: str, minimum: float, maximum: float):
    """Protect against score explosions while keeping the short-side mode lively."""
    goals = []
    for seed in range(16):
        match = MatchEngine(f"balance-{mode}-{seed}", mode, _team("HOME", mode), _team("AWAY", mode), seed)
        match.run_to_end()
        goals.append(sum(match.score))

    assert minimum <= mean(goals) <= maximum


MIX = (("POSSESSION", "WIDE"), ("COUNTER", "POSSESSION"), ("WIDE", "WIDE"), ("DIRECT", "SHORT_BUILDUP"))


@pytest.mark.parametrize(("mode", "minimum", "maximum"), (("ELEVEN_A_SIDE", 1.1, 3.6), ("FIVE_A_SIDE", 3.0, 8.5)))
def test_a_mix_of_plans_scores_like_football(mode: str, minimum: float, maximum: float):
    goals = []
    for seed in range(6):
        for home_style, away_style in MIX:
            home = replace(_team("HOME", mode), tactics=Tactics(style=home_style))
            away = replace(_team("AWAY", mode), tactics=Tactics(style=away_style))
            match = MatchEngine(f"mix-{mode}-{seed}-{home_style}", mode, home, away, seed)
            match.run_to_end()
            goals.append(sum(match.score))
    assert minimum <= mean(goals) <= maximum


def test_no_style_dominates_between_equal_sides():
    """Before the calibration COUNTER beat POSSESSION 3.2-0.9 between identical teams."""
    edge = []
    for seed in range(10):
        for flip in (False, True):
            counter, possession = Tactics(style="COUNTER"), Tactics()
            home_t, away_t = (possession, counter) if flip else (counter, possession)
            match = MatchEngine(f"edge-{seed}", "ELEVEN_A_SIDE", replace(_team("HOME", "ELEVEN_A_SIDE"), tactics=home_t),
                                replace(_team("AWAY", "ELEVEN_A_SIDE"), tactics=away_t), seed)
            match.run_to_end()
            ours, theirs = (match.score[1], match.score[0]) if flip else (match.score[0], match.score[1])
            edge.append(ours - theirs)
    assert mean(edge) < 1.0
