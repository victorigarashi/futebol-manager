"""Condensed live broadcast: maps real time to game time for one live match.

Three clocks are kept apart:

* simulation time – the engine's ticks (1 tick = 1 s of football, 5400 per match);
* presentation time – how fast those ticks are shown on screen (about 2–2.6× real
  speed during a highlight, so a pass or a run looks like football);
* match duration – the wall-clock length the host chose (90, 120 or 180 s).

The director simulates a little ahead of what is on screen (lookahead), finds the
moments worth showing (goals first, then chances by quality, then attacks), and lays
out a timeline of segments:

* ``PLAY``  – ticks shown continuously at a natural speed;
* ``CUT``   – ticks skipped with a short transition (clock spins forward);
* ``BREAK`` – clock stopped (half time, final whistle).

Segments are appended in order and never rewritten, so every viewer sees the same
broadcast and the scoreboard, clock, events and 2D positions always describe the same
tick. The final segment ends exactly at ``deadline``: the length of a match does not
depend on the clients' hardware or on how many moments the match produced.

Nothing here changes the engine's outcome: it only decides when each already
simulated tick is revealed. Coach commands are applied at the simulation frontier
(the first tick not yet planned for display), which is at most one planned segment
ahead of the screen.
"""

from __future__ import annotations

import bisect
from collections.abc import Callable
from dataclasses import dataclass

from app.domain.match_engine import FULL_TIME_TICK, TICKS_PER_HALF, MatchEngine

DURATIONS = (90, 120, 180)
DEFAULT_DURATION = 90


@dataclass(frozen=True)
class Profile:
    halftime: float        # real seconds of half-time break (clock stopped)
    final_hold: float      # real seconds frozen on the final whistle
    cut: float             # real seconds of a cut transition
    rate: float            # ticks per real second while a highlight plays
    max_build: int         # longest build-up shown before a shot (ticks)
    opening: int           # ticks shown at each kick-off of a half


PROFILES: dict[int, Profile] = {
    90: Profile(halftime=4.0, final_hold=2.5, cut=0.9, rate=2.6, max_build=16, opening=5),
    120: Profile(halftime=5.0, final_hold=3.0, cut=1.0, rate=2.4, max_build=22, opening=6),
    180: Profile(halftime=6.0, final_hold=3.0, cut=1.1, rate=2.2, max_build=28, opening=8),
}

MIN_BUILD = 6           # every highlight shows at least this much before the moment
SLOW_TICKS = 3          # the last ticks before a shot are shown slower
SLOW_FACTOR = 0.6
MERGE_GAP = 5           # gaps up to this many ticks are played through instead of cut
MAX_LEAD = 540          # one planning step looks at most 9 game minutes ahead
LEAD_CAP = 360          # do not plan further while this much is planned but not yet shown
PLAN_AHEAD = 1.5        # real seconds of timeline kept planned ahead of "now"
CHUNK = 30              # ticks simulated per lookahead step
LATE_RESERVE = 4.0      # real seconds held back for a late goal



def duration_profile(duration: int) -> Profile:
    if duration not in PROFILES:
        raise ValueError("Duração de partida inválida: escolha 90, 120 ou 180 segundos.")
    return PROFILES[duration]


def moment_importance(event: dict[str, object]) -> float:
    kind = event.get("kind")
    if kind == "GOAL":
        return 1.0
    if kind == "SHOT":
        xg = float(event.get("xg") or 0)
        value = 0.25 + 1.6 * xg + (0.12 if event.get("outcome") == "ON_TARGET" else 0.0)
        return min(0.95, value)
    if kind == "CARD" and event.get("outcome") in ("RED", "SECOND_YELLOW"):
        return 0.55
    return 0.0


@dataclass
class Moment:
    tick: int          # the decisive tick (shot, foul…)
    start: int         # earliest tick worth showing (start of the attack)
    after: int         # ticks shown after the moment
    importance: float
    label: str
    event_id: str | None = None


class Director:
    """Plans the broadcast timeline of one match. Serialisable (see `to_dict`)."""

    def __init__(self, started_at: float, duration: int, segments: list[dict[str, object]] | None = None,
                 halftime_planned: bool = False) -> None:
        self.profile = duration_profile(duration)
        self.duration = duration
        self.started_at = started_at
        self.deadline = started_at + duration
        self.segments: list[dict[str, object]] = segments or []
        self.halftime_planned = halftime_planned
        self._small_pitch = False
        self._goals_before = 0
        self._starts = [float(s["r0"]) for s in self.segments]
        self._t0s = [int(s["t0"]) for s in self.segments]

    # ------------------------------------------------------------------ state
    def to_dict(self) -> dict[str, object]:
        return {"started_at": self.started_at, "duration": self.duration, "segments": self.segments,
                "halftime_planned": self.halftime_planned}

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> Director:
        return cls(float(raw["started_at"]), int(raw["duration"]), list(raw.get("segments") or []),
                   bool(raw.get("halftime_planned")))

    @property
    def cursor_tick(self) -> int:
        return int(self.segments[-1]["t1"]) if self.segments else 0

    @property
    def cursor_real(self) -> float:
        return float(self.segments[-1]["r1"]) if self.segments else self.started_at

    @property
    def complete(self) -> bool:
        return bool(self.segments) and self.segments[-1]["k"] == "BREAK" and int(self.segments[-1]["t1"]) >= FULL_TIME_TICK

    def _min_tail(self, tick: int) -> float:
        """Shortest real time the rest of the broadcast can possibly take after `tick`."""
        if tick >= FULL_TIME_TICK:
            return 0.0
        tail = 0.6
        if tick < TICKS_PER_HALF:
            tail += self.profile.halftime + 0.6
        return tail

    def _append(self, kind: str, t0: int, t1: int, seconds: float, label: str = "") -> None:
        r0 = self.cursor_real
        # Safety net: whatever happened, the final whistle is never later than the deadline.
        seconds = min(max(0.0, seconds), max(0.0, self.deadline - self._min_tail(t1) - r0))
        r1 = r0 + seconds
        self.segments.append({"k": kind, "t0": t0, "t1": t1, "r0": round(r0, 4), "r1": round(r1, 4), "label": label})
        self._starts.append(round(r0, 4))
        self._t0s.append(int(t0))

    # ------------------------------------------------------------------ queries
    def tick_at(self, now: float) -> float:
        """Presented (fractional) tick at real time `now`."""
        if not self.segments or now <= self.started_at:
            return 0.0
        index = bisect.bisect_right(self._starts, now) - 1
        if index < 0:
            return 0.0
        segment = self.segments[index]
        t0, t1, r0, r1 = int(segment["t0"]), int(segment["t1"]), float(segment["r0"]), float(segment["r1"])
        if now >= r1 or r1 <= r0:
            return float(t1)
        return t0 + (t1 - t0) * (now - r0) / (r1 - r0)

    def shown_tick(self, now: float) -> int:
        return int(self.tick_at(now))

    def visible(self, tick: int) -> bool:
        """Frames worth sending: every tick of a PLAY segment, and the edges of cuts/breaks."""
        index = self._segment_for_tick(tick)
        if index is None:
            return False
        segment = self.segments[index]
        return segment["k"] == "PLAY" or tick in (int(segment["t0"]), int(segment["t1"]))

    def _segment_for_tick(self, tick: int) -> int | None:
        # Segments are contiguous in game time, so the last one starting at or before
        # `tick` is the latest one containing it (binary search, not a linear scan).
        index = bisect.bisect_right(self._t0s, tick) - 1
        if index < 0:
            return None
        segment = self.segments[index]
        if int(segment["t1"]) < tick:
            return None
        # Prefer a PLAY segment when two segments share a boundary tick.
        if segment["k"] != "PLAY" and index > 0 and int(self.segments[index - 1]["t1"]) == tick and self.segments[index - 1]["k"] == "PLAY":
            return index - 1
        return index

    def timeline_key(self, now: float) -> tuple[int, int]:
        """Changes when a segment is added or one finishes playing (its label is revealed)."""
        return len(self.segments), bisect.bisect_right(self._starts, now)

    def window(self, now: float, past: float = 12.0) -> list[dict[str, object]]:
        """Segments a client needs to render around `now` (nothing from the future)."""
        public = ("KICK_OFF", "HALF_TIME", "FULL_TIME")
        # A label such as GOAL would spoil the moment before it is on screen: it is only
        # revealed once the segment has been fully shown.
        return [s if float(s["r1"]) <= now or s["label"] in public else {**s, "label": ""}
                for s in self.segments if float(s["r1"]) >= now - past and float(s["r0"]) <= now]

    # ------------------------------------------------------------------ planning
    def plan(self, engine: MatchEngine, advance: Callable[[int], None], now: float) -> None:
        """Extend the timeline until it covers `now + PLAN_AHEAD` (or the match ends)."""
        if engine.mode == "FIVE_A_SIDE" and not self._small_pitch:
            # Small pitch: the same speed looks faster on screen.
            self._small_pitch = True
            self.profile = Profile(**{**self.profile.__dict__, "rate": self.profile.rate * 0.8})
        guard = 0
        while not self.complete and self.cursor_real < now + PLAN_AHEAD and guard < 64:
            # Keep the simulation frontier close to the screen (commands land sooner and
            # the engine's frame history always still holds what is being shown).
            if self.cursor_real > now + 0.3 and self.cursor_tick - self.shown_tick(now) > LEAD_CAP:
                break
            guard += 1
            if not self._plan_step(engine, advance, now):
                break

    def _plan_step(self, engine: MatchEngine, advance: Callable[[int], None], now: float) -> bool:
        p = self.profile
        T = self.cursor_tick
        if not self.segments:
            advance(p.opening)
            self._append("PLAY", 0, p.opening, p.opening / p.rate, "KICK_OFF")
            return True
        if T >= FULL_TIME_TICK:
            advance(FULL_TIME_TICK)
            self._append("BREAK", FULL_TIME_TICK, FULL_TIME_TICK, self.deadline - self.cursor_real, "FULL_TIME")
            return True
        if T == TICKS_PER_HALF and not self.halftime_planned:
            advance(TICKS_PER_HALF)
            self.halftime_planned = True
            self._append("BREAK", TICKS_PER_HALF, TICKS_PER_HALF, p.halftime, "HALF_TIME")
            return True
        if T == TICKS_PER_HALF and self.segments[-1]["label"] == "HALF_TIME":
            # Keep the engine in its half-time state while the break is on screen, so
            # substitutions made now are genuine half-time changes.
            if now < float(self.segments[-1]["r1"]) - 0.4:
                return False
            target = TICKS_PER_HALF + p.opening
            advance(target)
            self._append("PLAY", TICKS_PER_HALF, target, p.opening / p.rate, "KICK_OFF")
            return True

        half_end = TICKS_PER_HALF if T < TICKS_PER_HALF else FULL_TIME_TICK
        self._goals_before = sum(1 for e in engine.events if e["kind"] == "GOAL" and int(e["tick"]) <= T)
        pace = self._pace(T)
        limit = min(half_end, T + MAX_LEAD)
        chosen: Moment | None = None
        scan_from = T
        while chosen is None and scan_from < limit:
            chunk_end = min(limit, scan_from + CHUNK)
            # A few ticks of aftermath are needed, but never past the end of the half:
            # the half-time state must still be live while the break is on screen.
            advance(min(half_end, chunk_end + 8))
            for moment in self._moments(engine, scan_from, chunk_end):
                if self._affordable(moment, T, half_end, pace):
                    chosen = moment
                    break
            scan_from = chunk_end
        if chosen is None:
            self._cut_or_play(T, limit, pace)
            return True
        self._schedule(chosen, T, half_end, pace)
        return True

    # Budget. The real time available for football (everything but half time and the
    # whistles) is spread evenly over the 90 minutes: by game tick t the broadcast
    # "should" have used total × t / 5400. `credit` is how far ahead of that schedule we
    # are. A moment is shown when its cost fits the credit it would leave, plus an
    # allowance that grows with its importance (a goal may borrow almost anything).
    def _fixed_after(self, tick: int) -> float:
        p = self.profile
        # LATE_RESERVE: kept for a goal in the last minutes; if none comes it is spent on
        # the closing minutes (see `_cut_or_play`).
        fixed = p.final_hold + (LATE_RESERVE if tick < FULL_TIME_TICK else 0.0)
        if tick < TICKS_PER_HALF:
            fixed += p.halftime + p.opening / p.rate
        return fixed

    def _football_total(self) -> float:
        p = self.profile
        return self.duration - p.final_hold - LATE_RESERVE - p.halftime - 2 * p.opening / p.rate

    @staticmethod
    def _share(tick: int) -> float:
        """Fraction of the 90 minutes still to be played after `tick`."""
        remaining = (TICKS_PER_HALF - tick if tick < TICKS_PER_HALF else 0) + (FULL_TIME_TICK - max(tick, TICKS_PER_HALF))
        return max(0.0, min(1.0, remaining / FULL_TIME_TICK))

    def _credit(self, real: float, tick: int) -> float:
        available = self.deadline - real - self._fixed_after(tick)
        return available - self._football_total() * self._share(tick)

    def _typical_cost(self) -> float:
        p = self.profile
        build = (p.max_build + MIN_BUILD) / 2
        return p.cut + build / p.rate + (SLOW_TICKS + 1) / (p.rate * SLOW_FACTOR) + 4 / p.rate

    def _pace(self, tick: int) -> float:
        """Ahead of schedule: highlights play a little slower (down to 0.65×); behind: faster."""
        credit = self._credit(self.cursor_real, tick)
        typical = self._typical_cost()
        if credit > 0:
            return max(0.65, 1.0 - 0.35 * min(1.0, credit / (3 * typical)))
        return min(1.8, 1.0 + 0.8 * min(1.0, -credit / (3 * typical)))

    def _allowance(self, importance: float) -> float:
        if importance >= 1.0:
            return 1e9
        return self._football_total() * 0.12 * importance * importance

    def _affordable(self, moment: Moment, T: int, half_end: int, pace: float) -> bool:
        if moment.importance >= 1.0:
            return True  # goals are always shown (see `_schedule`)
        _, end, seconds, _ = self._shape(moment, T, half_end, pace)
        left = self._credit(self.cursor_real + seconds, end)
        # Something worth showing must also leave room to reach the whistles.
        room = self.deadline - self.cursor_real - seconds - self._fixed_after(end) - self.profile.cut
        return room > 0 and left + self._allowance(moment.importance) >= 0

    def _shape(self, moment: Moment, T: int, half_end: int, pace: float) -> tuple[int, int, float, bool]:
        p = self.profile
        start = max(moment.start, moment.tick - p.max_build)
        start = min(start, moment.tick - MIN_BUILD)
        start = max(T, start)
        end = min(half_end, moment.tick + moment.after)
        cut = start - T > MERGE_GAP
        if not cut:
            start = T
        rate = p.rate * pace
        slow_from = max(start, moment.tick - SLOW_TICKS)
        seconds = (slow_from - start) / rate + (min(end, moment.tick + 1) - slow_from) / (rate * SLOW_FACTOR) + max(0, end - moment.tick - 1) / rate
        return start, end, seconds + (p.cut if cut else 0.0), cut

    def _schedule(self, moment: Moment, T: int, half_end: int, pace: float) -> None:
        p = self.profile
        if moment.importance >= 1.0:
            # A goal may borrow from the schedule, but must leave room for the goals still
            # likely to come (this match's own scoring rate, blended with a league prior)
            # and never touch the whistles: when time is short it plays faster.
            _, end, _, _ = self._shape(moment, T, half_end, pace)
            played = 1.0 - self._share(T)
            rate = (self._goals_before + 1.5) / (played + 0.4)
            future = rate * self._share(end)
            room = self.deadline - self.cursor_real - self._min_tail(end) - p.final_hold * 0.5
            share_of_room = room / (future + 1.0)
            for _ in range(8):
                _, end, seconds, cut = self._shape(moment, T, half_end, pace)
                if seconds <= share_of_room or pace >= 4:
                    break
                pace *= 1.25
        start, end, seconds, cut = self._shape(moment, T, half_end, pace)
        rate = p.rate * pace
        if cut:
            self._append("CUT", T, start, p.cut if pace < 2 else min(p.cut, 0.5))
        slow_from = max(start, moment.tick - SLOW_TICKS)
        if slow_from > start:
            self._append("PLAY", start, slow_from, (slow_from - start) / rate, "BUILD_UP")
        slow_to = min(end, moment.tick + 1)
        if slow_to > slow_from:
            self._append("PLAY", slow_from, slow_to, (slow_to - slow_from) / (rate * SLOW_FACTOR), moment.label)
        if end > slow_to:
            self._append("PLAY", slow_to, end, (end - slow_to) / rate, "AFTERMATH")

    def _cut_or_play(self, T: int, target: int, pace: float) -> None:
        p = self.profile
        if target == FULL_TIME_TICK:
            # Nothing left worth a highlight: spend the spare time on the closing minutes.
            spare = self.deadline - self.cursor_real - p.final_hold - p.cut
            ticks = min(target - T, int(spare * p.rate))
            if ticks >= 4:
                start = target - ticks
                if start - T > MERGE_GAP:
                    self._append("CUT", T, start, p.cut)
                else:
                    start = T
                self._append("PLAY", start, target, min(spare, (target - start) / (p.rate * 0.65)), "FINAL_MINUTES")
                return
        if target - T <= MERGE_GAP:
            self._append("PLAY", T, target, (target - T) / (p.rate * pace))
        else:
            self._append("CUT", T, target, p.cut)

    # ------------------------------------------------------------------ moments
    def _moments(self, engine: MatchEngine, start: int, end: int) -> list[Moment]:
        """Candidate moments with start < tick <= end, in chronological order."""
        found: list[Moment] = []
        events = engine.events
        for index, event in enumerate(events):
            tick = int(event["tick"])
            if tick <= start or tick > end:
                continue
            kind = event["kind"]
            if kind == "SHOT":
                goal = event.get("outcome") == "GOAL"
                importance = 1.0 if goal else moment_importance(event)
                since = int(event.get("possession_since") or tick)
                label = "GOAL" if goal else "CHANCE"
                event_id = events[index + 1]["event_id"] if goal and index + 1 < len(events) else event["event_id"]
                found.append(Moment(tick, since - 2, 6 if goal else 3, importance, label, str(event_id)))
            elif kind == "CARD" and event.get("outcome") in ("RED", "SECOND_YELLOW"):
                found.append(Moment(tick, tick - 8, 3, moment_importance(event), "RED_CARD", str(event["event_id"])))
        found.extend(self._attack_moments(engine, start, end))
        found.sort(key=lambda m: (m.tick, -m.importance))
        # Several candidates on the same attack: keep the most important one.
        merged: list[Moment] = []
        for moment in found:
            if merged and moment.tick - merged[-1].tick <= 2:
                if moment.importance > merged[-1].importance:
                    merged[-1] = moment
                continue
            merged.append(moment)
        return merged

    @staticmethod
    def _attack_moments(engine: MatchEngine, start: int, end: int) -> list[Moment]:
        """Possessions reaching the final third with start < tick <= end.

        Pure function of the authoritative frames (it looks back a little to know whether
        the possession had already entered the final third), so a restarted server plans
        exactly the same broadcast."""
        home_count = len(engine.team_agents[0])
        depth_line = 0.72
        last_side, armed = -1, True
        found: list[Moment] = []
        for frame in engine.frames:
            tick, bx, _by, owner, _positions, state = frame
            if tick <= start - 60 or tick > end:
                continue
            if owner < 0 or state != 0:
                continue
            side = 0 if owner < home_count else 1
            depth = (bx if side == 0 else engine.L - bx) / engine.L
            if side != last_side:
                last_side, armed = side, True
            if armed and depth >= depth_line:
                armed = False
                if tick > start:
                    found.append(Moment(tick, tick - 14, 3, 0.12 + 0.2 * (depth - depth_line), "ATTACK"))
        return found


class LinearClock:
    """Score-ticker clock for a match nobody watches (bot against bot).

    There is no broadcast to plan and no 2D frames to keep: the 90 minutes simply run
    linearly over the round's real duration, with the same half-time break and final
    hold a broadcast of that length has, so its score moves in step with the matches
    the coaches are watching. Same query interface as `Director`."""

    kind = "LINEAR"

    def __init__(self, started_at: float, duration: int) -> None:
        profile = duration_profile(duration)
        self.started_at = float(started_at)
        self.duration = int(duration)
        self.deadline = self.started_at + self.duration
        self.halftime = profile.halftime
        self.half_seconds = (self.duration - profile.halftime - profile.final_hold) / 2
        self.segments: list[dict[str, object]] = []

    def to_dict(self) -> dict[str, object]:
        return {"kind": self.kind, "started_at": self.started_at, "duration": self.duration}

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> LinearClock:
        return cls(float(raw["started_at"]), int(raw["duration"]))

    def tick_at(self, now: float) -> float:
        elapsed = now - self.started_at
        if elapsed <= 0:
            return 0.0
        if elapsed < self.half_seconds:
            return TICKS_PER_HALF * elapsed / self.half_seconds
        second = elapsed - self.half_seconds - self.halftime
        if second <= 0:
            return float(TICKS_PER_HALF)
        if second < self.half_seconds:
            return TICKS_PER_HALF + TICKS_PER_HALF * second / self.half_seconds
        return float(FULL_TIME_TICK)

    def shown_tick(self, now: float) -> int:
        return int(self.tick_at(now))

    @property
    def cursor_tick(self) -> int:
        return 0

    @property
    def complete(self) -> bool:
        return False

    def visible(self, tick: int) -> bool:
        return False

    def window(self, now: float, past: float = 12.0) -> list[dict[str, object]]:
        return []

    def timeline_key(self, now: float) -> tuple[int, int]:
        return 0, 0


def clock_from_dict(raw: dict[str, object]) -> Director | LinearClock:
    return LinearClock.from_dict(raw) if raw.get("kind") == LinearClock.kind else Director.from_dict(raw)
