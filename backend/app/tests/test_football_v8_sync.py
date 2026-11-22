"""V8 match integrity under hostile conditions: every event exactly once.

Two human coaches with simulated clients that:
- poll from several "screens";
- send gestures and resend the same action id;
- send stale revisions;
- disappear in the middle of their attack (reconnecting inside or after the 30 s grace);
- let the decision timer expire.

At the end, the official record built from the match must match the match itself (score
= goal events, unique event ids, shots >= on target, the record's statistics). Covers
goals for both sides, consecutive goals, saves, rebounds, crosses/headers and
penalties when the seeds produce them (the test asserts they were exercised).
"""

from __future__ import annotations

import collections
import random

from app.domain.highlights import HighlightMatch
from app.services.season_service import highlight_record, team_input_view
from app.tests.test_football_v7 import _fixtures


def _play_hostile(index: int, seed: int) -> tuple[HighlightMatch, collections.Counter]:
    mid, home, away, base_seed = _fixtures(n=8)[index % 8]
    clubs = [home.club_code, away.club_code]
    match = HighlightMatch.create(mid, "ELEVEN_A_SIDE", home, away, team_input_view(home), team_input_view(away), clubs, base_seed + seed,
                                  "TRADITIONAL", 5, False, 0.0, engine="v8")
    rng = random.Random(seed)
    seen = collections.Counter()
    now, away_until = 0.0, {c: -1.0 for c in clubs}
    for _ in range(20000):
        if match.finished:
            break
        now += 0.35
        for club in clubs:
            if now >= away_until[club]:
                match.seen(club, now)          # this client polls (connected)
        match.advance(now)
        for club in clubs:
            match.view(club, now)              # a second screen of the same coach
        opp = match.opportunity
        if match.state != "DECISION" or not opp:
            continue
        club = str(opp["attacking"])
        if now < away_until[club]:
            continue
        roll = rng.random()
        if roll < 0.06:
            away_until[club] = now + rng.choice((8.0, 45.0))   # drops: back inside / after the grace
            seen["disconnect"] += 1
            continue
        if roll < 0.12:
            seen["timeout"] += 1               # lets the timer expire (AI decides)
            continue
        carrier = next(b for b in opp["bodies"] if b["id"] == opp["carrier"])
        right = bool(opp["right"])
        kind = rng.choice(("PASS", "PASS", "SHOT", "LOFT", "CARRY"))
        tx = 1.0 if kind == "SHOT" else min(1.0, (carrier["x"] + rng.uniform(8, 20)) / 105)
        ty = rng.uniform(0.45, 0.55) if kind == "SHOT" else min(1.0, max(0.0, (carrier["y"] + rng.uniform(-12, 12)) / 68))
        x, y = HighlightMatch.to_world(tx, ty, right)
        payload = {"action_id": f"{opp['id']}-{opp['actions']}-{seed}", "opportunity_id": opp["id"], "revision": match.revision,
                   "type": kind, "x": x, "y": y, "power": round(rng.uniform(0.3, 0.9), 2)}
        try:
            first = match.submit(club, payload, now)
            seen["accepted"] += first["status"] == "ACCEPTED"
            again = match.submit(club, payload, now)                 # the same gesture twice (double tap)
            seen["duplicate"] += again["status"] == "DUPLICATE"
        except ValueError:
            seen["refused"] += 1
        try:
            match.submit(club, {**payload, "action_id": payload["action_id"] + "-stale"}, now)   # stale revision
            seen["stale_applied"] += 1
        except ValueError:
            seen["stale_refused"] += 1
    return match, seen


def test_events_are_recorded_exactly_once_under_hostile_clients():
    totals = collections.Counter()
    kinds = collections.Counter()
    for i in range(30):
        match, seen = _play_hostile(i, 100 + i)
        assert match.finished
        totals.update(seen)
        ids = [e["event_id"] for e in match.events]
        assert len(ids) == len(set(ids)), "an event was recorded twice"
        goals = [e for e in match.events if e["kind"] == "GOAL"]
        assert [sum(1 for g in goals if g["team"] == c) for c in match.clubs] == match.score
        for club in match.clubs:
            st = match.stats[club]
            assert st["shots_on_target"] <= st["shots"] and st["passes_completed"] <= st["passes"]
        record = highlight_record(match, {"id": match.match_id, "home": match.clubs[0], "away": match.clubs[1], "seed": match.seed}, "REALISTIC")
        assert (record["home_goals"], record["away_goals"]) == tuple(match.score)
        assert len(record["action_log"]) == len(match.action_log)
        applied = [a for a in match.action_log if a["by"] == "HUMAN"]
        assert len(applied) == seen["accepted"], "a duplicate or stale gesture was applied"
        for e in match.events:
            kinds[e["kind"]] += 1
        kinds["both_scored"] += all(match.score)
        kinds["consecutive_goals"] += any(a["kind"] == b["kind"] == "GOAL" and a["team"] == b["team"]
                                          for a, b in zip(goals, goals[1:], strict=False))
        kinds["penalty"] += any(e["kind"] == "CHANCE" and e["outcome"] == "PENALTY" for e in match.events)
        kinds["header_shot"] += any(e["kind"] == "SHOT" and e.get("header") for e in match.events)
    assert totals["stale_applied"] == 0
    assert totals["duplicate"] == totals["accepted"]
    # The hostile behaviours and the rich events were really exercised (not an empty test).
    assert totals["disconnect"] > 5 and totals["timeout"] > 5 and totals["accepted"] > 50
    assert kinds["GOAL"] > 0 and kinds["SAVE"] > 0 and kinds["both_scored"] > 0 and kinds["consecutive_goals"] > 0
    assert kinds["header_shot"] > 0 and kinds["penalty"] > 0
