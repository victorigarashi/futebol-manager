"""Momentos decisivos: the interactive match engine (Modo Jogável).

A match is fast-simulated between *opportunities*; each opportunity is a short attack
played with real 2D physics. The attacking coach (human) decides one action at a time
(pass, lofted ball/cross, carry or shot: direction + power from a drag gesture); the
defence and both goalkeepers are always AI. Bot attacks are played by the same physics
with an AI choosing the actions, so their replay is the official event itself (never an
animation invented after the fact).

Everything here is deterministic and pure: the randomness of an action comes from
``Random(f"{seed}:{opportunity}:{action}")``, so a session can be serialised as plain
data and rebuilt exactly. Real time (decision deadlines, playback, reconnection grace)
is handled by ``HighlightMatch.advance(now)`` with *logical* timestamps: if nobody
polls for a minute the server catches up transition by transition, in order.

Coordinates: metres; in an opportunity the attacking side always attacks towards
x = L (its goal at (L, W/2)). The client receives normalised coordinates.

Formulas and parameters are documented in docs/MODO_JOGAVEL.md.
"""

from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass, field

from app.domain.match_engine import PITCH, PlayerInput, TeamInput, derived_attributes

# ---------------------------------------------------------------- tunables (documented)
DT = 0.1                      # physics step (s); frames are recorded every step (10 Hz)
MAX_ACTION_SECONDS = 7.0      # an action that has not resolved by then is settled by proximity
MAX_ACTIONS = 8               # anti-infinite-attack guard: after 8 actions the next control ends it
GROUND_DECEL = 5.0            # m/s² rolling friction for passes and carries
SHOT_DECEL = 1.5
PASS_SPEED = (7.0, 19.0)      # v0 = a + b * power
LOFT_SPEED = (11.0, 15.0)
SHOT_SPEED = (16.0, 18.0)
LOFT_RANGE = (12.0, 46.0)     # flight distance = a + b * power
CARRY_RANGE = (3.0, 9.0)
CONTROL_RADIUS = 0.9
TACKLE_RADIUS = 0.95
KEEPER_CLAIM_RADIUS = 1.5
CLOCK_MINUTES_PER_SECOND = 4.0  # fast simulation between opportunities: 90' in ~22 s
HALF_TIME_SECONDS = 6.0
OUTCOME_PAUSE_SECONDS = 2.2   # banner after an opportunity ends
CONNECTED_WINDOW = 6.0        # a client polling within this window counts as connected
RECONNECT_GRACE = 30.0        # approved tolerance (validation 47)
DECISION_CHOICES = (5, 10, 15, 20)
ACTION_TYPES = ("PASS", "LOFT", "CARRY", "SHOT")
KINDS = ("BUILDUP", "COUNTER", "WING", "CROSS", "THROUGH", "ONE_ON_ONE", "FREE_KICK", "PENALTY", "CORNER")
KIND_LABEL = {"BUILDUP": "Ataque trabalhado", "COUNTER": "Contra-ataque", "WING": "Jogada pela ponta",
              "CROSS": "Chegada à linha de fundo", "THROUGH": "Infiltração", "ONE_ON_ONE": "Cara a cara",
              "FREE_KICK": "Falta perigosa", "PENALTY": "Pênalti", "CORNER": "Escanteio"}


@dataclass
class Body:
    id: str
    name: str
    number: int
    team: str          # "A" attacking, "D" defending (within the opportunity)
    role: str          # GK, DF, MF, ST
    x: float
    y: float
    pace: float
    passing: float
    shooting: float
    dribbling: float
    defending: float
    physical: float
    keeping: float
    ax: float = 0.0    # tactical anchor of this phase
    ay: float = 0.0
    vx: float = 0.0
    vy: float = 0.0

    @property
    def top_speed(self) -> float:
        return 5.6 + self.pace / 100 * 3.4


@dataclass
class Ball:
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    z: float = 0.0
    air_left: float = 0.0   # seconds of flight remaining (lofted balls)
    air_total: float = 0.0


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _dist(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(ax - bx, ay - by)


def team_strength(team: TeamInput) -> tuple[float, float, float]:
    """(attack, defence, keeper) from the actual attributes of the starters (not overall alone)."""
    attack, defence, keeper = [], [], 50.0
    for player in team.starters:
        a = derived_attributes(player)
        if player.slot_position == "GK":
            keeper = a["keeping"]
            continue
        weight = {"ST": 1.3, "MF": 1.0, "DF": 0.45}.get(player.slot_position, 1.0)
        attack.append((weight, a["shooting"] * 0.3 + a["passing"] * 0.3 + a["dribbling"] * 0.25 + a["pace"] * 0.15))
        dweight = {"DF": 1.3, "MF": 0.9, "ST": 0.3}.get(player.slot_position, 1.0)
        defence.append((dweight, a["defending"] * 0.6 + a["physical"] * 0.2 + a["pace"] * 0.2))
    avg = lambda rows: sum(w * v for w, v in rows) / max(0.01, sum(w for w, _ in rows)) if rows else 50.0  # noqa: E731
    return avg(attack), avg(defence), keeper


def build_timeline(home: TeamInput, away: TeamInput, seed: int, ruleset: str) -> list[dict[str, object]]:
    """Opportunities of the match: count per team and type follow attributes, tactics and cohesion.

    Never a fixed number per team and never forced equality: lambda depends on the
    attack of one side against the defence (and keeper) of the other."""
    rng = random.Random(f"{seed}:timeline")
    strengths = [team_strength(home), team_strength(away)]
    rows: list[dict[str, object]] = []
    for side, team in enumerate((home, away)):
        att = strengths[side][0]
        dfn, gk = strengths[1 - side][1], strengths[1 - side][2]
        mentality = {"ATTACKING": 1.15, "VERY_ATTACKING": 1.25, "DEFENSIVE": 0.85, "VERY_DEFENSIVE": 0.75}.get(team.tactics.mentality, 1.0)
        rate = 4.2 * math.exp((att - (dfn * 0.8 + gk * 0.2)) / 18) * mentality * (1 + 0.12 * team.cohesion)
        count = 0
        # Poisson draw (Knuth), clamped to a playable range.
        limit, product = math.exp(-_clamp(rate, 1.2, 8.0)), rng.random()
        while product > limit:
            count += 1
            product *= rng.random()
        count = int(_clamp(count, 1, 9))
        style = team.tactics.style
        weights = {"BUILDUP": 3.0, "COUNTER": 2.0, "WING": 2.0, "CROSS": 1.5, "THROUGH": 1.8, "ONE_ON_ONE": 0.5}
        weights[{"POSSESSION": "BUILDUP", "SHORT_BUILDUP": "BUILDUP", "COUNTER": "COUNTER", "WIDE": "WING", "DIRECT": "THROUGH"}.get(style, "BUILDUP")] += 2.5
        if style == "WIDE":
            weights["CROSS"] += 1.5
        if ruleset == "TRADITIONAL":
            weights["FREE_KICK"] = 0.8
            weights["PENALTY"] = 0.25
        for _ in range(count):
            kind = rng.choices(list(weights), list(weights.values()))[0]
            rows.append({"side": side, "kind": kind, "minute": round(rng.uniform(2, 89.5), 1)})
    rows.sort(key=lambda r: (r["minute"], r["side"]))
    for index, row in enumerate(rows):
        row["index"] = index
    return rows


# ---------------------------------------------------------------- scenario (opportunity set-up)
def _bodies(team: TeamInput, tag: str) -> list[Body]:
    bodies = []
    for player in team.starters:
        a = derived_attributes(player)
        bodies.append(Body(player.id, player.name, player.number, tag, player.slot_position if player.slot_position in ("GK", "DF", "MF", "ST") else "MF",
                           0.0, 0.0, a["pace"], a["passing"], a["shooting"], a["dribbling"], a["defending"], a["physical"], a["keeping"]))
    return bodies


def _forwardness(player: PlayerInput) -> float:
    # formation_slots: slot_y is depth from the own goal (89 = goalkeeper, small = striker)
    return _clamp(1 - player.slot_y / 100, 0.0, 1.0)


def build_scenario(kind: str, attack: TeamInput, defence: TeamInput, mode: str, rng: random.Random) -> tuple[list[Body], Ball, str]:
    """Valid positions for an opportunity of this kind: attackers by formation pushed up,
    the defence in its block (displaced on counters), keepers in goal, nobody overlapping."""
    cfg = PITCH[mode]
    L, W = cfg["length"], cfg["width"]
    s = L / 105.0  # scale everything for the five-a-side pitch
    attackers, defenders = _bodies(attack, "A"), _bodies(defence, "D")
    for body, player in zip(attackers, attack.starters, strict=True):
        f = _forwardness(player)
        if body.role == "GK":
            body.x, body.y = 8 * s, W / 2
        else:
            push = {"COUNTER": 0.62, "ONE_ON_ONE": 0.6}.get(kind, 0.72)
            body.x = (30 + f * 62 * push / 0.72) * s
            body.y = player.slot_x / 100 * W
    for body, player in zip(defenders, defence.starters, strict=True):
        f = _forwardness(player)
        if body.role == "GK":
            body.x, body.y = L - 1.2 * s, W / 2
        else:
            depth = (9 + f * 42) * s
            if kind == "COUNTER":
                depth += 14 * s * (1 - f)        # caught upfield
            body.x = L - depth
            body.y = W / 2 + (player.slot_x / 100 * W - W / 2) * 0.78  # compact block
    outfield = [b for b in attackers if b.role != "GK"]
    by_role = lambda *roles: [b for b in outfield if b.role in roles] or outfield  # noqa: E731
    if kind in ("BUILDUP",):
        carrier = rng.choice(by_role("MF"))
        carrier.x = min(carrier.x, (58 + rng.uniform(-4, 6)) * s)
    elif kind == "COUNTER":
        carrier = max(by_role("MF", "ST"), key=lambda b: b.pace + rng.uniform(0, 8))
        carrier.x, carrier.y = (52 + rng.uniform(0, 8)) * s, W / 2 + rng.uniform(-10, 10) * s
        # Two defensive midfielders are beaten (behind the ball).
        for body in sorted([b for b in defenders if b.role == "MF"], key=lambda b: b.x)[:2]:
            body.x = carrier.x - rng.uniform(3, 7) * s
    elif kind == "WING":
        carrier = min(outfield, key=lambda b: min(b.y, W - b.y))
        carrier.x, carrier.y = (70 + rng.uniform(0, 8)) * s, 6 * s if carrier.y < W / 2 else W - 6 * s
    elif kind == "CROSS":
        carrier = min(outfield, key=lambda b: min(b.y, W - b.y))
        carrier.x, carrier.y = L - (11 + rng.uniform(0, 5)) * s, 5 * s if carrier.y < W / 2 else W - 5 * s
    elif kind == "THROUGH":
        carrier = max(by_role("MF"), key=lambda b: b.x)
        carrier.x, carrier.y = (68 + rng.uniform(0, 6)) * s, W / 2 + rng.uniform(-8, 8) * s
    elif kind == "ONE_ON_ONE":
        carrier = max(by_role("ST"), key=lambda b: b.pace + b.shooting)
        carrier.x, carrier.y = L - (24 + rng.uniform(0, 6)) * s, W / 2 + rng.uniform(-6, 6) * s
        for body in defenders:
            if body.role != "GK" and body.x > carrier.x - 2 * s:
                body.x = carrier.x - rng.uniform(2, 10) * s   # the line is beaten: only one recovers
        chaser = max((b for b in defenders if b.role != "GK"), key=lambda b: b.pace)
        chaser.x, chaser.y = carrier.x - 2.5 * s, carrier.y + rng.choice((-2.5, 2.5)) * s
    elif kind == "FREE_KICK":
        carrier = max(outfield, key=lambda b: b.shooting + b.passing)
        carrier.x, carrier.y = L - (20 + rng.uniform(0, 8)) * s, W / 2 + rng.uniform(-9, 9) * s
        _wall(defenders, carrier, L, W, s)
    elif kind == "PENALTY":
        carrier = max(outfield, key=lambda b: b.shooting)
        carrier.x, carrier.y = L - 11 * s, W / 2
        for body in attackers + defenders:
            if body is not carrier and body.role != "GK":
                body.x = min(body.x, L - (17.5 * s))  # everybody outside the box
    else:  # CORNER (continuation of an attack)
        carrier = max(outfield, key=lambda b: b.passing)
        carrier.x, carrier.y = L - 0.3, 0.3 if rng.random() < 0.5 else W - 0.3
    _separate(attackers + defenders, carrier, L, W)
    if kind in ("CROSS", "CORNER", "FREE_KICK"):
        # Bodies in the box for the delivery.
        box = [b for b in sorted(outfield, key=lambda b: -b.x) if b is not carrier][:4]
        for body in box:
            body.x = _clamp(body.x, L - 16 * s, L - 6 * s)
            body.y = _clamp(body.y, W / 2 - 9 * s, W / 2 + 9 * s)
        _separate(attackers + defenders, carrier, L, W)
    for body in attackers + defenders:
        body.ax, body.ay = body.x, body.y
    ball = Ball(carrier.x + 0.4, carrier.y)
    return attackers + defenders, ball, carrier.id


def _wall(defenders: list[Body], carrier: Body, L: float, W: float, s: float) -> None:
    gx, gy = L, W / 2
    d = _dist(carrier.x, carrier.y, gx, gy)
    ux, uy = (gx - carrier.x) / d, (gy - carrier.y) / d
    wall = sorted([b for b in defenders if b.role != "GK"], key=lambda b: _dist(b.x, b.y, carrier.x, carrier.y))[:4]
    for i, body in enumerate(wall):
        offset = (i - (len(wall) - 1) / 2) * 0.75
        body.x = carrier.x + ux * 9.15 * s - uy * offset
        body.y = carrier.y + uy * 9.15 * s + ux * offset


def _separate(bodies: list[Body], carrier: Body, L: float, W: float) -> None:
    """Nobody inside anybody (1.3 m), everybody on the pitch; the carrier keeps its spot."""
    for _ in range(6):
        for i, a in enumerate(bodies):
            for b in bodies[i + 1:]:
                d = _dist(a.x, a.y, b.x, b.y)
                if d < 1.3:
                    angle = (hash((a.id, b.id)) % 628) / 100 if d < 1e-6 else math.atan2(b.y - a.y, b.x - a.x)
                    push = (1.3 - d) / 2 + 0.01
                    if a is not carrier:
                        a.x -= math.cos(angle) * push
                        a.y -= math.sin(angle) * push
                    if b is not carrier:
                        b.x += math.cos(angle) * push
                        b.y += math.sin(angle) * push
        for body in bodies:
            body.x, body.y = _clamp(body.x, 0.5, L - 0.3), _clamp(body.y, 0.3, W - 0.3)


# ---------------------------------------------------------------- physics of one action
@dataclass
class ActionResult:
    outcome: str                    # CONTROLLED, LOST, GOAL, SAVED_HELD, OUT, CORNER, STALLED
    frames: list[list[float]]
    receiver: str | None = None
    detail: str = ""
    shot: bool = False
    on_target: bool = False
    xg: float = 0.0
    keeper: str | None = None
    lost_to: str | None = None
    completed_pass: bool = False


class Pitch:
    """Physics + AI movement of one action. Bodies and ball are mutated in place."""

    def __init__(self, bodies: list[Body], ball: Ball, mode: str, rng: random.Random, pressure_boost: float = 0.0) -> None:
        cfg = PITCH[mode]
        self.L, self.W, self.goal = cfg["length"], cfg["width"], cfg["goal"]
        self.bodies, self.ball, self.rng = bodies, ball, rng
        self.boost = pressure_boost
        self.attackers = [b for b in bodies if b.team == "A"]
        self.defenders = [b for b in bodies if b.team == "D"]
        self.keeper = next((b for b in self.defenders if b.role == "GK"), None)
        self.shot_live = False

    def frame(self, t: float) -> list[float]:
        b = self.ball
        row = [round(t, 2), round(b.x / self.L, 3), round(b.y / self.W, 3), round(b.z, 1)]
        for body in self.bodies:
            row += [round(body.x / self.L, 3), round(body.y / self.W, 3)]
        return row

    def pressure_on(self, body: Body) -> float:
        nearest = min((_dist(body.x, body.y, d.x, d.y) for d in self.defenders if d.role != "GK"), default=20.0)
        return _clamp(1 - nearest / 4.5, 0.0, 1.0)

    def xg(self, x: float, y: float) -> float:
        d = _dist(x, y, self.L, self.W / 2)
        angle = abs(math.atan2(self.goal * (self.L - x), (self.L - x) ** 2 + (y - self.W / 2) ** 2 - (self.goal / 2) ** 2))
        scale = 105 / self.L
        return round(_clamp(0.9 * angle * math.exp(-d * scale / 22), 0.01, 0.8), 3)

    # ------------------------------------------------------------ movement AI
    def _steer(self, body: Body, tx: float, ty: float, intensity: float = 1.0) -> None:
        tx, ty = _clamp(tx, 0.3, self.L - 0.2), _clamp(ty, 0.3, self.W - 0.3)
        dx, dy = tx - body.x, ty - body.y
        d = math.hypot(dx, dy)
        top = body.top_speed * intensity
        desired = min(top, d * 2.2)
        dvx, dvy = (dx / d * desired, dy / d * desired) if d > 1e-6 else (0.0, 0.0)
        accel = 7.5 * DT
        body.vx += _clamp(dvx - body.vx, -accel, accel)
        body.vy += _clamp(dvy - body.vy, -accel, accel)
        body.x += body.vx * DT
        body.y += body.vy * DT

    def _ball_at(self, seconds: float) -> tuple[float, float]:
        b = self.ball
        speed = math.hypot(b.vx, b.vy)
        if speed < 1e-6:
            return b.x, b.y
        decel = GROUND_DECEL if b.air_left <= 0 else 0.0
        travel = speed * seconds - 0.5 * decel * seconds * seconds if decel else speed * seconds
        if decel:
            travel = min(travel, speed * speed / (2 * decel))
        return b.x + b.vx / speed * travel, b.y + b.vy / speed * travel

    def move_players(self, t: float, carrier: Body | None, intended: Body | None, chasers: set[str], marks: dict[str, Body]) -> None:
        b = self.ball
        for body in self.bodies:
            if body is carrier:
                continue
            if body.team == "A":
                if body is intended:
                    # Attack the ball's path (meet the pass, not where it was).
                    tx, ty = self._ball_at(0.45)
                    self._steer(body, tx, ty)
                elif body.role == "GK":
                    self._steer(body, body.ax, body.ay, 0.4)
                else:
                    # Support/desmarque: runs into depth up to the last line, spreading out.
                    line = max((d.x for d in self.defenders if d.role != "GK"), default=self.L - 10)
                    run = min(body.ax + 2.2 * t, line + (1.5 if body.role == "ST" else -1.0))
                    spread = body.ay + (body.ay - b.y) * 0.08
                    self._steer(body, max(body.ax, run), spread, 0.8)
            else:
                if body.role == "GK":
                    if not self.shot_live:
                        self._keeper_position(body)
                    continue
                reaction = 0.35 - body.defending / 100 * 0.2 - self.boost
                if t < reaction:
                    continue
                if body.id in chasers:
                    tx, ty = self._ball_at(0.3)
                    self._steer(body, tx, ty)
                else:
                    mark = marks.get(body.id)
                    if mark is not None:
                        # Goal-side of the mark, a little towards the ball: cover + marking.
                        gx, gy = self.L, self.W / 2
                        d = max(1.0, _dist(mark.x, mark.y, gx, gy))
                        tx = mark.x + (gx - mark.x) / d * 1.8 + (b.x - mark.x) * 0.12
                        ty = mark.y + (gy - mark.y) / d * 1.8 + (b.y - mark.y) * 0.12
                        self._steer(body, tx, ty, 0.9)
                    else:
                        self._steer(body, body.ax + (b.x - body.ax) * 0.25, body.ay + (b.y - body.ay) * 0.3, 0.7)

    def _keeper_position(self, gk: Body) -> None:
        b = self.ball
        gx, gy = self.L, self.W / 2
        d = _dist(b.x, b.y, gx, gy)
        off = _clamp(d * 0.12, 0.6, 5.5) * (0.7 + gk.keeping / 100 * 0.3)
        tx = gx - (gx - b.x) / max(d, 1e-6) * off
        ty = gy + (b.y - gy) / max(d, 1e-6) * off
        ty = _clamp(ty, gy - self.goal / 2 - 0.5, gy + self.goal / 2 + 0.5)
        self._steer(gk, tx, ty, 0.7)

    def assignments(self) -> dict[str, Body]:
        """Each outfield defender marks the closest free attacker (greedy, nearest the goal first)."""
        free = [a for a in self.attackers if a.role != "GK"]
        marks: dict[str, Body] = {}
        for defender in sorted((d for d in self.defenders if d.role != "GK"), key=lambda d: -d.x):
            if not free:
                break
            target = min(free, key=lambda a: _dist(a.x, a.y, defender.x, defender.y) - (a.x - self.L * 0.6) * 0.1)
            if _dist(target.x, target.y, defender.x, defender.y) < 18:
                marks[defender.id] = target
                free.remove(target)
        return marks

    # ------------------------------------------------------------ resolve an action
    def execute(self, carrier: Body, action: str, tx: float, ty: float, power: float, passer_last: str | None) -> ActionResult:
        rng, b = self.rng, self.ball
        L, W = self.L, self.W
        pressure = self.pressure_on(carrier)
        frames = [self.frame(0.0)]
        dx, dy = tx - carrier.x, ty - carrier.y
        aim = math.atan2(dy, dx)
        dist_aim = math.hypot(dx, dy)
        shot = action == "SHOT"          # live shot (the keeper reacts) until blocked/deflected
        was_shot = shot                    # for the statistics: a blocked shot is still a shot
        self.shot_live = shot
        xg = self.xg(carrier.x, carrier.y) if shot else 0.0
        if action == "PASS":
            sd = 0.075 * (1.3 - carrier.passing / 100) * (1 + pressure * 0.9) * (0.7 + power * 0.6)
            v0 = PASS_SPEED[0] + PASS_SPEED[1] * power
        elif action == "LOFT":
            sd = 0.06 * (1.3 - carrier.passing / 100) * (1 + pressure * 0.8)
            v0 = LOFT_SPEED[0] + LOFT_SPEED[1] * power
            flight = (LOFT_RANGE[0] + LOFT_RANGE[1] * power) * (L / 105)
            flight *= 1 + rng.gauss(0, 0.09 * (1.2 - carrier.passing / 100))
            b.air_total = b.air_left = flight / v0
        elif action == "SHOT":
            sd = 0.042 * (1.35 - carrier.shooting / 100) * (1 + pressure * 1.0) * (0.75 + max(0.0, power - 0.55) * 1.6)
            v0 = SHOT_SPEED[0] + SHOT_SPEED[1] * power
        else:  # CARRY
            return self._carry(carrier, aim, min(dist_aim, (CARRY_RANGE[0] + CARRY_RANGE[1] * power) * (L / 105)), frames)
        angle = aim + rng.gauss(0, sd)
        b.x, b.y = carrier.x + math.cos(angle) * 0.5, carrier.y + math.sin(angle) * 0.5
        b.vx, b.vy = math.cos(angle) * v0, math.sin(angle) * v0
        intended = None
        if not shot:
            intended = min((a for a in self.attackers if a is not carrier and a.role != "GK"),
                           key=lambda a: _dist(a.x, a.y, tx, ty), default=None)
        marks = self.assignments()
        chasers = {d.id for d in sorted((d for d in self.defenders if d.role != "GK"),
                                        key=lambda d: self._time_to_ball(d))[:2]}
        tried: set[str] = set()
        keeper_reacts = 0.42 - (self.keeper.keeping / 100 * 0.2 if self.keeper else 0) - self.boost * 0.3
        screened = shot and any(_dist(d.x, d.y, *self._project(carrier, angle, 6)) < 1.2 for d in self.defenders if d.role != "GK")
        if screened:
            keeper_reacts += 0.08
        t = 0.0
        last_touch = "A"
        while t < MAX_ACTION_SECONDS:
            t += DT
            self._ball_step(shot)
            self.move_players(t, None, intended, chasers, marks)
            if shot and self.keeper:
                outcome = self._keeper_vs_shot(t, keeper_reacts, frames)
                if outcome:
                    self.shot_live = False
                    return self._shot_result(outcome, frames, t, xg)
            frames.append(self.frame(t))
            # Out of play.
            if b.x >= L or b.x <= 0 or b.y <= 0 or b.y >= W:
                if b.x >= L and abs(b.y - W / 2) <= self.goal / 2 - 0.11 and (shot or b.z < 2.2):
                    return ActionResult("GOAL", frames, detail="Gol", shot=was_shot, on_target=True, xg=xg)
                if b.x >= L and last_touch == "D":
                    return ActionResult("CORNER", frames, detail="Escanteio", shot=was_shot, xg=xg)
                return ActionResult("OUT", frames, detail="Para fora" if was_shot else "Bola fora", shot=was_shot, xg=xg)
            if b.air_left > 0 and b.z > 1.9:
                continue  # in the air: nobody can play it
            speed = math.hypot(b.vx, b.vy)
            # Who reaches the ball first this step.
            contenders = sorted(self.bodies, key=lambda body: _dist(body.x, body.y, b.x, b.y))
            for body in contenders:
                d = _dist(body.x, body.y, b.x, b.y)
                if body is carrier and t < 0.5:
                    continue
                if body.team == "D":
                    reach = KEEPER_CLAIM_RADIUS if body.role == "GK" else TACKLE_RADIUS
                    if d > reach or body.id in tried:
                        continue
                    tried.add(body.id)
                    if body.role == "GK" and not shot:
                        in_box = b.x > L - 16.5 * (L / 105) and abs(b.y - W / 2) < 20 * (W / 68)
                        if in_box and rng.random() < 0.55 + body.keeping / 100 * 0.4:
                            return ActionResult("LOST", frames, detail="O goleiro sai e fica com a bola", lost_to=body.id)
                        continue
                    chance = _clamp(0.16 + body.defending / 100 * 0.42 - speed * 0.015 + self.boost, 0.06, 0.8)
                    if shot:
                        chance *= 0.55  # a shot blocked, not intercepted cleanly
                    if rng.random() < chance:
                        if shot:
                            # Block: deflected away; may still be live.
                            ang = math.atan2(b.vy, b.vx) + math.pi + rng.uniform(-1.0, 1.0)
                            sp = speed * rng.uniform(0.25, 0.45)
                            b.vx, b.vy = math.cos(ang) * sp, math.sin(ang) * sp
                            shot = self.shot_live = False
                            last_touch = "D"
                            frames[-1] = self.frame(t)
                            continue
                        return ActionResult("LOST", frames, detail=f"Interceptação de {body.name}", lost_to=body.id, shot=was_shot, xg=xg)
                    # Deflection: the ball carries on, slower and off line.
                    ang = math.atan2(b.vy, b.vx) + rng.uniform(-0.5, 0.5)
                    sp = speed * 0.7
                    b.vx, b.vy = math.cos(ang) * sp, math.sin(ang) * sp
                    last_touch = "D"
                    break
                if body.role == "GK" or d > CONTROL_RADIUS:
                    continue
                control = _clamp(0.99 - max(0.0, speed - 11) * 0.045 * (1.25 - body.dribbling / 100) - (0.12 if b.air_left > 0 else 0), 0.35, 0.99)
                if rng.random() < control:
                    b.vx = b.vy = 0.0
                    b.air_left = 0.0
                    b.z = 0.0
                    b.x, b.y = body.x + 0.4, body.y
                    frames[-1] = self.frame(t)
                    return ActionResult("CONTROLLED", frames, receiver=body.id, completed_pass=not was_shot and body is not carrier,
                                        detail=f"{body.name} domina", shot=was_shot, xg=xg)
                # Heavy touch: it bounces off, still live.
                ang = rng.uniform(-math.pi, math.pi)
                b.vx, b.vy = math.cos(ang) * speed * 0.35, math.sin(ang) * speed * 0.35
                break
            if speed < 0.25 and b.air_left <= 0:
                # Dead ball nobody controls yet: players race for it (handled by chasers next steps).
                intended = min((a for a in self.attackers if a.role != "GK"), key=lambda a: _dist(a.x, a.y, b.x, b.y))
                chasers = {min((d for d in self.defenders if d.role != "GK"), key=lambda d: _dist(d.x, d.y, b.x, b.y)).id}
        # Settled by proximity (the guard is deterministic and never fires mid-flight).
        nearest = min((body for body in self.bodies if body.role != "GK"), key=lambda body: _dist(body.x, body.y, b.x, b.y))
        if nearest.team == "A":
            b.vx = b.vy = 0.0
            return ActionResult("CONTROLLED", frames, receiver=nearest.id, detail=f"{nearest.name} fica com a sobra", shot=was_shot, xg=xg)
        return ActionResult("LOST", frames, detail="A defesa recupera", lost_to=nearest.id, shot=was_shot, xg=xg)

    def _project(self, carrier: Body, angle: float, d: float) -> tuple[float, float]:
        return carrier.x + math.cos(angle) * d, carrier.y + math.sin(angle) * d

    def _time_to_ball(self, body: Body) -> float:
        best = 99.0
        for step in range(1, 30):
            t = step * 0.1
            bx, by = self._ball_at(t)
            if _dist(body.x, body.y, bx, by) <= body.top_speed * max(0.0, t - 0.25) + TACKLE_RADIUS:
                best = t
                break
        return best

    def _ball_step(self, shot: bool) -> None:
        b = self.ball
        speed = math.hypot(b.vx, b.vy)
        if b.air_left > 0:
            b.air_left = max(0.0, b.air_left - DT)
            p = 1 - b.air_left / b.air_total if b.air_total else 1
            b.z = 4 * 3.2 * p * (1 - p) * min(1.0, b.air_total / 1.6)
            if b.air_left == 0:
                b.z = 0.0
                b.vx *= 0.5
                b.vy *= 0.5
        else:
            decel = SHOT_DECEL if shot else GROUND_DECEL
            if speed > 0:
                factor = max(0.0, speed - decel * DT) / speed
                b.vx *= factor
                b.vy *= factor
        b.x += b.vx * DT
        b.y += b.vy * DT

    def _keeper_vs_shot(self, t: float, reaction: float, frames: list[list[float]]) -> str | None:
        """Physical keeper: reacts after `reaction` s to the real trajectory, moves with
        limited speed, dives with limited reach. No knowledge of anything not yet executed."""
        gk, b = self.keeper, self.ball
        gy = self.W / 2
        if b.vx <= 0:
            return None
        if t >= reaction:
            # Where the ball will cross the keeper's plane (from its current real velocity).
            time_to = max(0.0, (gk.x - b.x) / b.vx)
            cross_y = b.y + b.vy * time_to
            target = _clamp(cross_y, gy - self.goal / 2 - 1.2, gy + self.goal / 2 + 1.2)
            lateral = 1.7 + gk.keeping / 100 * 1.8
            step = _clamp(target - gk.y, -lateral * DT, lateral * DT)
            gk.y += step
            gk.x = min(self.L - 0.4, gk.x + 0.05)
        if b.x >= gk.x - 0.3:
            reach = (0.7 + (0.95 * gk.keeping / 100 if t >= reaction + 0.2 else 0.2)) * (self.L / 105) ** 0.3
            miss = abs(b.y - gk.y)
            on_target = abs(b.y - gy) <= self.goal / 2
            if miss <= reach:
                speed = math.hypot(b.vx, b.vy)
                clean = miss < reach * 0.45
                if clean or self.rng.random() < 0.15 + gk.keeping / 100 * 0.4:
                    hold = speed < 23 and self.rng.random() < 0.25 + gk.keeping / 100 * 0.55
                    if hold:
                        b.vx = b.vy = 0.0
                        b.x, b.y = gk.x - 0.3, gk.y
                        frames.append(self.frame(t))
                        return "SAVED_HELD"
                    # Parry: rebound back into play (or behind for a corner).
                    ang = math.pi + self.rng.uniform(-1.1, 1.1)
                    if self.rng.random() < 0.3:
                        ang = self.rng.choice((-1, 1)) * self.rng.uniform(0.2, 0.9)  # pushed round the post
                    sp = speed * self.rng.uniform(0.25, 0.45)
                    b.vx, b.vy = math.cos(ang) * sp, math.sin(ang) * sp
                    b.x = gk.x - 0.4
                    frames.append(self.frame(t))
                    return "PARRIED" if on_target else "PARRIED_WIDE"
        return None

    def _shot_result(self, outcome: str, frames: list[list[float]], t: float, xg: float) -> ActionResult:
        gk = self.keeper.id if self.keeper else None
        if outcome == "SAVED_HELD":
            return ActionResult("SAVED_HELD", frames, detail="Defesa do goleiro", shot=True, on_target=True, xg=xg, keeper=gk)
        # A parry: keep the ball live a few more seconds - a rebound may stay with the attack.
        rebound = self._loose_ball(t, frames)
        rebound.shot, rebound.on_target, rebound.xg, rebound.keeper = True, outcome == "PARRIED", xg, gk
        rebound.detail = "Defesa! " + rebound.detail
        if rebound.outcome == "OUT" and self.ball.x >= self.L:
            rebound.outcome, rebound.detail = "CORNER", "Defesa! Escanteio"
        return rebound

    def _loose_ball(self, t0: float, frames: list[list[float]]) -> ActionResult:
        b = self.ball
        chasers = {d.id for d in sorted((d for d in self.defenders if d.role != "GK"), key=lambda d: _dist(d.x, d.y, b.x, b.y))[:2]}
        attacker = min((a for a in self.attackers if a.role != "GK"), key=lambda a: _dist(a.x, a.y, b.x, b.y))
        t = t0
        while t < t0 + 3.5:
            t += DT
            self._ball_step(False)
            self.move_players(t, None, attacker, chasers, {})
            frames.append(self.frame(t))
            if b.x >= self.L or b.x <= 0 or b.y <= 0 or b.y >= self.W:
                return ActionResult("OUT", frames, detail="bola para fora")
            for body in sorted(self.bodies, key=lambda body: _dist(body.x, body.y, b.x, b.y)):
                if body.role == "GK" and body.team == "D" and _dist(body.x, body.y, b.x, b.y) < 1.0 and t > t0 + 0.6:
                    return ActionResult("LOST", frames, detail="o goleiro fica com a sobra", lost_to=body.id)
                if body.role == "GK":
                    continue
                if _dist(body.x, body.y, b.x, b.y) < CONTROL_RADIUS:
                    if body.team == "A":
                        b.vx = b.vy = 0.0
                        return ActionResult("CONTROLLED", frames, receiver=body.id, detail=f"rebote com {body.name}!")
                    return ActionResult("LOST", frames, detail=f"{body.name} afasta o rebote", lost_to=body.id)
                break
        nearest = min((body for body in self.bodies if body.role != "GK"), key=lambda body: _dist(body.x, body.y, b.x, b.y))
        if nearest.team == "A":
            return ActionResult("CONTROLLED", frames, receiver=nearest.id, detail=f"rebote com {nearest.name}!")
        return ActionResult("LOST", frames, detail="a defesa afasta", lost_to=nearest.id)

    def _carry(self, carrier: Body, angle: float, distance: float, frames: list[list[float]]) -> ActionResult:
        """Conduction: the carrier runs with the ball; defenders close in and may tackle (once each)."""
        rng, b = self.rng, self.ball
        tx, ty = carrier.x + math.cos(angle) * distance, carrier.y + math.sin(angle) * distance
        marks = self.assignments()
        chasers = {d.id for d in sorted((d for d in self.defenders if d.role != "GK"), key=lambda d: _dist(d.x, d.y, carrier.x, carrier.y))[:2]}
        tried: set[str] = set()
        t = 0.0
        while t < MAX_ACTION_SECONDS:
            t += DT
            self._steer(carrier, tx, ty, 0.86 - (1 - carrier.dribbling / 100) * 0.1)
            b.x, b.y = carrier.x + math.cos(angle) * 0.5, carrier.y + math.sin(angle) * 0.5
            self.move_players(t, carrier, None, chasers, marks)
            frames.append(self.frame(t))
            if b.x >= self.L or b.y <= 0 or b.y >= self.W:
                return ActionResult("OUT", frames, detail="Conduziu para fora")
            for defender in self.defenders:
                if defender.id in tried or _dist(defender.x, defender.y, carrier.x, carrier.y) > TACKLE_RADIUS + 0.2:
                    continue
                tried.add(defender.id)
                if defender.role == "GK" and rng.random() > 0.35 + defender.keeping / 100 * 0.4:
                    continue
                chance = _clamp(0.32 + (defender.defending - carrier.dribbling) / 160 + (defender.physical - carrier.physical) / 400 + self.boost, 0.1, 0.8)
                if rng.random() < chance:
                    return ActionResult("LOST", frames, detail=f"Desarme de {defender.name}", lost_to=defender.id)
            if _dist(carrier.x, carrier.y, tx, ty) < 0.6:
                break
        carrier.vx *= 0.3
        carrier.vy *= 0.3
        return ActionResult("CONTROLLED", frames, receiver=carrier.id, detail=f"{carrier.name} avança")


# ---------------------------------------------------------------- AI choice (bots, timeouts, disconnections)
def ai_action(bodies: list[Body], ball: Ball, carrier_id: str, mode: str, actions_done: int, kind: str, rng: random.Random) -> dict[str, object]:
    """A sensible contextual action for the carrier: shoot when it is a chance, otherwise the
    most progressive safe pass (or a cross / carry). Same physics as a human gesture."""
    cfg = PITCH[mode]
    L, W, goal = cfg["length"], cfg["width"], cfg["goal"]
    s = L / 105
    carrier = next(b for b in bodies if b.id == carrier_id)
    defenders = [b for b in bodies if b.team == "D"]
    keeper = next((b for b in defenders if b.role == "GK"), None)
    d_goal = _dist(carrier.x, carrier.y, L, W / 2)
    angle_ok = abs(carrier.y - W / 2) < (L - carrier.x) * 1.4 + 4 * s
    must_shoot = actions_done >= MAX_ACTIONS - 1 or kind == "PENALTY"
    if kind == "PENALTY" or (d_goal < 21 * s and angle_ok) or (must_shoot and d_goal < 35 * s):
        side = 1 if (keeper is None or keeper.y <= W / 2) else -1
        if rng.random() < 0.3:
            side = -side
        ty = W / 2 + side * (goal / 2 - 0.8 * s ** 0.5)
        return {"type": "SHOT", "x": L, "y": ty, "power": round(_clamp(0.62 + rng.uniform(0, 0.25), 0, 1), 3)}

    def lane_risk(a: Body) -> float:
        risk = 0.0
        for d in defenders:
            if d.role == "GK":
                continue
            px, py = a.x - carrier.x, a.y - carrier.y
            length = math.hypot(px, py) or 1
            u = _clamp(((d.x - carrier.x) * px + (d.y - carrier.y) * py) / length ** 2, 0, 1)
            gap = _dist(d.x, d.y, carrier.x + px * u, carrier.y + py * u)
            risk += max(0.0, 2.6 - gap) * (1.2 if u > 0.15 else 0.3)
        return risk

    options = []
    for a in bodies:
        if a.team != "A" or a is carrier or a.role == "GK":
            continue
        d = _dist(a.x, a.y, carrier.x, carrier.y)
        if d < 4 * s or d > 45 * s:
            continue
        free = min((_dist(a.x, a.y, x.x, x.y) for x in defenders), default=9)
        gain = (a.x - carrier.x) / s
        value = gain * 0.12 + min(free, 6) * 0.35 - lane_risk(a) * 0.9 + rng.uniform(0, 0.6)
        if a.x > L - 16.5 * s and abs(a.y - W / 2) < 12 * s:
            value += 1.0
        options.append((value, a, d))
    space_ahead = min((_dist(carrier.x + 6 * s, carrier.y, x.x, x.y) for x in defenders if x.role != "GK"), default=20)
    if (not options or max(o[0] for o in options) < 0.4) and space_ahead > 5 * s:
        return {"type": "CARRY", "x": carrier.x + 9 * s, "y": carrier.y + (W / 2 - carrier.y) * 0.25, "power": 0.8}
    if not options:
        return {"type": "SHOT", "x": L, "y": W / 2, "power": 0.8}
    _, target, d = max(options, key=lambda o: o[0])
    wide_delivery = (carrier.x > L - 22 * s and min(carrier.y, W - carrier.y) < 14 * s) or kind == "CORNER"
    if wide_delivery or lane_risk(target) > 1.5 and d > 14 * s:
        flight = d + 0.5
        power = _clamp((flight / s - LOFT_RANGE[0]) / LOFT_RANGE[1], 0.0, 1.0)
        return {"type": "LOFT", "x": target.x + 1.0 * s, "y": target.y, "power": round(power, 3)}
    lead = 1.5 * s
    travel = d + lead + 2.0
    v0 = math.sqrt(2 * GROUND_DECEL * travel)
    power = _clamp((v0 - PASS_SPEED[0]) / PASS_SPEED[1], 0.05, 1.0)
    return {"type": "PASS", "x": target.x + lead, "y": target.y, "power": round(power, 3)}


# ---------------------------------------------------------------- the match (state machine)
@dataclass
class HighlightMatch:
    """States: CLOCK (fast simulation) -> DECISION (paused, timer) -> EXECUTING (ball in play)
    -> DECISION | OUTCOME -> CLOCK ... HALF_TIME ... FINISHED. Bot attacks go straight to
    REPLAY (played by the AI with the same physics) then OUTCOME."""
    match_id: str
    mode: str
    clubs: list[str]
    humans: list[str]                 # clubs whose attacks a human plays
    seed: int
    ruleset: str
    decision_seconds: int
    free_vs_bots: bool
    inputs: list[dict[str, object]]   # team_input_view of home/away
    timeline: list[dict[str, object]] = field(default_factory=list)
    state: str = "CLOCK"
    revision: int = 0
    minute: float = 0.0
    clock_since: float = 0.0          # real time when the clock last resumed from `minute`
    cursor: int = 0                   # next timeline index
    score: list[int] = field(default_factory=lambda: [0, 0])
    events: list[dict[str, object]] = field(default_factory=list)
    stats: dict[str, dict[str, float]] = field(default_factory=dict)
    players: dict[str, dict[str, float]] = field(default_factory=dict)
    opportunity: dict[str, object] | None = None
    deadline: float | None = None
    state_until: float | None = None  # end of EXECUTING / REPLAY / OUTCOME / HALF_TIME
    half_time_done: bool = False
    late_checked: bool = False
    last_seen: dict[str, float] = field(default_factory=dict)
    ai_control: list[str] = field(default_factory=list)   # clubs whose coach was away past the grace
    paused_left: float | None = None  # decision time left while waiting for a reconnection
    grace_until: float | None = None
    applied: dict[str, int] = field(default_factory=dict)  # action_id -> revision (idempotency)
    action_log: list[dict[str, object]] = field(default_factory=list)
    finished_at: float | None = None

    # ------------------------------------------------------------ construction
    @classmethod
    def create(cls, match_id: str, mode: str, home: TeamInput, away: TeamInput, home_view: dict, away_view: dict,
               humans: list[str], seed: int, ruleset: str, decision_seconds: int, free_vs_bots: bool, now: float) -> HighlightMatch:
        match = cls(match_id, mode, [home.club_code, away.club_code], sorted(humans), seed, ruleset,
                    decision_seconds if decision_seconds in DECISION_CHOICES else 10, free_vs_bots, [home_view, away_view])
        match.timeline = build_timeline(home, away, seed, ruleset)
        match.clock_since = now
        for club in match.clubs:
            match.stats[club] = dict.fromkeys(("shots", "shots_on_target", "passes", "passes_completed", "saves", "corners",
                                               "tackles", "interceptions", "fouls", "chances", "possession_actions"), 0)
            match.stats[club]["xg"] = 0.0
        for team in (home, away):
            for p in (*team.starters, *team.bench):
                match.players[p.id] = dict.fromkeys(("goals", "assists", "shots", "shots_on_target", "passes", "passes_completed",
                                                     "key_passes", "saves", "tackles", "interceptions", "dribbles", "losses"), 0)
        match.revision = 1
        return match

    def teams(self) -> tuple[TeamInput, TeamInput]:
        from app.services.season_service import team_input_from_view  # local: avoid an import cycle
        return team_input_from_view(self.inputs[0]), team_input_from_view(self.inputs[1])

    # ------------------------------------------------------------ helpers
    @property
    def finished(self) -> bool:
        return self.state == "FINISHED"

    def side_of(self, club: str) -> int:
        return self.clubs.index(club)

    def _human_controls(self, club: str) -> bool:
        return club in self.humans and club not in self.ai_control

    def connected(self, club: str, at: float) -> bool:
        seen = self.last_seen.get(club)
        return seen is not None and at - seen <= CONNECTED_WINDOW

    def seen(self, club: str, now: float) -> None:
        """A coach polled: counts as connected; a coach replaced by the AI takes control
        back at the next decision (never in the middle of one)."""
        if club not in self.humans:
            return
        self.last_seen[club] = now
        if club in self.ai_control:
            self.ai_control.remove(club)
            self.revision += 1

    def _event(self, kind: str, club: str | None, minute: float, player: Body | None = None, outcome: str = "",
               other: Body | None = None, xg: float = 0.0, x: float = 0.5, y: float = 0.5, reveal: float = 0.0, extra: dict | None = None) -> None:
        side = self.side_of(club) if club else None
        # Engine-compatible coordinates: home attacks towards x = 1, away towards x = 0.
        ex = x if side in (0, None) else 1 - x
        event = {"event_id": f"{self.match_id}:H{len(self.events) + 1:04d}", "match_id": self.match_id, "kind": kind,
                 "team": club, "tick": int(minute * 60), "minute": max(1, min(90, math.ceil(minute))), "x": round(ex, 4), "y": round(y, 4),
                 "outcome": outcome, "player_id": player.id if player else None, "player_name": player.name if player else None,
                 "secondary_player_id": other.id if other else None, "secondary_player_name": other.name if other else None,
                 "xg": round(xg, 4), "score": {"home": self.score[0], "away": self.score[1]}, "revealed_at": reveal, "animation_ms": 0,
                 "participant_ids": []}
        if extra:
            event.update(extra)
        self.events.append(event)

    def clock_minute(self, now: float) -> float:
        if self.state == "CLOCK":
            return min(90.0, self.minute + max(0.0, now - self.clock_since) * CLOCK_MINUTES_PER_SECOND)
        return self.minute

    # ------------------------------------------------------------ the state machine (logical time)
    def advance(self, now: float) -> bool:
        """Apply every transition due by `now`, each at its own scheduled time. Returns True if
        anything changed. Idempotent: calling it twice with the same `now` changes nothing."""
        changed = False
        for _ in range(200):
            step = self._next_transition(now)
            if step is None:
                break
            changed = True
        return changed

    def _next_transition(self, now: float) -> str | None:
        if self.state == "FINISHED":
            return None
        if self.state == "CLOCK":
            target = self._next_stop()
            at = self.clock_since + (target - self.minute) / CLOCK_MINUTES_PER_SECOND
            if at > now:
                return None
            self.minute = target
            if target >= 90.0 and (self.cursor >= len(self.timeline)):
                self.state, self.finished_at = "FINISHED", at
                self.revision += 1
                return "FINISHED"
            if target >= 45.0 and not self.half_time_done and (self.cursor >= len(self.timeline) or float(self.timeline[self.cursor]["minute"]) >= 45):
                self.half_time_done = True
                self.state, self.state_until = "HALF_TIME", at + HALF_TIME_SECONDS
                self.revision += 1
                return "HALF_TIME"
            if target >= 80 and not self.late_checked:
                self.late_checked = True
                self._late_opportunity()
                self.clock_since = at
                return "LATE_CHECK"
            self._open(at)
            return "OPEN"
        if self.state in ("HALF_TIME", "OUTCOME"):
            if self.state_until is None or self.state_until > now:
                return None
            at = self.state_until
            self.state, self.state_until, self.opportunity, self.clock_since = "CLOCK", None, None, at
            self.revision += 1
            return "RESUME"
        if self.state in ("EXECUTING", "REPLAY"):
            if self.state_until is None or self.state_until > now:
                return None
            at = self.state_until
            opp = self.opportunity
            if opp and opp["status"] == "LIVE" and self.state == "EXECUTING":
                self._to_decision(at)
            else:
                self.state, self.state_until = "OUTCOME", at + OUTCOME_PAUSE_SECONDS
                self.revision += 1
            return "PLAYED"
        if self.state == "DECISION":
            club = str(self.opportunity["attacking"])
            # Disconnected coach: freeze the decision (safe point) and wait for the grace period.
            if self.grace_until is None and not self.connected(club, now):
                seen = self.last_seen.get(club, 0.0)
                lost_at = max(seen + CONNECTED_WINDOW, float(self.opportunity.get("decision_opened_at", now)))
                if lost_at <= now and (self.deadline is None or lost_at < self.deadline):
                    self.paused_left = None if self.deadline is None else max(0.0, self.deadline - lost_at)
                    self.grace_until, self.deadline = lost_at + RECONNECT_GRACE, None
                    self.revision += 1
                    return "PAUSED"
            if self.grace_until is not None:
                if self.connected(club, now) and (self.last_seen.get(club, 0) < self.grace_until):
                    resumed = self.last_seen[club]
                    self.deadline = None if self.paused_left is None else resumed + max(3.0, self.paused_left)
                    self.grace_until = self.paused_left = None
                    self.revision += 1
                    return "RESUMED"
                if self.grace_until <= now:
                    at = self.grace_until
                    self.grace_until = self.paused_left = None
                    if club not in self.ai_control:
                        self.ai_control.append(club)
                    self._auto(at, "AI_TAKEOVER")
                    return "TAKEOVER"
                return None
            if self.deadline is not None and self.deadline <= now:
                self._auto(self.deadline, "TIMEOUT")
                return "TIMEOUT"
            return None
        return None

    def _next_stop(self) -> float:
        nxt = float(self.timeline[self.cursor]["minute"]) if self.cursor < len(self.timeline) else 90.0
        if not self.half_time_done and nxt >= 45:
            return 45.0
        if not self.late_checked and nxt >= 80:
            return 80.0
        return nxt

    def _late_opportunity(self) -> None:
        """Minutes-final pressure: a losing side may get one more attack (by its quality, not for free)."""
        if self.score[0] == self.score[1]:
            return
        losing = 0 if self.score[0] < self.score[1] else 1
        rng = random.Random(f"{self.seed}:late")
        home, away = self.teams()
        att = team_strength((home, away)[losing])[0]
        dfn = team_strength((home, away)[1 - losing])[1]
        if rng.random() < _clamp(0.45 + (att - dfn) / 100, 0.2, 0.7):
            minute = round(rng.uniform(85, 89.5), 1)
            self.timeline.append({"side": losing, "kind": rng.choice(["BUILDUP", "CROSS", "WING"]), "minute": minute, "index": len(self.timeline), "late": True})
            rest = sorted(self.timeline[self.cursor:], key=lambda r: (r["minute"], r["side"]))
            self.timeline[self.cursor:] = rest
            for index, row in enumerate(self.timeline):
                row["index"] = index

    def _open(self, at: float) -> None:
        row = self.timeline[self.cursor]
        self.cursor += 1
        side = int(row["side"])
        home, away = self.teams()
        attack, defence = (home, away) if side == 0 else (away, home)
        rng = random.Random(f"{self.seed}:open:{row['index']}")
        kind = str(row["kind"])
        bodies, ball, carrier = build_scenario(kind, attack, defence, self.mode, rng)
        club = self.clubs[side]
        self.stats[club]["chances"] += 1
        self.opportunity = {"id": f"{self.match_id}:O{int(row['index']) + 1:02d}", "index": int(row["index"]), "kind": kind,
                            "attacking": club, "defending": self.clubs[1 - side], "minute": self.minute, "status": "LIVE",
                            "bodies": [asdict(b) for b in bodies], "ball": asdict(ball), "carrier": carrier,
                            "actions": 0, "last": None, "opened_at": at, "assist_candidate": None, "result": None}
        self._event("CHANCE", club, self.minute, outcome=kind, reveal=at, extra={"label": KIND_LABEL.get(kind, kind)})
        self.revision += 1
        if self._human_controls(club):
            self._to_decision(at)
        else:
            self._replay(at)

    def _decision_seconds_for(self, club: str) -> float | None:
        rival = self.clubs[1 - self.side_of(club)]
        if self.free_vs_bots and rival not in self.humans:
            return None
        return float(self.decision_seconds)

    def _to_decision(self, at: float) -> None:
        club = str(self.opportunity["attacking"])
        if not self._human_controls(club):
            # The coach is under AI control (left past the grace period): the AI plays on.
            self._auto(at, "AI_CONTROL")
            return
        seconds = self._decision_seconds_for(club)
        self.state = "DECISION"
        self.deadline = None if seconds is None else at + seconds
        self.opportunity["decision_opened_at"] = at
        self.state_until = None
        self.revision += 1

    def _replay(self, at: float) -> None:
        """Bot attack: every action chosen by the AI and resolved by the same physics, all at
        once. The replay frames *are* the official event."""
        opp = self.opportunity
        sequence: list[dict[str, object]] = []
        while opp["status"] == "LIVE":
            bodies, ball = self._restore_bodies(opp)
            rng = random.Random(f"{self.seed}:ai:{opp['index']}:{opp['actions']}")
            choice = ai_action(bodies, ball, str(opp["carrier"]), self.mode, int(opp["actions"]), str(opp["kind"]), rng)
            sequence.append(self._resolve(choice, "AI", at))
        total = sum(float(step["duration"]) for step in sequence)
        self.state, self.state_until = "REPLAY", at + total + 0.6 * len(sequence)
        opp["replay"] = sequence
        self.revision += 1

    def _auto(self, at: float, reason: str) -> None:
        opp = self.opportunity
        bodies, ball = self._restore_bodies(opp)
        rng = random.Random(f"{self.seed}:ai:{opp['index']}:{opp['actions']}")
        choice = ai_action(bodies, ball, str(opp["carrier"]), self.mode, int(opp["actions"]), str(opp["kind"]), rng)
        self.deadline = None
        self._execute(choice, reason, at)

    # ------------------------------------------------------------ actions
    def submit(self, club: str, payload: dict[str, object], now: float) -> dict[str, object]:
        """A coach's gesture. Validated against identity, state, opportunity, revision, time
        and physical limits. Exactly one of {this action, the timer's automatic action} wins:
        both run under the room lock and `advance(now)` is applied first."""
        action_id = str(payload.get("action_id") or "")
        if not 8 <= len(action_id) <= 80:
            raise ValueError("Ação sem identificador válido.")
        if action_id in self.applied:
            return {"status": "DUPLICATE", "revision": self.applied[action_id]}
        self.seen(club, now)
        self.advance(now)
        opp = self.opportunity
        if self.state != "DECISION" or opp is None:
            raise ValueError("Não há decisão aberta agora (a jogada já foi executada ou encerrada).")
        if opp["attacking"] != club or not self._human_controls(club):
            raise ValueError("Esta oportunidade não é sua.")
        if str(payload.get("opportunity_id")) != opp["id"]:
            raise ValueError("Ação de uma oportunidade anterior.")
        if int(payload.get("revision", -1)) != self.revision:
            raise ValueError("Estado desatualizado: a jogada mudou. Tente de novo.")
        kind = str(payload.get("type"))
        if kind not in ACTION_TYPES:
            raise ValueError("Tipo de ação inválido.")
        if opp["kind"] == "PENALTY" and kind != "SHOT":
            raise ValueError("No pênalti só é possível chutar.")
        try:
            x, y, power = float(payload.get("x")), float(payload.get("y")), float(payload.get("power"))
        except (TypeError, ValueError) as error:
            raise ValueError("Direção ou potência inválida.") from error
        if not all(map(math.isfinite, (x, y, power))) or not (-0.1 <= x <= 1.1 and -0.1 <= y <= 1.1) or not 0.0 <= power <= 1.0:
            raise ValueError("Direção ou potência fora dos limites.")
        cfg = PITCH[self.mode]
        bodies, _ = self._restore_bodies(opp)
        carrier = next(b for b in bodies if b.id == opp["carrier"])
        tx, ty = x * cfg["length"], y * cfg["width"]
        if math.hypot(tx - carrier.x, ty - carrier.y) < 0.8:
            raise ValueError("Arraste mais longe para indicar a direção.")
        self._execute({"type": kind, "x": tx, "y": ty, "power": power}, "HUMAN", now)
        self.applied[action_id] = self.revision
        return {"status": "ACCEPTED", "revision": self.revision}

    def _execute(self, choice: dict[str, object], by: str, at: float) -> None:
        step = self._resolve(choice, by, at)
        self.opportunity["last"] = step
        self.state, self.state_until = "EXECUTING", at + float(step["duration"]) + 0.35
        self.revision += 1

    def _restore_bodies(self, opp: dict[str, object]) -> tuple[list[Body], Ball]:
        return [Body(**b) for b in opp["bodies"]], Ball(**opp["ball"])

    def _resolve(self, choice: dict[str, object], by: str, at: float) -> dict[str, object]:
        """Run the physics of one action and apply its official consequences (stats, events, score)."""
        opp = self.opportunity
        bodies, ball = self._restore_bodies(opp)
        carrier = next(b for b in bodies if b.id == opp["carrier"])
        rng = random.Random(f"{self.seed}:act:{opp['index']}:{opp['actions']}")
        boost = min(0.12, 0.02 * int(opp["actions"]))  # the defence tightens as the move drags on
        pitch = Pitch(bodies, ball, self.mode, rng, boost)
        kind = str(choice["type"])
        result = pitch.execute(carrier, kind, float(choice["x"]), float(choice["y"]), float(choice["power"]), None)
        club, rival = str(opp["attacking"]), str(opp["defending"])
        stats, minute = self.stats[club], float(opp["minute"])
        reveal = at + len(result.frames) * DT
        by_id = {b.id: b for b in bodies}
        opp["actions"] = int(opp["actions"]) + 1
        stats["possession_actions"] += 1
        cx, cy = carrier.x / pitch.L, carrier.y / pitch.W
        if kind in ("PASS", "LOFT"):
            stats["passes"] += 1
            self.players[carrier.id]["passes"] += 1
            if result.completed_pass:
                stats["passes_completed"] += 1
                self.players[carrier.id]["passes_completed"] += 1
                opp["assist_candidate"] = carrier.id
        elif kind == "CARRY" and result.outcome == "CONTROLLED":
            self.players[carrier.id]["dribbles"] += 1
        if result.shot:
            stats["shots"] += 1
            stats["xg"] = round(stats["xg"] + result.xg, 3)
            self.players[carrier.id]["shots"] += 1
            if result.on_target:
                stats["shots_on_target"] += 1
                self.players[carrier.id]["shots_on_target"] += 1
            assister = by_id.get(str(opp.get("assist_candidate"))) if opp.get("assist_candidate") else None
            if assister and result.outcome != "GOAL":
                self.players[assister.id]["key_passes"] += 1
            if result.outcome == "GOAL":
                self.score[self.side_of(club)] += 1
                self.players[carrier.id]["goals"] += 1
                if assister and assister.id != carrier.id:
                    self.players[assister.id]["assists"] += 1
            outcome = "GOAL" if result.outcome == "GOAL" else "ON_TARGET" if result.on_target else "OFF_TARGET"
            self._event("SHOT", club, minute, carrier, outcome, xg=result.xg, x=cx, y=cy, reveal=reveal)
            if result.outcome == "GOAL":
                self._event("GOAL", club, minute, carrier, "GOAL", other=assister if assister and assister.id != carrier.id else None,
                            xg=result.xg, x=1.0, y=0.5, reveal=reveal)
            elif result.on_target and result.keeper:
                self.stats[rival]["saves"] += 1
                self.players[result.keeper]["saves"] += 1
                self._event("SAVE", rival, minute, by_id.get(result.keeper), "SAVE", x=0.0, y=0.5, reveal=reveal)
        if result.outcome == "LOST" and result.lost_to:
            loser = carrier
            self.players[loser.id]["losses"] += 1
            taker = by_id.get(result.lost_to)
            if taker and taker.role != "GK":
                key = "tackles" if kind == "CARRY" else "interceptions"
                self.stats[rival][key] += 1
                self.players[taker.id][key] += 1
                self._event("TACKLE" if kind == "CARRY" else "INTERCEPTION", rival, minute, taker, "WON", x=1 - cx, y=cy, reveal=reveal)
        if result.outcome == "CORNER":
            stats["corners"] += 1
            self._event("CORNER", club, minute, None, "", x=1.0, y=0.0, reveal=reveal)
        step = {"by": by, "type": kind, "aim": {"x": round(float(choice["x"]) / pitch.L, 4), "y": round(float(choice["y"]) / pitch.W, 4)},
                "power": round(float(choice["power"]), 3), "carrier": carrier.id, "outcome": result.outcome, "detail": result.detail,
                "frames": result.frames, "duration": round(len(result.frames) * DT, 2), "starts_at": at, "receiver": result.receiver}
        self.action_log.append({"opportunity": opp["id"], "action": int(opp["actions"]), "by": by, "type": kind,
                                "x": round(float(choice["x"]), 3), "y": round(float(choice["y"]), 3), "power": step["power"], "at": round(at, 3),
                                "outcome": result.outcome})
        # Where everybody ended: the next decision starts from here (no teleport).
        opp["bodies"] = [asdict(b) for b in bodies]
        opp["ball"] = asdict(Ball(ball.x, ball.y))
        if result.outcome == "CONTROLLED" and result.receiver:
            if int(opp["actions"]) >= MAX_ACTIONS:
                opp["status"], opp["result"] = "STALLED", "A defesa se reorganiza e o ataque termina"
            else:
                opp["carrier"] = result.receiver
                if opp["kind"] in ("FREE_KICK", "PENALTY", "CORNER"):
                    opp["kind"] = "BUILDUP"  # the set piece is over; play continues
        elif result.outcome == "CORNER":
            # The attack continues from the corner flag with the best crosser.
            corner = random.Random(f"{self.seed}:corner:{opp['index']}:{opp['actions']}")
            home, away = self.teams()
            side = self.side_of(club)
            attack, defence = (home, away) if side == 0 else (away, home)
            bodies2, ball2, carrier2 = build_scenario("CORNER", attack, defence, self.mode, corner)
            opp.update(bodies=[asdict(b) for b in bodies2], ball=asdict(ball2), carrier=carrier2, kind="CORNER")
            if int(opp["actions"]) >= MAX_ACTIONS:
                opp["status"], opp["result"] = "STALLED", "Escanteio afastado"
        else:
            opp["status"] = result.outcome
            opp["result"] = {"GOAL": "GOL!", "SAVED_HELD": "Defesa do goleiro", "LOST": result.detail, "OUT": result.detail}.get(result.outcome, result.detail)
        return step

    # ------------------------------------------------------------ views
    def view(self, club: str | None, now: float) -> dict[str, object]:
        """What a client sees. Nothing beyond what has been executed is revealed; the score
        follows the events already shown (a goal appears when its ball crosses the line)."""
        shown = [e for e in self.events if float(e.get("revealed_at", 0)) <= now]
        score = [sum(1 for e in shown if e["kind"] == "GOAL" and e["team"] == c) for c in self.clubs]
        opp = self.opportunity
        opp_view = None
        if opp is not None:
            last = opp.get("last")
            opp_view = {"id": opp["id"], "kind": opp["kind"], "label": KIND_LABEL.get(str(opp["kind"]), opp["kind"]),
                        "attacking": opp["attacking"], "defending": opp["defending"], "minute": opp["minute"],
                        "status": opp["status"], "result": opp.get("result"), "actions": opp["actions"], "max_actions": MAX_ACTIONS,
                        "carrier": opp["carrier"],
                        "roster": [{"id": b["id"], "name": b["name"], "number": b["number"], "team": b["team"], "role": b["role"]} for b in opp["bodies"]],
                        "positions": [[round(b["x"] / PITCH[self.mode]["length"], 4), round(b["y"] / PITCH[self.mode]["width"], 4)] for b in opp["bodies"]],
                        "ball": [round(opp["ball"]["x"] / PITCH[self.mode]["length"], 4), round(opp["ball"]["y"] / PITCH[self.mode]["width"], 4)],
                        "last": last if self.state == "EXECUTING" or (self.state in ("DECISION", "OUTCOME") and last) else None,
                        "replay": opp.get("replay") if self.state in ("REPLAY", "OUTCOME") else None,
                        "opened_at": opp.get("opened_at")}
        controller = None
        if opp is not None:
            attacking = str(opp["attacking"])
            controller = "HUMAN" if self._human_controls(attacking) else "AI"
        cfg = PITCH[self.mode]
        return {"match_id": self.match_id, "home": self.clubs[0], "away": self.clubs[1], "state": self.state, "revision": self.revision,
                "minute": round(self.clock_minute(now), 2), "clock_rate": CLOCK_MINUTES_PER_SECOND if self.state == "CLOCK" else 0,
                "score": {"home": score[0], "away": score[1]}, "server_now": now, "deadline": self.deadline,
                "decision_seconds": self.decision_seconds, "state_until": self.state_until, "grace_until": self.grace_until,
                "you": club if club in self.clubs else None, "your_turn": bool(opp and self.state == "DECISION" and club == opp["attacking"] and self._human_controls(str(club))),
                "controller": controller, "ai_control": list(self.ai_control), "humans": self.humans,
                "connected": {c: self.connected(c, now) for c in self.humans},
                "opportunity": opp_view, "ruleset": self.ruleset,
                "pitch": {"length": cfg["length"], "width": cfg["width"], "goal": cfg["goal"], "box": cfg["box"]},
                "physics": {"pass": PASS_SPEED, "loft": LOFT_SPEED, "loft_range": LOFT_RANGE, "shot": SHOT_SPEED, "carry": CARRY_RANGE, "decel": GROUND_DECEL},
                "events": [{k: v for k, v in e.items() if k != "revealed_at"} for e in shown[-30:]],
                "stats": self.stats}

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> HighlightMatch:
        return cls(**raw)
