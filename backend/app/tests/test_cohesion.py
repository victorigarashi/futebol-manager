"""Entrosamento tático, instruções individuais, estilo de simulação e formação ao vivo."""

from dataclasses import replace

import pytest

from app.domain.cohesion import (
    FAMILIARITY_FLOOR,
    FAMILIARITY_START,
    cohesion_factor,
    compatibility,
    familiarity_after_match,
    validate_instruction,
)
from app.domain.match_engine import FULL_TIME_TICK, MatchEngine, replay_engine
from app.tests.test_match_engine import team


def row(attrs, overall=70, pos="MF", role="MF", instruction="BALANCED", natural=True):
    return {"attributes": attrs, "overall": overall, "slot_position": pos, "role": role,
            "instruction": instruction, "natural": natural, "estimated": False}


def test_compatibility_measures_fit_not_quality():
    fast = {"pace": 85, "passing": 70, "shooting": 72, "dribbling": 66, "defending": 55, "physical": 60}
    slow = {"pace": 52, "passing": 74, "shooting": 64, "dribbling": 72, "defending": 70, "physical": 76}
    counter_fast = compatibility([row(fast)] * 5, "COUNTER", "MEDIUM", "BALANCED")["score"]
    counter_slow = compatibility([row(slow)] * 5, "COUNTER", "MEDIUM", "BALANCED")["score"]
    possession_slow = compatibility([row(slow)] * 5, "POSSESSION", "MEDIUM", "BALANCED")["score"]
    assert counter_fast > counter_slow
    assert possession_slow > counter_slow  # the same players suit another plan better
    # A weaker squad with the right profile beats a stronger one with the wrong profile.
    weak_fit = {k: v - 10 for k, v in fast.items()}
    assert compatibility([row(weak_fit, overall=60)] * 5, "COUNTER", "MEDIUM", "BALANCED")["score"] > counter_slow


def test_improvised_players_and_unbalanced_instructions_cost_compatibility():
    attrs = {"pace": 70, "passing": 70, "shooting": 70, "dribbling": 70, "defending": 70, "physical": 70}
    natural = compatibility([row(attrs)] * 4, "POSSESSION", "MEDIUM", "BALANCED")["score"]
    improvised = compatibility([row(attrs, natural=False)] * 4, "POSSESSION", "MEDIUM", "BALANCED")["score"]
    assert improvised < natural
    fullbacks = [row(attrs, pos="DF", role="FB", instruction="OVERLAP")] * 2 + [row(attrs)] * 2
    report = compatibility(fullbacks, "POSSESSION", "MEDIUM", "BALANCED")
    assert report["notes"] and "volante" in report["notes"][0]


def test_instructions_are_validated_per_role():
    assert validate_instruction("ST", "FALSE_9") == "FALSE_9"
    with pytest.raises(ValueError):
        validate_instruction("GK", "FALSE_9")
    with pytest.raises(ValueError):
        validate_instruction("FB", "HOLD")


def test_familiarity_grows_gradually_and_is_not_wiped_by_a_change():
    fam: dict[str, float] = {}
    history = []
    for _ in range(10):
        fam = familiarity_after_match(fam, "COUNTER")
        history.append(fam["COUNTER"])
    assert history == sorted(history) and history[0] < 40 and history[-1] < 75  # no instant mastery
    assert fam["POSSESSION"] <= FAMILIARITY_START
    learned = fam["COUNTER"]
    for _ in range(5):
        fam = familiarity_after_match(fam, "POSSESSION")
    assert learned - 5 <= fam["COUNTER"] < learned  # fades slowly
    for _ in range(500):
        fam = familiarity_after_match(fam, "POSSESSION")
    assert fam["COUNTER"] >= FAMILIARITY_FLOOR and fam["POSSESSION"] < 100


def test_cohesion_factor_is_bounded_and_centred():
    assert cohesion_factor(50, 50) == 0
    assert cohesion_factor(100, 100) == 1 and cohesion_factor(0, 0) == -1
    assert -1 <= cohesion_factor(80, 10) <= 1


def test_defaults_keep_the_engine_identical():
    """Neutral cohesion, no instructions and REALISTIC add no random draws."""
    a = MatchEngine("m", "FIVE_A_SIDE", team("AAA", "FIVE_A_SIDE"), team("BBB", "FIVE_A_SIDE"), 3)
    b = MatchEngine("m", "FIVE_A_SIDE", replace(team("AAA", "FIVE_A_SIDE"), cohesion=0.0, instructions={}),
                    team("BBB", "FIVE_A_SIDE"), 3, "REALISTIC")
    a.run_to_end()
    b.run_to_end()
    assert a.score == b.score and len(a.events) == len(b.events)


def _results(n, mode, home_cohesion, away_cohesion, style="REALISTIC"):
    scores = []
    for seed in range(n):
        home = replace(team("AAA", mode), cohesion=home_cohesion)
        away = replace(team("BBB", mode), cohesion=away_cohesion)
        engine = MatchEngine("m", mode, home, away, seed, style)
        engine.run_to_end()
        scores.append(tuple(engine.score))
    return scores


def test_cohesion_is_noticeable_but_never_a_guarantee():
    # Mirror the fixture so the home side's edge cancels out.
    forward = _results(36, "FIVE_A_SIDE", 1.0, -1.0)
    mirrored = _results(36, "FIVE_A_SIDE", -1.0, 1.0)
    diffs = [h - a for h, a in forward] + [a - h for h, a in mirrored]
    wins = sum(d > 0 for d in diffs)
    assert sum(diffs) / len(diffs) > 0.15        # perceptible
    assert wins < len(diffs) * 0.85              # the less cohesive side still wins or draws often
    assert any(d < 0 for d in diffs)


def test_exciting_style_creates_more_goals_without_absurd_scores():
    realistic = _results(24, "ELEVEN_A_SIDE", 0, 0, "REALISTIC")
    exciting = _results(24, "ELEVEN_A_SIDE", 0, 0, "EXCITING")
    goals_r = sum(h + a for h, a in realistic)
    goals_e = sum(h + a for h, a in exciting)
    assert goals_e > goals_r
    assert goals_e / len(exciting) < 4.5 and max(h + a for h, a in exciting) <= 10
    with pytest.raises(ValueError):
        MatchEngine("m", "ELEVEN_A_SIDE", team("AAA"), team("BBB"), 1, "ARCADE")


def test_overlapping_fullback_plays_higher_than_one_told_to_stay_back():
    def mean_depth(instruction):
        home = team("AAA")
        fb = home.starters[1]  # 4-3-3: first defender is a full-back (x = 20)
        engine = MatchEngine("m", "ELEVEN_A_SIDE", replace(home, instructions={fb.id: instruction}), team("BBB"), 5)
        total = count = 0
        while not engine.finished:
            engine.step()
            if engine.possession_side == 0 and engine.phase in ("FIRST_HALF", "SECOND_HALF"):
                agent = engine.by_id[fb.id]
                total += engine.fwd(0, agent.x)
                count += 1
        return total / count
    assert mean_depth("OVERLAP") > mean_depth("STAY_BACK") + 3


def test_live_formation_change_moves_players_and_replays_identically():
    engine = MatchEngine("m", "ELEVEN_A_SIDE", team("AAA"), team("BBB"), 9)
    engine.advance_to(1500)
    status = engine.queue_formation(0, "5-4-1", "AAA:form-1")
    assert status["status"] == "APPLIED"
    defenders = [a for a in engine.active(0) if a.role == "DF"]
    assert len(defenders) == 5
    with pytest.raises(ValueError):
        engine.queue_formation(0, "9-9-9", "AAA:form-2")
    engine.run_to_end()
    assert engine.summary()["formations"]["home"] == "5-4-1"
    again = replay_engine("m", "ELEVEN_A_SIDE", team("AAA"), team("BBB"), 9, engine.command_log, FULL_TIME_TICK)
    assert again.score == engine.score and len(again.events) == len(engine.events)
