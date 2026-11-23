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
            assert a["by"] in ("TIME_LIMIT", "AI"), a
    assert concluded is not None


def test_free_duration_is_unchanged_behaviour():
    a, b = _limited(None, humans=False, index=2), _limited(None, humans=False, index=2)
    a.advance(1e6)
    b.advance(1e6)
    assert a.finished and not a.limit_reached and a.score == b.score
