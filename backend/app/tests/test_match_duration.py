"""Approved match duration: A + C for competitive rooms, B for friendlies / the Lab.

A: the configured duration drives the clock, the pauses and the number of decisive
moments (never the chance of each one). C: a server-controlled limit; nothing already in
play is cut, pending/next decisions of the current move are concluded by the contextual AI
(for both teams alike), no new opportunity opens. B: free duration, unchanged behaviour.
"""

from __future__ import annotations

import pytest

from app.domain.highlights import DURATION_CHOICES, HighlightMatch
from app.services.season_service import team_input_view
from app.tests.test_football_v7 import _fixtures


def _limited(seconds: int | None, humans: bool, index: int = 0) -> HighlightMatch:
    mid, home, away, seed = _fixtures()[index]
    clubs = [home.club_code, away.club_code] if humans else []
    return HighlightMatch.create(mid, "ELEVEN_A_SIDE", home, away, team_input_view(home), team_input_view(away), clubs, seed, "ARCADE", 10, False, 0.0,
                                 engine="v8", duration_seconds=seconds or 0, limited=seconds is not None)


@pytest.mark.parametrize("seconds", DURATION_CHOICES)
def test_duration_drives_clock_pauses_and_number_of_moments(seconds):
    match = _limited(seconds, humans=False)
    assert match.duration_mode == "LIMITED" and match.limit_at == seconds
    free = _limited(None, humans=False)
    assert free.duration_mode == "FREE" and free.limit_at is None
    assert match.chance_factor <= 1.0 and match.clock_rate >= free.clock_rate
    if seconds < 180:
        assert match.chance_factor < 1.0 and len(match.timeline) <= len(free.timeline)


@pytest.mark.parametrize("seconds", DURATION_CHOICES)
def test_limit_is_server_controlled_and_bounded_with_coaches_who_never_decide(seconds):
    match = _limited(seconds, humans=True)
    now = 0.0
    while not match.finished and now < 2000:
        now += 0.25
        for club in match.clubs:
            match.seen(club, now)
        match.advance(now)          # nobody ever gestures: every decision waits for its 10 s timer
    # Either the plan (A) fitted the match in the duration, or the limit (C) closed it.
    assert match.finished and (match.limit_reached or match.finished_at <= seconds)
    # Only the move in progress (and its result banner) may run past the limit.
    assert match.finished_at - seconds < 25
    if match.limit_reached:
        assert any(e["kind"] == "TIME_LIMIT" for e in match.events)


def test_no_human_gesture_is_accepted_after_the_limit_and_the_ai_concludes_for_both_sides():
    match = _limited(60, humans=True, index=1)
    now = 0.0
    while not match.finished and now < 2000:
        now += 0.25
        for club in match.clubs:
            match.seen(club, now)
        match.advance(now)
        if match.limit_reached and match.state == "DECISION":
            pytest.fail("a human decision opened after the limit")
    concluded = {a["opportunity"].split(":")[-1] for a in match.action_log if a["by"] == "TIME_LIMIT"}
    assert match.finished
    for a in match.action_log:
        if a["at"] > 60.0 + 1e-6:
            assert a["by"] in ("TIME_LIMIT", "TIME_BUDGET", "AI"), a
    assert concluded is not None


def test_free_duration_is_unchanged_behaviour():
    a, b = _limited(None, humans=False, index=2), _limited(None, humans=False, index=2)
    a.advance(1e6)
    b.advance(1e6)
    assert a.finished and not a.limit_reached and a.score == b.score


def test_time_budget_never_takes_over_before_the_second_human_action():
    """A short match may pace a long move, but not immediately after the first pass."""
    match = _limited(60, humans=True)
    now = 0.0
    while match.state != "DECISION" and now < 60:
        now += 0.25
        for club in match.clubs:
            match.seen(club, now)
        match.advance(now)
    assert match.state == "DECISION" and match.opportunity is not None

    attacking = str(match.opportunity["attacking"])
    match.seen(attacking, now)
    match.moment_until = now - 1.0   # this moment has already spent its pacing share
    match.opportunity["actions"] = 1
    match._to_decision(now)

    assert match.state == "DECISION"
    assert match.deadline is not None and match.deadline >= now + 6.0
    assert not any(action["by"] == "TIME_BUDGET" for action in match.action_log)

    # After two human actions, pacing may safely conclude the remainder of the move.
    match.opportunity["actions"] = 2
    match._to_decision(now + 0.1)
    assert match.state == "EXECUTING"
    assert match.action_log[-1]["by"] == "TIME_BUDGET"


@pytest.mark.parametrize("seconds", DURATION_CHOICES)
def test_adaptive_pacing_keeps_the_limit_at_the_end_of_the_match(seconds):
    """People take longer than bots: the match is re-planned after every moment and a moment that
    used its share is concluded by the AI, so the limit (if it fires at all) only fires late —
    never a match cut at minute 20."""
    for index in range(3):
        match = _limited(seconds, humans=True, index=index)
        now = 0.0
        while not match.finished and now < 2000:
            now += 0.25
            for club in match.clubs:
                match.seen(club, now)
            match.advance(now)          # the worst case: every decision waits for its timer
        limit = next((e["minute"] for e in match.events if e["kind"] == "TIME_LIMIT"), None)
        assert limit is None or limit >= 60, (seconds, index, limit)
        assert match.finished_at - seconds < 25
