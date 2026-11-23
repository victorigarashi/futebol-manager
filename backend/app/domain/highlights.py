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
import zlib
from dataclasses import asdict, dataclass, field

from app.domain import football
from app.domain.cohesion import slot_role
from app.domain.kits import select_kits
from app.domain.match_engine import PlayerInput, TeamInput, derived_attributes

# ---------------------------------------------------------------- tunables (documented)
# Every gameplay number lives here (docs/MODO_JOGAVEL.md §5 explains each one). These
# are *physics/rules*; the look of the screen has its own config in the frontend
# (features/career/interactive/render/config.ts) and can never change a result.
DT = 0.1                      # physics step (s); frames are recorded every step (10 Hz). Results never depend on the client's FPS.
MAX_ACTION_SECONDS = 7.0      # an action that has not resolved by then is settled by proximity
MAX_ACTIONS = 8               # anti-infinite-attack guard: after 8 actions the next control ends it
# Ball
GROUND_DECEL = 5.0            # m/s² rolling friction for passes and carries
SHOT_DECEL = 1.5
BALL_RADIUS = 0.11
PASS_SPEED = (7.0, 19.0)      # v0 = a + b * power
LOFT_SPEED = (11.0, 15.0)
SHOT_SPEED = (16.0, 18.0)
LOFT_RANGE = (12.0, 46.0)     # flight distance = a + b * power
# Execution error: standard deviation of the angle (rad) = base * (skill_offset - skill/100) * (1 + pressure factor) ...
PASS_ERROR = 0.075
LOFT_ERROR = 0.06
SHOT_ERROR = 0.06
HEADER_Z = (0.9, 2.6)         # a lofted ball between these heights can be headed
HEADER_SPEED = (10.0, 7.0)    # v0 = a + b * physical/100
# Pitch of the interactive mode, in metres (x along the length, y across, z up). Both
# renderers draw exactly these numbers; the collisions use exactly the drawn mouth, posts
# and crossbar. 5x5 is a game-design size (more room than futsal), 11x11 is regulation.
HL_PITCH = {
    "ELEVEN_A_SIDE": {"length": 105.0, "width": 68.0, "goal": 7.32, "goal_height": 2.44, "box": 16.5},
    "FIVE_A_SIDE": {"length": 50.0, "width": 32.0, "goal": 4.0, "goal_height": 2.0, "box": 8.0},
}
POST_RADIUS = 0.06            # posts and crossbar (12 cm thick)
GRAVITY = 9.81
SHOT_LIFT = (0.5, 9.0)        # vertical speed of a shot (m/s) = a + b * max(0, power - 0.35) (+ error)
# Players
PLAYER_BASE_SPEED = 5.6       # top speed = base + pace/100 * PLAYER_PACE_SPEED (m/s)
PLAYER_PACE_SPEED = 3.4
PLAYER_ACCEL = (6.0, 3.5)     # m/s² = a + b * pace/100 (fast players also get going sooner)
CARRY_SPEED = (0.93, 0.12)    # fraction of top speed while carrying = a + b * dribbling/100
CARRY_ACCEL = 11.0            # m/s² with the ball (short bursts, sharp direction changes)
CARRY_TOUCH = (0.95, 0.55)    # ball ahead of the foot = a - b * dribbling/100 (m): poor dribblers push it further
CARRY_RANGE = (6.0, 18.0)     # requested carry distance = a + b * power (m): one gesture crosses real ground
# Duels and control
CONTROL_RADIUS = 0.9
TACKLE_RADIUS = 0.95
KEEPER_CLAIM_RADIUS = 1.5
INTERCEPT = (0.16, 0.42, 0.015)   # chance = a + b*defending/100 - c*ball speed
TACKLE = (0.30, 160.0, 400.0)     # chance = a + (def - dribbling)/b + (phys - phys)/c
PRESSURE_RADIUS = 4.5             # pressure = 1 - nearest marker distance / radius
PASS_ASSIST_ANGLE = 0.24          # rad: a team-mate this close to the drawn line is the intended receiver
PASS_ASSIST = (0.35, 0.35)        # fraction of the angle corrected = a + b * passing/100 (moderate, never a lock-on)
DEFENCE_REACTION = (0.35, 0.2)    # s: a - b * defending/100 before an outfield defender reacts
# Keeper
KEEPER_REACTION = (0.42, 0.2)     # s: a - b * keeping/100 (+0.08 s when the view is blocked)
KEEPER_LATERAL = (1.9, 1.9)       # m/s: a + b * keeping/100
KEEPER_REACH = (0.75, 1.0)        # m: standing reach + dive bonus * keeping/100 once the dive had time
# Clock and pacing (real time, not physics)
CLOCK_MINUTES_PER_SECOND = 4.0  # fast simulation between opportunities: 90' in ~22 s
HALF_TIME_SECONDS = 6.0
OUTCOME_PAUSE_SECONDS = 1.8   # banner after an opportunity ends (celebrations are skippable on the client)
EXECUTE_TAIL_SECONDS = 0.2    # after the last frame of an action, before the next decision opens
CONNECTED_WINDOW = 6.0        # a client polling within this window counts as connected
RECONNECT_GRACE = 30.0        # approved tolerance (validation 47)
DECISION_CHOICES = (5, 10, 15, 20)
DURATION_CHOICES = (60, 90, 120, 180)   # the room's approved match durations
OPPORTUNITY_COST_SECONDS = 13.0         # mean real cost of one decisive moment (measured: tools/match_duration.py)
ACTION_TYPES = ("PASS", "LOFT", "CARRY", "SHOT")
KINDS = ("BUILDUP", "COUNTER", "WING", "CROSS", "THROUGH", "ONE_ON_ONE", "REBOUND", "FREE_KICK", "PENALTY", "CORNER", "OVERLOAD")
ENGINES = ("v6", "v7", "v8")      # v6: original Pitch (kept intact); v7/v8: app.domain.football (docs/v7, docs/v8)
DIFFICULTIES = ("EASY", "NORMAL", "HARD")
KIND_LABEL = {"BUILDUP": "Ataque trabalhado", "COUNTER": "Contra-ataque", "WING": "Jogada pela ponta",
              "CROSS": "Chegada à linha de fundo", "THROUGH": "Infiltração", "ONE_ON_ONE": "Cara a cara", "REBOUND": "Sobra na entrada da área",
              "FREE_KICK": "Falta perigosa", "PENALTY": "Pênalti", "CORNER": "Escanteio", **football.DRILLS}


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
    facing: float = 0.0   # body orientation (V7; V6 ignores it)

    @property
    def top_speed(self) -> float:
        return PLAYER_BASE_SPEED + self.pace / 100 * PLAYER_PACE_SPEED


@dataclass
class Ball:
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    z: float = 0.0
    vz: float = 0.0          # vertical speed of a shot/rebound (lofted passes use air_left)
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


def build_timeline(home: TeamInput, away: TeamInput, seed: int, ruleset: str, engine: str = "v6", chance_factor: float = 1.0) -> list[dict[str, object]]:
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
        rate = 5.0 * math.exp((att - (dfn * 0.8 + gk * 0.2)) / 18) * mentality * (1 + 0.12 * team.cohesion)
        # Competitive duration (docs/v8/DURACAO_PARTIDAS.md): a shorter match has proportionally
        # fewer decisive moments; each one keeps exactly the same chances (no goal multiplier).
        rate *= chance_factor
        count = 0
        # Poisson draw (Knuth), clamped to a playable range.
        limit, product = math.exp(-_clamp(rate, 1.2 * chance_factor, 8.0)), rng.random()
        while product > limit:
            count += 1
            product *= rng.random()
        count = int(_clamp(count, 1, 9))
        style = team.tactics.style
        weights = {"BUILDUP": 3.0, "COUNTER": 2.0, "WING": 2.0, "CROSS": 1.5, "THROUGH": 1.8, "ONE_ON_ONE": 0.5, "REBOUND": 0.9}
        weights[{"POSSESSION": "BUILDUP", "SHORT_BUILDUP": "BUILDUP", "COUNTER": "COUNTER", "WIDE": "WING", "DIRECT": "THROUGH"}.get(style, "BUILDUP")] += 2.5
        if style == "WIDE":
            weights["CROSS"] += 1.5
        if ruleset == "TRADITIONAL":
            weights["FREE_KICK"] = 0.8
            weights["PENALTY"] = 0.25
        if engine in ("v7", "v8"):
            weights["OVERLOAD"] = 1.2 + (0.8 if style in ("COUNTER", "DIRECT") else 0.0)
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
    cfg = HL_PITCH[mode]
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
            # Occupy the width: wide slots hug the touchlines, the rest spread across.
            lateral = player.slot_x / 100
            if lateral < 0.22 or lateral > 0.78:
                lateral = 0.07 if lateral < 0.5 else 0.93
            body.y = lateral * W
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
    # The whole move happens on one side or the other: no two openings look the same.
    if kind not in ("PENALTY", "FREE_KICK", "CORNER"):
        shift = rng.uniform(-7, 7) * s * (W / 68 / s)
        for body in attackers + defenders:
            if body.role != "GK":
                body.y = _clamp(body.y + shift * (1.0 if body.team == "A" else 0.6), 1.5 * s, W - 1.5 * s)
    outfield = [b for b in attackers if b.role != "GK"]
    by_role = lambda *roles: [b for b in outfield if b.role in roles] or outfield  # noqa: E731
    if kind in ("BUILDUP",):
        carrier = rng.choice(by_role("MF"))
        carrier.x = min(carrier.x, (52 + rng.uniform(-4, 12)) * s)
    elif kind == "REBOUND":
        # A cleared ball drops to an attacker at the edge of the box, with defenders closing.
        carrier = rng.choice(by_role("MF", "ST"))
        carrier.x, carrier.y = L - (19 + rng.uniform(0, 7)) * s, W / 2 + rng.uniform(-11, 11) * s
        for body in sorted((b for b in defenders if b.role != "GK"), key=lambda b: _dist(b.x, b.y, carrier.x, carrier.y))[:2]:
            body.x, body.y = carrier.x + rng.uniform(1.6, 3.5) * s, carrier.y + rng.uniform(-3, 3) * s
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
    """Personal space: nobody inside anybody (1.3 m) and team-mates spread out (a team never
    starts bunched); everybody on the pitch; the carrier keeps its spot."""
    mates = max(1.3, 4.5 * L / 105)
    for _ in range(8):
        for i, a in enumerate(bodies):
            for b in bodies[i + 1:]:
                d = _dist(a.x, a.y, b.x, b.y)
                need = mates if a.team == b.team and "GK" not in (a.role, b.role) else 1.3
                if d < need:
                    angle = (zlib.crc32(f"{a.id}|{b.id}".encode()) % 628) / 100 if d < 1e-6 else math.atan2(b.y - a.y, b.x - a.x)
                    push = (need - d) / 2 + 0.01
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
    shooter: str | None = None      # who finished (a header is not finished by the crosser)
    post: bool = False
    cues: list[dict[str, object]] = field(default_factory=list)  # timed moments for animation and sound


def _wrap(angle: float) -> float:
    return (angle + math.pi) % (2 * math.pi) - math.pi


class Pitch:
    """Physics + AI movement of one action. Bodies and ball are mutated in place.

    Local frame: the attacking side attacks towards x = L. ``HighlightMatch`` turns it into
    the real pitch (each club attacks its own end, switching at half-time) exactly once."""

    def __init__(self, bodies: list[Body], ball: Ball, mode: str, rng: random.Random, pressure_boost: float = 0.0,
                 tactics: dict[str, str] | None = None) -> None:
        cfg = HL_PITCH[mode]
        self.L, self.W = cfg["length"], cfg["width"]
        self.goal = cfg["goal"]
        self.goal_h = cfg["goal_height"]
        self.s = self.L / 105.0
        self.bodies, self.ball, self.rng = bodies, ball, rng
        self.boost = pressure_boost
        self.attackers = [b for b in bodies if b.team == "A"]
        self.defenders = [b for b in bodies if b.team == "D"]
        self.keeper = next((b for b in self.defenders if b.role == "GK"), None)
        self.shot_live = False
        self.shot_t0 = 0.0
        self.keeper_done = False
        self.ball0 = (ball.x, ball.y)
        self.cover: str | None = None
        self.passer: str | None = None       # give-and-go: the passer keeps running into space
        # The clubs' saved tactics shape the movement (reused, never duplicated):
        # attacking style (runs), defending mentality (depth/compactness) and pressure (reaction).
        t = tactics or {}
        self.style = t.get("style", "POSSESSION")
        self.def_mentality = t.get("def_mentality", "BALANCED")
        self.def_pressure = t.get("def_pressure", "MEDIUM")
        self.cues: list[dict[str, object]] = []

    def cue(self, t: float, kind: str, body: Body | None = None, **extra: object) -> None:
        self.cues.append({"t": round(t, 2), "kind": kind, "id": body.id if body else None, **extra})

    def frame(self, t: float) -> list[float]:
        b = self.ball
        row = [round(t, 2), round(b.x / self.L, 4), round(b.y / self.W, 4), round(b.z, 2)]
        for body in self.bodies:
            row += [round(body.x / self.L, 4), round(body.y / self.W, 4)]
        return row

    def pressure_on(self, body: Body) -> float:
        nearest = min((_dist(body.x, body.y, d.x, d.y) for d in self.defenders if d.role != "GK"), default=20.0)
        return _clamp(1 - nearest / PRESSURE_RADIUS, 0.0, 1.0)

    def xg(self, x: float, y: float) -> float:
        d = _dist(x, y, self.L, self.W / 2)
        angle = abs(math.atan2(self.goal * (self.L - x), (self.L - x) ** 2 + (y - self.W / 2) ** 2 - (self.goal / 2) ** 2))
        scale = 105 / self.L
        return round(_clamp(0.9 * angle * math.exp(-d * scale / 22), 0.01, 0.85), 3)

    # ------------------------------------------------------------ movement AI
    def _steer(self, body: Body, tx: float, ty: float, intensity: float = 1.0, accel: float | None = None) -> None:
        if accel is None:
            accel = PLAYER_ACCEL[0] + PLAYER_ACCEL[1] * body.pace / 100
        tx, ty = _clamp(tx, 0.3, self.L - 0.2), _clamp(ty, 0.3, self.W - 0.3)
        dx, dy = tx - body.x, ty - body.y
        d = math.hypot(dx, dy)
        top = body.top_speed * intensity
        desired = min(top, d * 2.2)
        dvx, dvy = (dx / d * desired, dy / d * desired) if d > 1e-6 else (0.0, 0.0)
        step = accel * DT
        body.vx += _clamp(dvx - body.vx, -step, step)
        body.vy += _clamp(dvy - body.vy, -step, step)
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

    def _intercept(self, body: Body) -> tuple[float, float]:
        """Earliest point of the ball's path this player can reach (pursuit, not chase)."""
        for step in range(1, 31):
            t = step * 0.1
            bx, by = self._ball_at(t)
            if _dist(body.x, body.y, bx, by) <= body.top_speed * max(0.0, t - 0.1) + 0.4:
                return bx, by
        return self._ball_at(3.0)

    def _spread(self, body: Body, tx: float, ty: float, radius: float) -> tuple[float, float]:
        """Keep the shape: no two team-mates on the same spot (no artificial clusters)."""
        for mate in self.bodies:
            if mate is body or mate.team != body.team or mate.role == "GK":
                continue
            d = _dist(mate.x, mate.y, tx, ty)
            if d < radius:
                if d < 1e-6:
                    tx, ty = tx, ty + (radius if body.y < self.W / 2 else -radius) * 0.5
                    continue
                push = (radius - d) * 0.6
                tx += (tx - mate.x) / d * push
                ty += (ty - mate.y) / d * push
        return tx, ty

    def _openness(self, x: float, y: float) -> float:
        return min((_dist(x, y, d.x, d.y) for d in self.defenders if d.role != "GK"), default=12.0)

    def _support(self, body: Body, t: float) -> tuple[float, float, float]:
        """Off-the-ball runs of the attack: the striker on the last defender's shoulder and
        attacking depth, wingers holding width, midfielders showing for the ball in a free lane;
        the player who just passed goes again (give-and-go). The team's style shapes all of it."""
        b, s, L, W = self.ball, self.s, self.L, self.W
        if body.id == self.passer:
            # Pass and move: into the space ahead, on the side away from the nearest defender.
            side = 1 if body.y < W / 2 else -1
            near = min((d for d in self.defenders if d.role != "GK"), key=lambda d: _dist(d.x, d.y, body.x, body.y), default=None)
            if near is not None:
                side = 1 if near.y < body.y else -1
            tx = min(body.x + 8 * s, L - 6 * s)            # keeps going: the target stays ahead of him
            return tx, _clamp(body.y + side * 3 * s, 2 * s, W - 2 * s), 1.0
        depth_bonus = 3.0 * s if self.style == "COUNTER" else 1.5 * s if self.style == "DIRECT" else 0.0
        show = (5, 8) if self.style in ("POSSESSION", "SHORT_BUILDUP") else (7, 11)
        line = max((d.x for d in self.defenders if d.role != "GK"), default=L - 12 * s)
        progress = b.x - self.ball0[0]
        wide = min(body.ay, W - body.ay) < W * 0.2
        if body.role == "ST":
            depth = min(1.0, t / 2.0)
            tx = _clamp(max(body.ax + progress * 0.5, line - 1.5 * s + 2.5 * s * depth + depth_bonus), body.ax, L - 5 * s)
            base_y = body.ay + (b.y - body.ay) * 0.15
            ty = max((base_y + k * 4 * s for k in (-1, 0, 1)), key=lambda y: self._openness(tx, y) - abs(y - base_y) * 0.1)
            return tx, ty, 1.0 if self.style in ("COUNTER", "DIRECT") else 0.85
        if wide:
            tx = _clamp(max(body.ax, b.x + (6 if self.style == "WIDE" else 3) * s), body.ax, L - 7 * s)
            hug = 0.9 if self.style == "WIDE" else 0.3
            ty = body.ay + (2 * s if body.ay > W / 2 else -2 * s) * hug
            return tx, ty, 0.85
        near = _dist(body.x, body.y, b.x, b.y) < 22 * s
        tx = body.ax + max(0.0, progress) * 0.75
        ty = body.ay + (b.y - body.ay) * 0.2
        if near:
            # Show for the ball: a short, open angle (a passing line), never on top of the carrier.
            side = 1 if body.ay >= b.y else -1
            candidates = [(b.x + dx * s, b.y + side * dy * s) for dx in (-6, -2, 3) for dy in show]
            candidates.append((tx, ty))
            tx, ty = max(candidates, key=lambda c: self._openness(*c) - _dist(c[0], c[1], body.x, body.y) * 0.12)
        return tx, ty, 0.8

    def _defend(self, body: Body, mark: Body | None) -> tuple[float, float, float]:
        """Defensive positioning: goal-side of the mark, the block sliding to the ball and
        dropping to protect the box when the ball gets close."""
        b, s, L, W = self.ball, self.s, self.L, self.W
        gx, gy = L, W / 2
        if mark is not None:
            d = max(1.0, _dist(mark.x, mark.y, gx, gy))
            tx = mark.x + (gx - mark.x) / d * 1.8 + (b.x - mark.x) * 0.1
            ty = mark.y + (gy - mark.y) / d * 1.8 + (b.y - mark.y) * 0.12
            intensity = 0.92
        else:
            tx = body.ax + (b.x - body.ax) * 0.3
            ty = body.ay + (b.y - body.ay) * 0.4
            intensity = 0.75
        if self.def_mentality in ("DEFENSIVE", "VERY_DEFENSIVE"):
            tx += (3.0 if self.def_mentality == "DEFENSIVE" else 5.0) * s   # deeper block
            ty = gy + (ty - gy) * 0.85                                      # more compact
        elif self.def_mentality in ("ATTACKING", "VERY_ATTACKING"):
            tx -= 2.0 * s
        if body.role == "DF" and L - b.x < 30 * s:
            tx = max(tx, L - 15 * s)              # protect the box
            ty = gy + (ty - gy) * 0.8
        return tx, ty, intensity

    def move_players(self, t: float, carrier: Body | None, intended: Body | None, chasers: set[str], marks: dict[str, Body]) -> None:
        for body in self.bodies:
            if body is carrier:
                continue
            if body.team == "A":
                if body is intended:
                    tx, ty = self._intercept(body)   # run onto the ball's path (passes into space)
                    self._steer(body, tx, ty)
                elif body.role == "GK":
                    self._steer(body, body.ax, body.ay, 0.4)
                else:
                    tx, ty, intensity = self._support(body, t)
                    tx, ty = self._spread(body, tx, ty, 6.0 * self.s)
                    self._steer(body, tx, ty, intensity)
                continue
            if body.role == "GK":
                if not self.shot_live:
                    self._keeper_position(body)
                continue
            reaction = DEFENCE_REACTION[0] - body.defending / 100 * DEFENCE_REACTION[1] - self.boost \
                + {"HIGH": -0.06, "LOW": 0.06}.get(self.def_pressure, 0.0)
            if t < reaction:
                continue
            if body.id in chasers:
                tx, ty = self._intercept(body)
                self._steer(body, tx, ty)
                continue
            if body.id == self.cover:
                # Cover: between the ball and the goal, behind the presser.
                b, gx, gy = self.ball, self.L, self.W / 2
                d = max(1.0, _dist(b.x, b.y, gx, gy))
                gap = min(7.0 * self.s ** 0.5, d * 0.5)
                self._steer(body, b.x + (gx - b.x) / d * gap, b.y + (gy - b.y) / d * gap, 0.95)
                continue
            tx, ty, intensity = self._defend(body, marks.get(body.id))
            tx, ty = self._spread(body, tx, ty, 2.2 * self.s ** 0.5)
            self._steer(body, tx, ty, intensity)

    def _keeper_position(self, gk: Body) -> None:
        b = self.ball
        gx, gy = self.L, self.W / 2
        d = _dist(b.x, b.y, gx, gy)
        off = _clamp(d * 0.12, 0.6, 5.5) * (0.7 + gk.keeping / 100 * 0.3) * self.s ** 0.5
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
            if _dist(target.x, target.y, defender.x, defender.y) < 18 * self.s ** 0.5:
                marks[defender.id] = target
                free.remove(target)
        return marks

    # ------------------------------------------------------------ resolve an action
    def execute(self, carrier: Body, action: str, tx: float, ty: float, power: float, passer_last: str | None) -> ActionResult:
        result = self._execute(carrier, action, tx, ty, power)
        result.cues = self.cues
        return result

    def _assist_receiver(self, carrier: Body, aim: float, want: float) -> tuple[Body | None, float]:
        """Moderate pass assistance: a team-mate close to the drawn line (angle and distance
        compatible) is the intended receiver; the ball is bent part of the way towards where
        he is running. Never a lock-on: pressure and the passer's error still apply."""
        best, best_score = None, 9.0
        for a in self.attackers:
            if a is carrier or a.role == "GK":
                continue
            d = _dist(a.x, a.y, carrier.x, carrier.y)
            if d < 2.5 or not (0.3 * want <= d <= 1.6 * want + 4):
                continue
            diff = abs(_wrap(math.atan2(a.y - carrier.y, a.x - carrier.x) - aim))
            if diff > PASS_ASSIST_ANGLE:
                continue
            score = diff + abs(d - want) / max(want, 1) * 0.15
            if score < best_score:
                best, best_score = a, score
        if best is None:
            return None, aim
        d = _dist(best.x, best.y, carrier.x, carrier.y)
        lead = min(1.2, d / 14)
        lx, ly = best.x + best.vx * lead, best.y + best.vy * lead
        correction = _wrap(math.atan2(ly - carrier.y, lx - carrier.x) - aim) * (PASS_ASSIST[0] + PASS_ASSIST[1] * carrier.passing / 100)
        return best, aim + correction

    def _execute(self, carrier: Body, action: str, tx: float, ty: float, power: float) -> ActionResult:
        rng, b = self.rng, self.ball
        L, W, s = self.L, self.W, self.s
        pressure = self.pressure_on(carrier)
        frames = [self.frame(0.0)]
        dx, dy = tx - carrier.x, ty - carrier.y
        aim = math.atan2(dy, dx)
        dist_aim = math.hypot(dx, dy)
        shot = action == "SHOT"          # live shot (the keeper reacts) until blocked/deflected
        was_shot = shot                  # for the statistics: a blocked shot is still a shot
        shooter = carrier
        self.shot_live = shot
        xg = self.xg(carrier.x, carrier.y) if shot else 0.0
        intended = None
        if action == "PASS":
            sd = PASS_ERROR * (1.3 - carrier.passing / 100) * (1 + pressure * 0.9) * (0.7 + power * 0.6)
            v0 = PASS_SPEED[0] + PASS_SPEED[1] * power
            intended, aim = self._assist_receiver(carrier, aim, v0 * v0 / (2 * GROUND_DECEL))
        elif action == "LOFT":
            sd = LOFT_ERROR * (1.3 - carrier.passing / 100) * (1 + pressure * 0.8)
            v0 = LOFT_SPEED[0] + LOFT_SPEED[1] * power
            flight = (LOFT_RANGE[0] + LOFT_RANGE[1] * power) * s
            intended, aim = self._assist_receiver(carrier, aim, flight)
            flight *= 1 + rng.gauss(0, 0.09 * (1.2 - carrier.passing / 100))
            b.air_total = b.air_left = flight / v0
        elif action == "SHOT":
            sd = SHOT_ERROR * (1.35 - carrier.shooting / 100) * (1 + pressure * 1.0) * (0.75 + max(0.0, power - 0.55) * 1.6)
            v0 = SHOT_SPEED[0] + SHOT_SPEED[1] * power
            # Height: a placed shot stays low, a hard one rises (and can go over the bar).
            b.vz = max(0.0, SHOT_LIFT[0] + SHOT_LIFT[1] * max(0.0, power - 0.35)
                       + rng.gauss(0, 1.1 * (1.35 - carrier.shooting / 100) * (1 + pressure * 0.5)))
        else:  # CARRY
            return self._carry(carrier, aim, min(dist_aim, (CARRY_RANGE[0] + CARRY_RANGE[1] * power) * s), frames)
        angle = aim + rng.gauss(0, sd)
        b.x, b.y = carrier.x + math.cos(angle) * 0.5, carrier.y + math.sin(angle) * 0.5
        b.vx, b.vy = math.cos(angle) * v0, math.sin(angle) * v0
        self.cue(0.0, "KICK", carrier, action=action, power=round(power, 2))
        if action in ("PASS", "LOFT"):
            self.passer = carrier.id
        if not shot and intended is None:
            intended = min((a for a in self.attackers if a is not carrier and a.role != "GK"),
                           key=lambda a: _dist(a.x, a.y, tx, ty), default=None)
        marks = self.assignments()
        ranked = sorted((d for d in self.defenders if d.role != "GK"), key=lambda d: self._time_to_ball(d))
        chasers = {d.id for d in ranked[:2 if self.def_pressure == "HIGH" else 1]}   # one presses the ball (two under high pressure)...
        self.cover = ranked[1].id if len(ranked) > 1 else None   # ...one covers; the rest keep their zones
        tried: set[str] = set()
        keeper_reacts = KEEPER_REACTION[0] - (self.keeper.keeping / 100 * KEEPER_REACTION[1] if self.keeper else 0) - self.boost * 0.3
        screened = shot and any(_dist(d.x, d.y, *self._project(carrier, angle, 6)) < 1.2 for d in self.defenders if d.role != "GK")
        if screened:
            keeper_reacts += 0.08
        post = False
        t = 0.0
        last_touch = "A"
        while t < MAX_ACTION_SECONDS:
            t += DT
            px, py, pz = b.x, b.y, b.z
            self._ball_step(shot)
            self.move_players(t, None, intended, chasers, marks)
            if shot and self.keeper:
                outcome = self._keeper_vs_shot(t - self.shot_t0, keeper_reacts, frames, t, px, py, pz)
                if outcome:
                    self.shot_live = False
                    return self._shot_result(outcome, frames, t, xg, shooter, post)
            frames.append(self.frame(t))
            # Over the goal line: goal, post, corner or goal kick (exact crossing point, not the step's end).
            if b.x >= L:
                k = (L - px) / (b.x - px) if b.x != px else 1.0
                cross_y = py + (b.y - py) * k
                cross_z = pz + (b.z - pz) * k
                off = abs(cross_y - W / 2)
                low = cross_z <= self.goal_h - BALL_RADIUS
                if off <= self.goal / 2 and abs(cross_z - self.goal_h) <= POST_RADIUS + BALL_RADIUS:
                    # Crossbar: down and back into play.
                    self.cue(t, "BAR", None)
                    post = True
                    speed = math.hypot(b.vx, b.vy)
                    b.x, b.y, b.z = L - 0.3, cross_y, max(0.5, cross_z - 0.3)
                    b.vx, b.vy = -abs(b.vx) * rng.uniform(0.25, 0.45), b.vy * 0.5 + rng.uniform(-2, 2)
                    b.vz, b.air_left = -abs(b.vz) * 0.4 - 1.0, 0.0
                    frames[-1] = self.frame(t)
                    shot = self.shot_live = False
                    intended = min((a for a in self.attackers if a.role != "GK"), key=lambda a: _dist(a.x, a.y, b.x, b.y))
                    tried.clear()
                    continue
                if low and abs(off - self.goal / 2) <= POST_RADIUS + BALL_RADIUS:
                    inner = off < self.goal / 2
                    self.cue(t, "POST", None)
                    post = True
                    if inner and rng.random() < 0.4:
                        b.x, b.y, b.vx, b.vy = L + 0.6, cross_y, 0.0, 0.0
                        frames[-1] = self.frame(t)
                        self.cue(t, "GOAL", shooter)
                        return ActionResult("GOAL", frames, detail="Na trave… e entra!", shot=was_shot, on_target=True, xg=xg, shooter=shooter.id, post=True)
                    # Back into play: a rebound for whoever is quicker.
                    speed = math.hypot(b.vx, b.vy)
                    away = -1 if cross_y > W / 2 else 1
                    out_dir = away if inner else -away
                    ang = math.pi + out_dir * rng.uniform(0.25, 0.9)
                    sp = speed * rng.uniform(0.3, 0.5)
                    b.x, b.y = L - 0.3, cross_y
                    b.vx, b.vy = math.cos(ang) * sp, math.sin(ang) * sp
                    b.air_left, b.z = 0.0, 0.0
                    frames[-1] = self.frame(t)
                    shot = self.shot_live = False
                    last_touch = "A"
                    intended = min((a for a in self.attackers if a.role != "GK"), key=lambda a: _dist(a.x, a.y, b.x, b.y))
                    chasers = {d.id for d in sorted((d for d in self.defenders if d.role != "GK"), key=lambda d: _dist(d.x, d.y, b.x, b.y))[:2]}
                    tried.clear()
                    continue
                if low and off <= self.goal / 2 - BALL_RADIUS:
                    b.x, b.y, b.vx, b.vy, b.z, b.vz = L + 0.6, cross_y, 0.0, 0.0, min(cross_z, self.goal_h - 0.3), 0.0
                    frames[-1] = self.frame(t)
                    self.cue(t, "GOAL", shooter)
                    return ActionResult("GOAL", frames, detail="Gol", shot=was_shot, on_target=True, xg=xg, shooter=shooter.id, post=post)
                self.cue(t, "OUT", None)
                if last_touch == "D":
                    return ActionResult("CORNER", frames, detail="Escanteio", shot=was_shot, xg=xg, shooter=shooter.id, post=post)
                over = off <= self.goal / 2 + 1 and cross_z > self.goal_h
                return ActionResult("OUT", frames, detail=("Por cima do gol" if over else "Para fora") if was_shot else "Bola pela linha de fundo",
                                    shot=was_shot, xg=xg, shooter=shooter.id, post=post)
            if b.x <= 0 or b.y <= 0 or b.y >= W:
                self.cue(t, "OUT", None)
                return ActionResult("OUT", frames, detail="Para fora" if was_shot else "Bola fora", shot=was_shot, xg=xg, shooter=shooter.id, post=post)
            if b.air_left > 0:
                header = self._header(t, tried, frames)
                if header is not None:
                    kind, body = header
                    if kind == "LOST":
                        return ActionResult("LOST", frames, detail=f"{body.name} afasta de cabeça", lost_to=body.id)
                    if kind == "CONTROLLED":
                        return ActionResult("CONTROLLED", frames, receiver=body.id, completed_pass=True, detail=f"{body.name} ajeita de cabeça")
                    # A header at goal: a new live shot from the header's point.
                    shot = was_shot = self.shot_live = True
                    shooter, self.shot_t0, self.keeper_done = body, t, False
                    xg = round(self.xg(body.x, body.y) * 0.7, 3)
                    keeper_reacts = KEEPER_REACTION[0] - (self.keeper.keeping / 100 * KEEPER_REACTION[1] if self.keeper else 0)
                    intended = None
                    continue
                if b.z > 1.9:
                    continue  # in the air: nobody can play it
            speed = math.hypot(b.vx, b.vy)
            # Who reaches the ball first this step.
            contenders = sorted(self.bodies, key=lambda body: _dist(body.x, body.y, b.x, b.y))
            for body in contenders:
                d = _dist(body.x, body.y, b.x, b.y)
                if body is shooter and t - self.shot_t0 < 0.5:
                    continue
                if body is carrier and t < 0.5:
                    continue
                if body.team == "D":
                    reach = KEEPER_CLAIM_RADIUS if body.role == "GK" else TACKLE_RADIUS
                    if d > reach or body.id in tried:
                        continue
                    tried.add(body.id)
                    if body.role == "GK" and not shot:
                        in_box = b.x > L - 16.5 * s and abs(b.y - W / 2) < 20 * (W / 68)
                        if in_box and rng.random() < 0.55 + body.keeping / 100 * 0.4:
                            self.cue(t, "CLAIM", body)
                            return ActionResult("LOST", frames, detail="O goleiro sai e fica com a bola", lost_to=body.id)
                        continue
                    if body.role == "GK":
                        continue  # a live shot is the keeper's save routine
                    chance = _clamp(INTERCEPT[0] + body.defending / 100 * INTERCEPT[1] - speed * INTERCEPT[2] + self.boost, 0.06, 0.8)
                    if shot:
                        chance *= 0.55  # a shot blocked, not intercepted cleanly
                    if rng.random() < chance:
                        if shot:
                            ang = math.atan2(b.vy, b.vx) + math.pi + rng.uniform(-1.0, 1.0)
                            sp = speed * rng.uniform(0.25, 0.45)
                            b.vx, b.vy = math.cos(ang) * sp, math.sin(ang) * sp
                            shot = self.shot_live = False
                            last_touch = "D"
                            self.cue(t, "BLOCK", body)
                            frames[-1] = self.frame(t)
                            intended = min((a for a in self.attackers if a.role != "GK"), key=lambda a: _dist(a.x, a.y, b.x, b.y))
                            continue
                        self.cue(t, "INTERCEPT", body)
                        return ActionResult("LOST", frames, detail=f"Interceptação de {body.name}", lost_to=body.id, shot=was_shot, xg=xg, shooter=shooter.id)
                    # Deflection: the ball carries on, slower and off line.
                    ang = math.atan2(b.vy, b.vx) + rng.uniform(-0.5, 0.5)
                    sp = speed * 0.7
                    b.vx, b.vy = math.cos(ang) * sp, math.sin(ang) * sp
                    last_touch = "D"
                    self.cue(t, "DEFLECT", body)
                    break
                if body.role == "GK" or d > CONTROL_RADIUS:
                    continue
                control = _clamp(0.99 - max(0.0, speed - 11) * 0.045 * (1.25 - body.dribbling / 100) - (0.12 if b.air_left > 0 else 0), 0.35, 0.99)
                if rng.random() < control:
                    b.vx = b.vy = 0.0
                    b.air_left = 0.0
                    b.z = 0.0
                    heading = math.atan2(body.vy, body.vx) if math.hypot(body.vx, body.vy) > 0.5 else 0.0
                    b.x, b.y = body.x + math.cos(heading) * 0.4, body.y + math.sin(heading) * 0.4
                    frames[-1] = self.frame(t)
                    self.cue(t, "CONTROL", body)
                    return ActionResult("CONTROLLED", frames, receiver=body.id, completed_pass=not was_shot and body is not carrier,
                                        detail=f"{body.name} domina", shot=was_shot, xg=xg, shooter=shooter.id if was_shot else None, post=post)
                # Heavy touch: it bounces off, still live.
                ang = rng.uniform(-math.pi, math.pi)
                b.vx, b.vy = math.cos(ang) * speed * 0.35, math.sin(ang) * speed * 0.35
                self.cue(t, "TOUCH", body)
                break
            if speed < 0.25 and b.air_left <= 0:
                # Dead ball nobody controls yet: players race for it.
                intended = min((a for a in self.attackers if a.role != "GK"), key=lambda a: _dist(a.x, a.y, b.x, b.y))
                nearest_d = min((d for d in self.defenders if d.role != "GK"), key=lambda d: _dist(d.x, d.y, b.x, b.y), default=None)
                chasers = {nearest_d.id} if nearest_d else set()
        # Settled by proximity (the guard is deterministic and never fires mid-flight).
        nearest = min((body for body in self.bodies if body.role != "GK"), key=lambda body: _dist(body.x, body.y, b.x, b.y))
        if nearest.team == "A":
            b.vx = b.vy = 0.0
            return ActionResult("CONTROLLED", frames, receiver=nearest.id, detail=f"{nearest.name} fica com a sobra", shot=was_shot, xg=xg,
                                shooter=shooter.id if was_shot else None, post=post)
        return ActionResult("LOST", frames, detail="A defesa recupera", lost_to=nearest.id, shot=was_shot, xg=xg, shooter=shooter.id if was_shot else None, post=post)

    def _header(self, t: float, tried: set[str], frames: list[list[float]]) -> tuple[str, Body] | None:
        """A dropping lofted ball at head height: an aerial duel (physical, a little pace).
        In the box the winning attacker heads at goal; elsewhere he cushions it down."""
        b, s, L, W = self.ball, self.s, self.L, self.W
        if not (HEADER_Z[0] <= b.z <= HEADER_Z[1]) or b.air_left > b.air_total * 0.5:
            return None
        att = min((a for a in self.attackers if a.role != "GK" and a.id not in tried), key=lambda a: _dist(a.x, a.y, b.x, b.y), default=None)
        dfn = min((d for d in self.defenders if d.role != "GK" and d.id not in tried), key=lambda d: _dist(d.x, d.y, b.x, b.y), default=None)
        att_in = att is not None and _dist(att.x, att.y, b.x, b.y) <= 1.1
        dfn_in = dfn is not None and _dist(dfn.x, dfn.y, b.x, b.y) <= 1.1
        if not att_in and not dfn_in:
            return None
        if att_in and dfn_in:
            tried.update((att.id, dfn.id))
            p_att = _clamp(0.5 + (att.physical - dfn.physical) / 120 + (att.pace - dfn.pace) / 400, 0.2, 0.8)
            winner = att if self.rng.random() < p_att else dfn
        else:
            winner = att if att_in else dfn
            tried.add(winner.id)
            if winner.team == "A" and self.rng.random() > 0.85:
                return None  # misjudged the flight
        self.cue(t, "HEADER", winner)
        header_z = b.z
        b.air_left, b.z, b.vz = 0.0, 0.0, 0.0
        if winner.team == "D":
            ang = math.pi + self.rng.uniform(-0.9, 0.9)
            sp = 8 + winner.physical / 100 * 6
            b.vx, b.vy = math.cos(ang) * sp, math.sin(ang) * sp
            frames[-1] = self.frame(t)
            return "LOST", winner
        in_zone = b.x > L - 20 * s and abs(b.y - W / 2) < 13 * s
        if not in_zone:
            b.vx = b.vy = 0.0
            b.x, b.y = winner.x + 0.4, winner.y
            frames[-1] = self.frame(t)
            return "CONTROLLED", winner
        keeper_y = self.keeper.y if self.keeper else W / 2
        side = -1 if keeper_y > W / 2 else 1
        ty = W / 2 + side * (self.goal / 2 - 0.6) * self.rng.uniform(0.3, 1.0)
        aim = math.atan2(ty - b.y, L - b.x)
        skill = (winner.shooting * 0.5 + winner.physical * 0.5) / 100
        angle = aim + self.rng.gauss(0, 0.09 * (1.4 - skill))
        sp = HEADER_SPEED[0] + HEADER_SPEED[1] * winner.physical / 100
        b.vx, b.vy = math.cos(angle) * sp, math.sin(angle) * sp
        b.z, b.vz = header_z, -1.2 + self.rng.uniform(-0.6, 0.8)   # headed down towards goal
        frames[-1] = self.frame(t)
        return "SHOT", winner

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
            airborne = b.z > 0 or b.vz > 0
            decel = 0.4 if airborne else SHOT_DECEL if shot else GROUND_DECEL
            if speed > 0:
                factor = max(0.0, speed - decel * DT) / speed
                b.vx *= factor
                b.vy *= factor
            if airborne:
                b.vz -= GRAVITY * DT
                b.z += b.vz * DT
                if b.z <= 0:
                    b.z = 0.0
                    b.vz = -b.vz * 0.45 if b.vz < -1.5 else 0.0   # bounce
                    b.vx *= 0.8
                    b.vy *= 0.8
        b.x += b.vx * DT
        b.y += b.vy * DT

    def _keeper_vs_shot(self, ts: float, reaction: float, frames: list[list[float]], t: float, px: float, py: float, pz: float = 0.0) -> str | None:
        """Physical keeper: reacts after `reaction` s to the real trajectory, moves with
        limited speed, dives with limited reach, and gets ONE chance when the ball crosses
        his plane. No knowledge of anything not yet executed."""
        gk, b = self.keeper, self.ball
        gy = self.W / 2
        if b.vx <= 0 or self.keeper_done:
            return None
        if ts >= reaction:
            time_to = max(0.0, (gk.x - b.x) / b.vx)
            cross_y = b.y + b.vy * time_to
            target = _clamp(cross_y, gy - self.goal / 2 - 1.2, gy + self.goal / 2 + 1.2)
            lateral = KEEPER_LATERAL[0] + gk.keeping / 100 * KEEPER_LATERAL[1]
            gk.y += _clamp(target - gk.y, -lateral * DT, lateral * DT)
            gk.x = min(self.L - 0.4, gk.x + 0.05)
        plane = gk.x - 0.3
        if b.x < plane:
            return None
        self.keeper_done = True
        k = (plane - px) / (b.x - px) if b.x != px else 1.0
        at_y = py + (b.y - py) * _clamp(k, 0.0, 1.0)
        at_z = pz + (b.z - pz) * _clamp(k, 0.0, 1.0)
        dived = ts >= reaction + 0.2
        reach = (KEEPER_REACH[0] + (KEEPER_REACH[1] * gk.keeping / 100 if dived else 0.2)) * self.s ** 0.3
        # Vertical reach: arms above the head (higher after a jump); a ball above it beats him.
        top = (2.15 if dived else 1.95) + gk.keeping / 100 * 0.25
        miss = math.hypot(abs(at_y - gk.y), max(0.0, at_z - top) * 1.6)
        on_target = abs(at_y - gy) <= self.goal / 2 and at_z <= self.goal_h
        if miss > reach:
            if dived and miss < reach + 1.2:
                self.cue(t, "DIVE", gk, dy=round((at_y - gk.y) / self.W, 3))
            return None
        speed = math.hypot(b.vx, b.vy)
        clean = miss < reach * 0.45
        if not (clean or self.rng.random() < 0.15 + gk.keeping / 100 * 0.4):
            self.cue(t, "DIVE", gk, dy=round((at_y - gk.y) / self.W, 3))
            return None
        hold = speed < 23 and self.rng.random() < 0.25 + gk.keeping / 100 * 0.55
        self.cue(t, "SAVE", gk, hold=hold, dy=round((at_y - gk.y) / self.W, 3), high=at_z > 1.4)
        if hold:
            b.vx = b.vy = b.vz = 0.0
            b.x, b.y, b.z = gk.x - 0.3, at_y, 0.0
            frames.append(self.frame(t))
            return "SAVED_HELD"
        # Parry: rebound back into play (or behind for a corner).
        ang = math.pi + self.rng.uniform(-1.1, 1.1)
        if self.rng.random() < 0.3:
            ang = self.rng.choice((-1, 1)) * self.rng.uniform(0.2, 0.9)  # pushed round the post
        sp = speed * self.rng.uniform(0.25, 0.45)
        b.vx, b.vy = math.cos(ang) * sp, math.sin(ang) * sp
        b.x, b.y, b.z, b.vz = gk.x - 0.4, at_y, min(at_z, 1.2), 1.5 if at_z > 1.4 else 0.5
        frames.append(self.frame(t))
        return "PARRIED" if on_target else "PARRIED_WIDE"

    def _shot_result(self, outcome: str, frames: list[list[float]], t: float, xg: float, shooter: Body, post: bool) -> ActionResult:
        gk = self.keeper.id if self.keeper else None
        if outcome == "SAVED_HELD":
            return ActionResult("SAVED_HELD", frames, detail="Defesa do goleiro", shot=True, on_target=True, xg=xg, keeper=gk, shooter=shooter.id, post=post)
        # A parry: keep the ball live a few more seconds - a rebound may stay with the attack.
        rebound = self._loose_ball(t, frames)
        rebound.shot, rebound.on_target, rebound.xg, rebound.keeper = True, outcome == "PARRIED", xg, gk
        rebound.shooter, rebound.post = shooter.id, post
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
                    self.cue(t, "CLAIM", body)
                    return ActionResult("LOST", frames, detail="o goleiro fica com a sobra", lost_to=body.id)
                if body.role == "GK":
                    continue
                if _dist(body.x, body.y, b.x, b.y) < CONTROL_RADIUS:
                    self.cue(t, "CONTROL", body)
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
        """Conduction: the carrier runs with the ball at the foot (a touch ahead every few
        strides, further for poor dribblers); defenders close in and may tackle on contact
        with the ball or the carrier (once each). No loss without contact."""
        rng, b = self.rng, self.ball
        tx, ty = carrier.x + math.cos(angle) * distance, carrier.y + math.sin(angle) * distance
        marks = self.assignments()
        chasers = {d.id for d in sorted((d for d in self.defenders if d.role != "GK"), key=lambda d: _dist(d.x, d.y, carrier.x, carrier.y))[:2]}
        tried: set[str] = set()
        intensity = min(1.0, CARRY_SPEED[0] + CARRY_SPEED[1] * carrier.dribbling / 100)
        touch = CARRY_TOUCH[0] - CARRY_TOUCH[1] * carrier.dribbling / 100
        heading = angle
        self.cue(0.0, "CARRY", carrier)
        t = 0.0
        while t < MAX_ACTION_SECONDS:
            t += DT
            self._steer(carrier, tx, ty, intensity, CARRY_ACCEL)
            if math.hypot(carrier.vx, carrier.vy) > 0.6:
                heading = math.atan2(carrier.vy, carrier.vx)
            stride = (t % 0.5) / 0.5            # the ball is pushed ahead, then caught up with
            ahead = 0.35 + touch * (1 - stride)
            b.x, b.y = carrier.x + math.cos(heading) * ahead, carrier.y + math.sin(heading) * ahead
            self.move_players(t, carrier, None, chasers, marks)
            frames.append(self.frame(t))
            if b.x >= self.L or b.y <= 0 or b.y >= self.W:
                self.cue(t, "OUT", None)
                return ActionResult("OUT", frames, detail="Conduziu para fora")
            for defender in self.defenders:
                if defender.id in tried:
                    continue
                near_ball = _dist(defender.x, defender.y, b.x, b.y) <= TACKLE_RADIUS
                near_body = _dist(defender.x, defender.y, carrier.x, carrier.y) <= TACKLE_RADIUS + 0.15
                if not (near_ball or near_body):
                    continue
                tried.add(defender.id)
                if defender.role == "GK" and rng.random() > 0.35 + defender.keeping / 100 * 0.4:
                    continue
                exposed = 0.06 if near_ball and not near_body else 0.0   # the ball pushed too far is easier to nick
                chance = _clamp(TACKLE[0] + (defender.defending - carrier.dribbling) / TACKLE[1]
                                + (defender.physical - carrier.physical) / TACKLE[2] + self.boost + exposed, 0.1, 0.8)
                if rng.random() < chance:
                    self.cue(t, "TACKLE", defender)
                    return ActionResult("LOST", frames, detail=f"Desarme de {defender.name}", lost_to=defender.id)
                self.cue(t, "DRIBBLE", carrier, past=defender.id)
            if _dist(carrier.x, carrier.y, tx, ty) < 0.6:
                break
        carrier.vx *= 0.4
        carrier.vy *= 0.4
        b.x, b.y = carrier.x + math.cos(heading) * 0.4, carrier.y + math.sin(heading) * 0.4
        frames[-1] = self.frame(t)
        return ActionResult("CONTROLLED", frames, receiver=carrier.id, detail=f"{carrier.name} avança")


# ---------------------------------------------------------------- AI choice (bots, timeouts, disconnections)
def ai_action(bodies: list[Body], ball: Ball, carrier_id: str, mode: str, actions_done: int, kind: str, rng: random.Random) -> dict[str, object]:
    """A sensible contextual action for the carrier: shoot when it is a chance, otherwise the
    most progressive safe pass (or a cross / carry). Same physics as a human gesture."""
    cfg = HL_PITCH[mode]
    L, W, goal = cfg["length"], cfg["width"], cfg["goal"]
    s = L / 105
    carrier = next(b for b in bodies if b.id == carrier_id)
    defenders = [b for b in bodies if b.team == "D"]
    keeper = next((b for b in defenders if b.role == "GK"), None)
    d_goal = _dist(carrier.x, carrier.y, L, W / 2)
    angle_ok = abs(carrier.y - W / 2) < (L - carrier.x) * 1.4 + 4 * s
    must_shoot = actions_done >= MAX_ACTIONS - 1 or kind == "PENALTY"
    if kind == "PENALTY" or (d_goal < 25 * s and angle_ok) or (must_shoot and d_goal < 35 * s):
        side = 1 if (keeper is None or keeper.y <= W / 2) else -1
        if rng.random() < 0.3:
            side = -side
        ty = W / 2 + side * (goal / 2) * rng.uniform(0.55, 0.92)
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
    kits: dict[str, dict[str, object]] = field(default_factory=dict)   # official kit selection (both renderers)
    engine: str = "v6"                # gameplay engine this match started with (snapshots keep it)
    difficulty: str = "NORMAL"        # bot decision quality (Lab / friendlies); never attributes
    # Duration (approved: A+C competitive, B friendlies/Lab). Defaults = the old behaviour.
    duration_mode: str = "FREE"       # "FREE" (B: lasts what the coaches take) | "LIMITED" (A+C)
    duration_seconds: int = 0         # the room's configured duration (60/90/120/180)
    started_at: float = 0.0
    limit_at: float | None = None     # C: server-controlled limit (kick-off + duration)
    limit_reached: bool = False
    clock_rate: float = 4.0           # A: game minutes per real second between opportunities
    half_time_seconds: float = 6.0
    outcome_pause: float = 1.8
    chance_factor: float = 1.0

    # ------------------------------------------------------------ construction
    @classmethod
    def create(cls, match_id: str, mode: str, home: TeamInput, away: TeamInput, home_view: dict, away_view: dict,
               humans: list[str], seed: int, ruleset: str, decision_seconds: int, free_vs_bots: bool, now: float,
               engine: str = "v6", difficulty: str = "NORMAL", duration_seconds: int = 0, limited: bool = False) -> HighlightMatch:
        match = cls(match_id, mode, [home.club_code, away.club_code], sorted(humans), seed, ruleset,
                    decision_seconds if decision_seconds in DECISION_CHOICES else 10, free_vs_bots, [home_view, away_view])
        match.engine = engine if engine in ENGINES else "v6"
        match.difficulty = difficulty if difficulty in DIFFICULTIES else "NORMAL"
        match.started_at = now
        match.clock_rate, match.half_time_seconds, match.outcome_pause = CLOCK_MINUTES_PER_SECOND, HALF_TIME_SECONDS, OUTCOME_PAUSE_SECONDS
        if limited and duration_seconds in DURATION_CHOICES:
            match._plan_duration(int(duration_seconds), now)
        match.timeline = build_timeline(home, away, seed, ruleset, match.engine, match.chance_factor)
        match.kits = select_kits(home.club_code, away.club_code)
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

    def _plan_duration(self, seconds: int, now: float) -> None:
        """A (competitive): the configured duration drives the clock speed, the pauses and how many
        decisive moments the match has; C: a server limit at kick-off + duration.
        The chance of each opportunity is untouched — only how many there are and how fast the
        time between them runs."""
        self.duration_mode, self.duration_seconds = "LIMITED", seconds
        self.limit_at = now + seconds
        self.clock_rate = max(CLOCK_MINUTES_PER_SECOND, 90.0 / (0.2 * seconds))
        self.half_time_seconds = _clamp(0.04 * seconds, 2.5, HALF_TIME_SECONDS)
        self.outcome_pause = _clamp(seconds / 100.0, 1.0, OUTCOME_PAUSE_SECONDS)
        available = seconds * 0.92 - 90.0 / self.clock_rate - self.half_time_seconds
        self.chance_factor = round(_clamp(available / (10.0 * OPPORTUNITY_COST_SECONDS), 0.2, 1.0), 3)

    def _due(self) -> float:
        """Logical time of the next scheduled transition (inf when waiting for a person)."""
        if self.state == "CLOCK":
            return self.clock_since + (self._next_stop() - self.minute) / self.clock_rate
        if self.state in ("HALF_TIME", "OUTCOME", "EXECUTING", "REPLAY"):
            return float(self.state_until) if self.state_until is not None else math.inf
        if self.state == "DECISION":
            due = [x for x in (self.deadline, self.grace_until) if x is not None]
            return min(due) if due else math.inf
        return math.inf

    def _apply_limit(self) -> str:
        """C: the competitive time limit. Nothing already in play is cut: an action or a bot replay
        finishes; a pending decision is taken by the contextual AI (the same one for both teams);
        no new opportunity opens; the match ends at the next safe point."""
        at = float(self.limit_at)
        self.limit_reached = True
        self.revision += 1
        self._event("TIME_LIMIT", None, self.clock_minute(at), reveal=at)
        if self.state == "CLOCK":
            self.minute, self.state, self.finished_at = 90.0, "FINISHED", at
        elif self.state == "HALF_TIME":
            self.state_until = at
        elif self.state == "DECISION":
            self.grace_until = self.paused_left = None
            self._auto(max(at, float(self.opportunity.get("decision_opened_at", at))), "TIME_LIMIT")
        return "LIMIT"

    def teams(self) -> tuple[TeamInput, TeamInput]:
        from app.services.season_service import team_input_from_view  # local: avoid an import cycle
        return team_input_from_view(self.inputs[0]), team_input_from_view(self.inputs[1])

    # ------------------------------------------------------------ helpers
    @property
    def finished(self) -> bool:
        return self.state == "FINISHED"

    def side_of(self, club: str) -> int:
        return self.clubs.index(club)

    def attacks_right(self, side: int, second_half: bool | None = None) -> bool:
        """Real direction of play: home attacks to the right (x = 1) in the first half and to
        the left after half-time; the away side the opposite. Each keeper stays in its own goal."""
        second = self.half_time_done if second_half is None else second_half
        return (side == 0) != second

    @staticmethod
    def to_world(x: float, y: float, right: bool) -> tuple[float, float]:
        """Engine-local (the attack always goes to x = 1) -> real pitch, normalised. A point
        reflection (x, y) -> (1 - x, 1 - y), so a team's left wing stays its left wing. Its own
        inverse: the same call converts a gesture from the pitch back to the local frame."""
        return (x, y) if right else (1 - x, 1 - y)

    def _world_frames(self, frames: list[list[float]], right: bool) -> list[list[float]]:
        if right:
            return frames
        out = []
        if self.engine in ("v7", "v8"):
            # Layout v7: [t, bx, by, bz, (x, y, facing, act) per athlete]; facing turns by pi.
            for row in frames:
                new = [row[0], round(1 - row[1], 4), round(1 - row[2], 4), row[3]]
                for i in range(4, len(row), 4):
                    new += [round(1 - row[i], 4), round(1 - row[i + 1], 4), round(football.world_facing(row[i + 2], False), 2), row[i + 3]]
                out.append(new)
            return out
        for row in frames:
            new = [row[0], round(1 - row[1], 4), round(1 - row[2], 4), row[3]]
            for i in range(4, len(row), 2):
                new += [round(1 - row[i], 4), round(1 - row[i + 1], 4)]
            out.append(new)
        return out

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
            return min(90.0, self.minute + max(0.0, now - self.clock_since) * self.clock_rate)
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
        if self.limit_at is not None and not self.limit_reached and self.limit_at <= now and self.limit_at <= self._due():
            return self._apply_limit()
        if self.state == "CLOCK":
            if self.limit_reached:
                # Past the limit: no new decisive moment — full time at this safe point.
                self.minute, self.state, self.finished_at = 90.0, "FINISHED", self.clock_since
                self.revision += 1
                return "FINISHED"
            target = self._next_stop()
            at = self.clock_since + (target - self.minute) / self.clock_rate
            if at > now:
                return None
            self.minute = target
            if target >= 90.0 and (self.cursor >= len(self.timeline)):
                self.state, self.finished_at = "FINISHED", at
                self.revision += 1
                return "FINISHED"
            if target >= 45.0 and not self.half_time_done and (self.cursor >= len(self.timeline) or float(self.timeline[self.cursor]["minute"]) >= 45):
                self.half_time_done = True
                self.state, self.state_until = "HALF_TIME", at + self.half_time_seconds
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
                self.state, self.state_until = "OUTCOME", at + self.outcome_pause
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
        bodies, ball, carrier = build_scenario("BUILDUP" if kind.startswith("DRILL_") or kind == "OVERLOAD" else kind, attack, defence, self.mode, rng)
        body_rows = [asdict(b) for b in bodies]
        if self.engine in ("v7", "v8"):
            body_rows, carrier = football.opening(body_rows, carrier, kind, HL_PITCH[self.mode], rng, self.engine)
            c = next(b for b in body_rows if b["id"] == carrier)
            ball = Ball(float(c["x"]) + 0.4 * math.cos(float(c["facing"])), float(c["y"]) + 0.4 * math.sin(float(c["facing"])))
        club = self.clubs[side]
        self.stats[club]["chances"] += 1
        self.opportunity = {"id": f"{self.match_id}:O{int(row['index']) + 1:02d}", "index": int(row["index"]), "kind": kind,
                            "attacking": club, "defending": self.clubs[1 - side], "minute": self.minute, "status": "LIVE",
                            "right": self.attacks_right(side),
                            "tactics": self._tactics(attack, defence),
                            "bodies": body_rows, "ball": asdict(ball), "carrier": carrier,
                            "actions": 0, "last": None, "opened_at": at, "assist_candidate": None, "result": None}
        self._event("CHANCE", club, self.minute, outcome=kind, reveal=at, extra={"label": KIND_LABEL.get(kind, kind)})
        self.revision += 1
        if self._human_controls(club):
            self._to_decision(at)
        else:
            self._replay(at)

    def _tactics(self, attack: TeamInput, defence: TeamInput) -> dict[str, object]:
        """The tactical contract the engine consumes (docs/v8/TATICA.md). V6/V7 read only the
        first three keys; V8 also uses roles, individual instructions, the attacking
        mentality and the cohesion (familiarity) of each side. A future Tactical Engine fills
        the same keys — no parallel tactical system."""
        out: dict[str, object] = {"style": attack.tactics.style, "def_mentality": defence.tactics.mentality, "def_pressure": defence.tactics.pressure}
        if self.engine != "v8":
            return out
        roles: dict[str, str] = {}
        for team in (attack, defence):
            lines: dict[float, int] = {}
            for p in team.starters:
                lines[p.slot_y] = lines.get(p.slot_y, 0) + 1
            for p in team.starters:
                roles[p.id] = slot_role(p.slot_position, p.slot_x, lines[p.slot_y]) if p.slot_position in ("DF",) else p.slot_position
        out.update({"att_mentality": attack.tactics.mentality, "att_pressure": attack.tactics.pressure, "def_style": defence.tactics.style,
                    "att_cohesion": round(attack.cohesion, 3), "def_cohesion": round(defence.cohesion, 3), "roles": roles,
                    "instructions": {**dict(defence.instructions), **dict(attack.instructions)}})
        return out

    def _decision_seconds_for(self, club: str) -> float | None:
        rival = self.clubs[1 - self.side_of(club)]
        if self.free_vs_bots and rival not in self.humans:
            return None
        return float(self.decision_seconds)

    def _to_decision(self, at: float) -> None:
        club = str(self.opportunity["attacking"])
        if self.limit_reached:
            self._auto(at, "TIME_LIMIT")    # past the limit: the AI concludes the move (both teams alike)
            return
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
            choice = self._choose(opp, bodies, ball, rng)
            sequence.append(self._resolve(choice, "AI", at))
        total = sum(float(step["duration"]) for step in sequence)
        gap = 0.25 if self.engine in ("v7", "v8") else 0.6    # V7 replays flow (no long freeze between actions)
        self.state, self.state_until = "REPLAY", at + total + gap * len(sequence)
        opp["replay"] = sequence
        self.revision += 1

    def _auto(self, at: float, reason: str) -> None:
        opp = self.opportunity
        bodies, ball = self._restore_bodies(opp)
        rng = random.Random(f"{self.seed}:ai:{opp['index']}:{opp['actions']}")
        choice = self._choose(opp, bodies, ball, rng)
        self.deadline = None
        self._execute(choice, reason, at)

    def _choose(self, opp: dict[str, object], bodies: list[Body], ball: Ball, rng: random.Random) -> dict[str, object]:
        if self.engine in ("v7", "v8"):
            return football.choose(opp["bodies"], str(opp["carrier"]), HL_PITCH[self.mode], int(opp["actions"]), str(opp["kind"]), rng, self.difficulty, self.engine,
                                  opp.get("tactics"))
        return ai_action(bodies, ball, str(opp["carrier"]), self.mode, int(opp["actions"]), str(opp["kind"]), rng)

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
        cfg = HL_PITCH[self.mode]
        bodies, _ = self._restore_bodies(opp)
        carrier = next(b for b in bodies if b.id == opp["carrier"])
        x, y = self.to_world(x, y, bool(opp.get("right", True)))   # the gesture is on the real pitch
        tx, ty = x * cfg["length"], y * cfg["width"]
        if math.hypot(tx - carrier.x, ty - carrier.y) < 0.8:
            raise ValueError("Arraste mais longe para indicar a direção.")
        self._execute({"type": kind, "x": tx, "y": ty, "power": power}, "HUMAN", now)
        self.applied[action_id] = self.revision
        return {"status": "ACCEPTED", "revision": self.revision}

    def _execute(self, choice: dict[str, object], by: str, at: float) -> None:
        step = self._resolve(choice, by, at)
        self.opportunity["last"] = step
        self.state, self.state_until = "EXECUTING", at + float(step["duration"]) + EXECUTE_TAIL_SECONDS
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
        pitch = Pitch(bodies, ball, self.mode, rng, boost, opp.get("tactics"))
        kind = str(choice["type"])
        if self.engine in ("v7", "v8"):
            result, after_rows, after_ball = football.resolve(opp["bodies"], opp["ball"], str(opp["carrier"]), kind, float(choice["x"]), float(choice["y"]),
                                                              float(choice["power"]), HL_PITCH[self.mode], rng, boost,
                                                              {**dict(opp.get("tactics") or {}), "kind": opp["kind"]}, self.difficulty,
                                                              self.engine)
            bodies = [Body(**{k: v for k, v in row.items() if k in Body.__dataclass_fields__}) for row in after_rows]
            ball = Ball(after_ball["x"], after_ball["y"])
            carrier = next(b for b in bodies if b.id == opp["carrier"])
        else:
            result = pitch.execute(carrier, kind, float(choice["x"]), float(choice["y"]), float(choice["power"]), None)
        club, rival = str(opp["attacking"]), str(opp["defending"])
        stats, minute = self.stats[club], float(opp["minute"])
        duration = round(float(result.frames[-1][0]) + DT, 2) if self.engine in ("v7", "v8") and result.frames else round(len(result.frames) * DT, 2)
        reveal = at + duration
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
            shooter = by_id.get(str(result.shooter)) or carrier
            header = shooter is not carrier
            stats["shots"] += 1
            stats["xg"] = round(stats["xg"] + result.xg, 3)
            self.players[shooter.id]["shots"] += 1
            if result.on_target:
                stats["shots_on_target"] += 1
                self.players[shooter.id]["shots_on_target"] += 1
            # A header's assist is the cross itself; otherwise the last completed pass.
            assister = carrier if header else (by_id.get(str(opp.get("assist_candidate"))) if opp.get("assist_candidate") else None)
            if assister and result.outcome != "GOAL" and assister.id != shooter.id:
                self.players[assister.id]["key_passes"] += 1
            if result.outcome == "GOAL":
                self.score[self.side_of(club)] += 1
                self.players[shooter.id]["goals"] += 1
                if assister and assister.id != shooter.id:
                    self.players[assister.id]["assists"] += 1
            outcome = "GOAL" if result.outcome == "GOAL" else "ON_TARGET" if result.on_target else "OFF_TARGET"
            sx, sy = (shooter.x / pitch.L, shooter.y / pitch.W)
            self._event("SHOT", club, minute, shooter, outcome, xg=result.xg, x=sx, y=sy, reveal=reveal, extra={"header": header} if header else None)
            if result.outcome == "GOAL":
                self._event("GOAL", club, minute, shooter, "GOAL", other=assister if assister and assister.id != shooter.id else None,
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
        # Everything a client receives is on the real pitch (the conversion happens here, once).
        right = bool(opp.get("right", True))
        ax, ay = self.to_world(float(choice["x"]) / pitch.L, float(choice["y"]) / pitch.W, right)
        step = {"by": by, "type": kind, "aim": {"x": round(ax, 4), "y": round(ay, 4)},
                "power": round(float(choice["power"]), 3), "carrier": carrier.id, "outcome": result.outcome, "detail": result.detail,
                "frames": self._world_frames(result.frames, right), "duration": duration, "starts_at": at,
                "layout": self.engine if self.engine in ("v7", "v8") else "v6",
                "receiver": result.receiver, "shooter": result.shooter, "post": result.post, "cues": result.cues}
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
            rows2 = [asdict(b) for b in bodies2]
            if self.engine in ("v7", "v8"):
                rows2, carrier2 = football.opening(rows2, carrier2, "CORNER", HL_PITCH[self.mode], corner, self.engine)
            opp.update(bodies=rows2, ball=asdict(ball2), carrier=carrier2, kind="CORNER")
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
        L, W = HL_PITCH[self.mode]["length"], HL_PITCH[self.mode]["width"]
        if opp is not None:
            right = bool(opp.get("right", True))
            last = opp.get("last")
            opp_view = {"id": opp["id"], "kind": opp["kind"], "label": KIND_LABEL.get(str(opp["kind"]), opp["kind"]),
                        "attacking": opp["attacking"], "defending": opp["defending"], "minute": opp["minute"],
                        "status": opp["status"], "result": opp.get("result"), "actions": opp["actions"], "max_actions": MAX_ACTIONS,
                        "carrier": opp["carrier"],
                        "roster": [{"id": b["id"], "name": b["name"], "number": b["number"], "team": b["team"], "role": b["role"]} for b in opp["bodies"]],
                        "right": right,
                        "positions": [[round(v, 4) for v in self.to_world(b["x"] / L, b["y"] / W, right)] for b in opp["bodies"]],
                        "motion": [[round(football.world_facing(float(b.get("facing", 0.0)), right), 2),
                                    round(math.hypot(float(b.get("vx", 0.0)), float(b.get("vy", 0.0))), 2)] for b in opp["bodies"]],
                        "ball": [round(v, 4) for v in self.to_world(opp["ball"]["x"] / L, opp["ball"]["y"] / W, right)],
                        "last": last if self.state == "EXECUTING" or (self.state in ("DECISION", "OUTCOME") and last) else None,
                        "replay": opp.get("replay") if self.state in ("REPLAY", "OUTCOME") else None,
                        "opened_at": opp.get("opened_at")}
        controller = None
        if opp is not None:
            attacking = str(opp["attacking"])
            controller = "HUMAN" if self._human_controls(attacking) else "AI"
        cfg = HL_PITCH[self.mode]
        return {"match_id": self.match_id, "home": self.clubs[0], "away": self.clubs[1], "state": self.state, "revision": self.revision,
                "minute": round(self.clock_minute(now), 2), "clock_rate": self.clock_rate if self.state == "CLOCK" else 0,
                "duration": {"mode": self.duration_mode, "seconds": self.duration_seconds, "limit_at": self.limit_at, "limit_reached": self.limit_reached},
                "score": {"home": score[0], "away": score[1]}, "server_now": now, "deadline": self.deadline,
                "decision_seconds": self.decision_seconds, "state_until": self.state_until, "grace_until": self.grace_until,
                "you": club if club in self.clubs else None, "your_turn": bool(opp and self.state == "DECISION" and club == opp["attacking"] and self._human_controls(str(club))),
                "controller": controller, "ai_control": list(self.ai_control), "humans": self.humans,
                "connected": {c: self.connected(c, now) for c in self.humans},
                "opportunity": opp_view, "ruleset": self.ruleset,
                "pitch": {"length": cfg["length"], "width": cfg["width"], "goal": cfg["goal"], "goal_height": cfg["goal_height"], "box": cfg["box"],
                          "post": POST_RADIUS},
                "half": 2 if self.half_time_done else 1,
                "kits": self.kits or select_kits(self.clubs[0], self.clubs[1]),
                "attacks_right": {self.clubs[0]: self.attacks_right(0), self.clubs[1]: self.attacks_right(1)},
                "physics": football.physics_view(L / 105, PASS_ASSIST_ANGLE, self.engine) if self.engine in ("v7", "v8") else
                {"pass": PASS_SPEED, "loft": LOFT_SPEED, "loft_range": LOFT_RANGE, "shot": SHOT_SPEED, "carry": CARRY_RANGE, "decel": GROUND_DECEL,
                 "assist_angle": PASS_ASSIST_ANGLE},
                "engine": self.engine, "difficulty": self.difficulty,
                "events": [{k: v for k, v in e.items() if k != "revealed_at"} for e in shown[-30:]],
                "stats": self.stats}

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> HighlightMatch:
        return cls(**raw)
