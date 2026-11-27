"""End of an interactive match (Modo Jogável): the regression suite for the "frozen screen".

The freeze happened around the final whistle, so these tests pin the whole ending:

  * the round is committed exactly once, at the safe point after the whistle;
  * the official result never changes afterwards (a second commit is refused);
  * a coach who is away at the whistle (disconnected / closed tab) does not block it;
  * a duplicated gesture is idempotent and a late one never reaches a finished match;
  * polling the same state twice (what 2D and 3D clients do, at their own pace) never
    advances the match nor changes the score — the renderer is presentation only;
  * after the commit the endpoint answers "NONE" (the screen shows the result), and
    re-opening the round does not restart the simulation.
"""

from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.domain.highlights import HL_PITCH
from app.tests.test_competition_flow import new_competition


def _interactive_round(room: str, engine: str = "v6"):
    """Two human coaches in an interactive 4-club knockout, round already live."""
    settings = get_settings()
    previous = settings.gameplay_engine
    settings.gameplay_engine = engine
    try:
        service, market, clubs, now = new_competition(
            "DRAFT_KNOCKOUT", 4, {"execution_mode": "INTERACTIVE", "decision_seconds": 5}, room=room)
    finally:
        settings.gameplay_engine = previous
    humans = set(clubs[:2])
    season = service._season(room)
    season.human_clubs = humans
    for club in sorted(humans):
        if service.preview(room, market, club).get("fixture"):
            service.ready(room, club)
    while not season.live_round:
        service.advance(room, market, humans, 60)
        if not season.live_round:
            now[0] += 301
            service.start_if_preparation_expired(room, market, humans, 300, 60)
    return service, market, clubs, humans, now, season


def _play_to_the_whistle(service, season, now, step: float = 0.5, limit: int = 20000) -> None:
    """Time passes with nobody polling: every session must still reach FULL_TIME."""
    for _ in range(limit):
        now[0] += step
        service.advance_highlights(season, now[0])
        if all(session.finished for session in season.highlights.values()):
            return
    raise AssertionError("an interactive session never reached the final whistle")


def _commit(service, room, season, now) -> None:
    whistle = max(float(session.finished_at) for session in season.highlights.values())
    now[0] = max(whistle + service.FINAL_WHISTLE_SECONDS + 0.5, float(season.live_round["ends_at"]) + 0.1)
    assert service.ready_to_finish(room) is True
    assert service.finish_due(room) is True


@pytest.mark.parametrize("engine", ["v6", "v8"])
def test_final_whistle_records_the_result_once_and_never_changes_it(engine: str) -> None:
    room = f"finish-{engine}"
    service, _market, _clubs, humans, now, season = _interactive_round(room, engine)
    sessions = {session.match_id: session for session in season.highlights.values()}
    assert sessions, "the round has no interactive match"
    _play_to_the_whistle(service, season, now)
    club = next(c for session in sessions.values() for c in session.clubs if c in humans)
    assert service.interactive_view(room, club)["state"] == "FINISHED"

    _commit(service, room, season, now)
    records = {match_id: dict(season.matches[match_id]) for match_id in sessions}
    assert not season.highlights, "a committed session must leave the round"
    for record in records.values():
        assert record["status"] == "FINISHED"
        assert record["interactive"] is True
        goals = [event for event in record["events"] if event["kind"] == "GOAL"]
        assert len(goals) == int(record["home_goals"]) + int(record["away_goals"])

    # The same screen polling again (or a second tab) sees "NONE", not a restarted match.
    assert service.interactive_view(room, club)["state"] == "NONE"
    assert service._interactive_match_for(season, club) is None
    # Committing twice is a no-op: no second record, no duplicated events.
    assert service.finish_due(room) is False
    for match_id, record in records.items():
        assert season.matches[match_id] == record
    assert season.live_round is None


def test_a_coach_away_at_the_whistle_does_not_block_the_round() -> None:
    room = "finish-away"
    service, _market, _clubs, humans, now, season = _interactive_round(room)
    session = next(iter(season.highlights.values()))
    club = next(c for c in session.clubs if c in humans)
    # He was never connected during this match: the decisions go to the contextual AI.
    assert session.connected(club, now[0]) is False
    _play_to_the_whistle(service, season, now)
    assert session.finished
    _commit(service, room, season, now)
    assert session.match_id not in season.highlights
    assert season.matches[session.match_id]["status"] == "FINISHED"


def test_duplicate_and_late_gestures_never_duplicate_the_result() -> None:
    room = "finish-duplicate"
    service, _market, _clubs, humans, now, season = _interactive_round(room)
    session = next(iter(season.highlights.values()))
    club = next(c for c in session.clubs if c in humans)
    for _ in range(400):
        now[0] += 0.25
        session.seen(club, now[0])
        session.advance(now[0])
        if session.state == "DECISION" and session.opportunity and session.opportunity["attacking"] == club:
            break
    assert session.state == "DECISION"
    opportunity = session.opportunity
    length, width = HL_PITCH[session.mode]["length"], HL_PITCH[session.mode]["width"]
    right = bool(opportunity.get("right", True))
    body = next(b for b in opportunity["bodies"] if b["id"] == opportunity["carrier"])
    carrier = session.to_world(body["x"] / length, body["y"] / width, right)
    # The farthest corner: always a valid drag (more than 0.8 m from the carrier).
    target = max(((x, y) for x in (0.05, 0.95) for y in (0.05, 0.95)),
                 key=lambda p: (p[0] - carrier[0]) ** 2 + (p[1] - carrier[1]) ** 2)
    payload = {"action_id": "regression-action-1", "opportunity_id": opportunity["id"], "revision": session.revision,
               "type": "SHOT", "x": target[0], "y": target[1], "power": 0.7}
    first = session.submit(club, payload, now[0])
    revision, shots = first["revision"], session.stats[club]["shots"]
    assert session.submit(club, payload, now[0]) == {"status": "DUPLICATE", "revision": revision}
    assert session.revision == revision and session.stats[club]["shots"] == shots

    _play_to_the_whistle(service, season, now)
    _commit(service, room, season, now)
    record = season.matches[session.match_id]
    events = len(record["events"])
    late = dict(payload, action_id="regression-action-late", revision=session.revision)
    with pytest.raises(ValueError):
        session.submit(club, late, now[0])
    assert len(season.matches[session.match_id]["events"]) == events
    assert season.matches[session.match_id] == record


def test_polling_the_same_state_twice_never_changes_it() -> None:
    """2D and 3D clients poll the same session at their own pace (presentation only)."""
    room = "finish-polling"
    service, _market, _clubs, humans, now, season = _interactive_round(room)
    session = next(iter(season.highlights.values()))
    club = next(c for c in session.clubs if c in humans)
    now[0] += 1.0
    first = service.interactive_view(room, club)
    second = service.interactive_view(room, club, first.get("revision"))
    if second.get("unchanged"):
        assert second["revision"] == first["revision"]
    else:
        assert (second["revision"], second["score"]) == (first["revision"], first["score"])
    assert service.interactive_view(room, club)["revision"] == first["revision"]
    # Both coaches read the same official state (the 2D and the 3D screen).
    rival = next(c for session in season.highlights.values() for c in session.clubs if c not in humans)
    other = service.interactive_view(room, rival)
    assert (other["revision"], other["score"]) == (first["revision"], first["score"])
    _play_to_the_whistle(service, season, now)
    final = service.interactive_view(room, club)
    assert final["state"] == "FINISHED"
    _commit(service, room, season, now)
    record = season.matches[session.match_id]
    assert (record["home_goals"], record["away_goals"]) == (final["score"]["home"], final["score"]["away"])
