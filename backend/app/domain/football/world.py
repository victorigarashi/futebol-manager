"""Football Game Core (V7): the physical world of one action — athletes, ball, pitch.

Units: metres, seconds, radians. Local frame of an opportunity: the attacking side
attacks towards x = L; x along the length, y across, z up. ``HighlightMatch`` turns it
into the real pitch exactly once (see highlights.py).

Fixed timestep: physics integrates at ``DT`` (40 Hz) regardless of any client; frames for
the renderers are recorded every ``FRAME_DT`` (10 Hz) with position, facing and an action
state per athlete, so animation never has to guess. Every number is documented in
docs/v7/MOTOR_V7.md.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# ---------------------------------------------------------------- time
DT = 0.025            # physics step (s): 40 Hz, deterministic, independent of rendering
FRAME_DT = 0.1        # frames sent to the clients (10 Hz; clients interpolate with splines)
BRAIN_DT = 0.2        # team AI re-plans 5x per second (stable intentions, no per-frame jitter)
MAX_ACTION_SECONDS = 7.0

# ---------------------------------------------------------------- ball
GRAVITY = 9.81
BALL_RADIUS = 0.11
ROLL_DECEL = 2.6      # m/s² rolling resistance on grass (constant part)
ROLL_DRAG = 0.010     # 1/m: velocity-squared part while rolling
AIR_DRAG = 0.0105     # 1/m: drag in flight (a 0.43 kg ball ~ 0.01 v² m/s²)
MAGNUS = 0.0036       # V8: lateral accel = MAGNUS * spin (rad/s) * speed, in flight (a curled shot bends ~1-2 m over 20 m)
SPIN_DECAY = 0.35     # 1/s
BOUNCE = 0.52         # vertical restitution on the grass
BOUNCE_FRICTION = 0.86  # horizontal speed kept on a bounce
PASS_SPEED = (6.5, 19.5)   # v0 = a + b * power (m/s)
SHOT_SPEED = (15.0, 19.0)
SHOT_LIFT = (0.6, 8.6)     # vz = a + b * max(0, power - 0.35)
LOFT_RANGE = (12.0, 46.0)  # first bounce at a + b * power metres (scaled by pitch)
LOFT_ANGLE = (0.62, 0.42)  # launch angle = a + b * (1 - power): short lofts are chips
CARRY_RANGE = (6.0, 18.0)  # requested run with the ball = a + b * power metres

# ---------------------------------------------------------------- athletes (derived from the six catalog attributes)
SPEED = (5.9, 3.1)          # top speed = a + b * pace/100 (m/s): 7.4 (pace 50) .. 8.7 (pace 90)
ACCEL = (4.6, 3.6)          # m/s² = a + b * acceleration/100 (acceleration = 0.7 pace + 0.3 dribbling)
BRAKE_FACTOR = 1.3          # braking is stronger than accelerating
TURN = (4.2, 4.6)           # max lateral (turning) accel m/s² = a + b * agility/100
MAX_ACCEL = 9.5             # no athlete exceeds this total acceleration (m/s²)
FACE_RATE = (5.5, 4.0)      # body rotation rad/s = a + b * agility/100
DRIBBLE_SPEED = (0.80, 0.15)  # fraction of top speed with the ball = a + b * dribbling/100
PERSONAL_SPACE = 0.75       # bodies never overlap closer than this (m)

# ---------------------------------------------------------------- action states sent per frame (renderers map them to poses)
ACT_NONE, ACT_KICK, ACT_RECEIVE, ACT_TACKLE, ACT_HEADER, ACT_STUMBLE = 0, 1, 2, 3, 4, 5
ACT_GK_SET, ACT_GK_DIVE, ACT_GK_HOLD, ACT_GK_DOWN, ACT_GK_RISE, ACT_DRIBBLE = 6, 7, 8, 9, 10, 11
ACT_GK_JUMP, ACT_GK_STEP = 12, 13


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def dist(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(ax - bx, ay - by)


def wrap(angle: float) -> float:
    return (angle + math.pi) % (2 * math.pi) - math.pi


@dataclass
class Athlete:
    """One player: physical state + the attributes that drive it + action state."""
    id: str
    name: str
    number: int
    team: str            # "A" attacking, "D" defending (within the opportunity)
    role: str            # GK, DF, MF, ST
    x: float
    y: float
    pace: float
    passing: float
    shooting: float
    dribbling: float
    defending: float
    physical: float
    keeping: float
    ax: float = 0.0      # tactical anchor of this opportunity
    ay: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    facing: float = 0.0
    act: int = ACT_NONE
    act_until: float = 0.0
    slow_until: float = 0.0     # beaten / getting up: reduced acceleration until then
    tx: float | None = None     # current locomotion target (kept between brain ticks)
    ty: float | None = None
    intensity: float = 0.8
    look: tuple[float, float] | None = None

    # Attributes the catalog does not have are DERIVED (documented, never invented values):
    @property
    def acceleration(self) -> float:
        return 0.7 * self.pace + 0.3 * self.dribbling

    @property
    def agility(self) -> float:
        return 0.55 * self.dribbling + 0.45 * self.pace

    @property
    def balance(self) -> float:
        return 0.6 * self.physical + 0.4 * self.dribbling

    @property
    def top_speed(self) -> float:
        return SPEED[0] + SPEED[1] * self.pace / 100

    @property
    def accel(self) -> float:
        return ACCEL[0] + ACCEL[1] * self.acceleration / 100

    @property
    def speed(self) -> float:
        return math.hypot(self.vx, self.vy)

    def time_to(self, px: float, py: float, reaction: float = 0.0) -> float:
        """Rough arrival time at a point from the current velocity (accelerating to top speed)."""
        d = dist(self.x, self.y, px, py)
        if d < 1e-6:
            return reaction
        ux, uy = (px - self.x) / d, (py - self.y) / d
        v0 = max(0.0, self.vx * ux + self.vy * uy)
        top, a = self.top_speed, self.accel
        t_acc = max(0.0, (top - v0) / a)
        d_acc = v0 * t_acc + 0.5 * a * t_acc * t_acc
        turn = 0.25 * (1 - (self.vx * ux + self.vy * uy) / max(0.5, self.speed)) if self.speed > 1 else 0.0
        if d_acc >= d:
            t = (-v0 + math.sqrt(v0 * v0 + 2 * a * d)) / a
        else:
            t = t_acc + (d - d_acc) / top
        return reaction + t + turn


def move(body: Athlete, now: float, dt: float = DT, top: float | None = None, accel: float | None = None) -> None:
    """Locomotion toward body.tx/ty: vector acceleration, braking and turning limited by the
    athlete's attributes, an 'arrive' profile that stops ON the target, and the body
    rotating at a finite rate. Never an instantaneous stop, start or turn."""
    slow = 0.35 if now < body.slow_until else 1.0
    speed = body.speed
    if body.tx is None:
        dvx, dvy = -body.vx, -body.vy
    else:
        dx, dy = body.tx - body.x, body.ty - body.y
        d = math.hypot(dx, dy)
        cap = (top if top is not None else body.top_speed) * body.intensity
        brake = (accel if accel is not None else body.accel) * BRAKE_FACTOR
        want = min(cap, math.sqrt(2 * brake * max(0.0, d - 0.15))) if d > 0.15 else 0.0
        dvx, dvy = (dx / d * want - body.vx, dy / d * want - body.vy) if d > 1e-6 else (-body.vx, -body.vy)
    accel = (accel if accel is not None else body.accel) * slow
    if speed > 1.0:
        ux, uy = body.vx / speed, body.vy / speed
        along = dvx * ux + dvy * uy
        lat = -dvx * uy + dvy * ux
        a_along = clamp(along / dt, -accel * BRAKE_FACTOR, accel)
        lat_cap = (TURN[0] + TURN[1] * body.agility / 100) * slow
        a_lat = clamp(lat / dt, -lat_cap, lat_cap)
        ax, ay = ux * a_along - uy * a_lat, uy * a_along + ux * a_lat
        total = math.hypot(ax, ay)
        if total > MAX_ACCEL * slow:
            ax, ay = ax / total * MAX_ACCEL * slow, ay / total * MAX_ACCEL * slow
    else:
        mag = math.hypot(dvx, dvy) / dt
        k = min(1.0, accel / mag) if mag > 1e-9 else 0.0
        ax, ay = dvx / dt * k, dvy / dt * k
    body.vx += ax * dt
    body.vy += ay * dt
    body.x += body.vx * dt
    body.y += body.vy * dt
    turn_towards(body, dt)


def turn_towards(body: Athlete, dt: float = DT) -> None:
    speed = body.speed
    if body.look is not None and (speed < 2.2 or body.act in (ACT_KICK, ACT_RECEIVE, ACT_GK_SET, ACT_GK_STEP)):
        want = math.atan2(body.look[1] - body.y, body.look[0] - body.x)
    elif speed > 0.6:
        want = math.atan2(body.vy, body.vx)
    else:
        return
    rate = (FACE_RATE[0] + FACE_RATE[1] * body.agility / 100) * dt
    body.facing = wrap(body.facing + clamp(wrap(want - body.facing), -rate, rate))


def separate(bodies: list[Athlete]) -> None:
    """Personal space: two bodies never overlap (soft push, the stronger player moves less)."""
    n = len(bodies)
    for i in range(n):
        a = bodies[i]
        for j in range(i + 1, n):
            b = bodies[j]
            dx, dy = b.x - a.x, b.y - a.y
            d2 = dx * dx + dy * dy
            if d2 >= PERSONAL_SPACE * PERSONAL_SPACE or d2 < 1e-12:
                continue
            d = math.sqrt(d2)
            nx, ny = dx / d, dy / d
            push = min(PERSONAL_SPACE - d, 0.05)      # a shoulder, never a teleport
            wa = clamp(0.5 + (b.physical - a.physical) / 400, 0.25, 0.75)
            a.x -= nx * push * wa
            a.y -= ny * push * wa
            b.x += nx * push * (1 - wa)
            b.y += ny * push * (1 - wa)
            # Bodies that run into each other lose the closing speed (they bump, they do not pass through).
            closing = (b.vx - a.vx) * nx + (b.vy - a.vy) * ny
            if closing < 0:
                a.vx += nx * closing * wa
                a.vy += ny * closing * wa
                b.vx -= nx * closing * (1 - wa)
                b.vy -= ny * closing * (1 - wa)


@dataclass
class BallState:
    x: float
    y: float
    z: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    vz: float = 0.0
    owner: str | None = None     # controlled at the feet of this athlete (dribble / settle)
    spin: float = 0.0            # V8 side spin (rad/s, + bends to the left of the motion)
    last_touch: str = "A"        # team of the last touch (corner vs goal kick)

    @property
    def ground_speed(self) -> float:
        return math.hypot(self.vx, self.vy)

    @property
    def airborne(self) -> bool:
        return self.z > 0.0 or self.vz > 0.05


def ball_step(b: BallState, dt: float = DT) -> None:
    """Free ball: rolling resistance + drag on the grass, gravity + drag in the air, bounces."""
    speed = math.hypot(b.vx, b.vy)
    if b.airborne:
        total = math.sqrt(speed * speed + b.vz * b.vz)
        drag = AIR_DRAG * total
        b.vx -= b.vx * drag * dt
        b.vy -= b.vy * drag * dt
        if b.spin and speed > 1.0:
            a = MAGNUS * b.spin * speed
            vx, vy = b.vx, b.vy
            b.vx = vx - vy / speed * a * dt
            b.vy = vy + vx / speed * a * dt
            b.spin *= max(0.0, 1 - SPIN_DECAY * dt)
        b.vz -= (GRAVITY + b.vz * drag) * dt
        b.x += b.vx * dt
        b.y += b.vy * dt
        b.z += b.vz * dt
        if b.z <= 0.0:
            b.z = 0.0
            if b.vz < -1.2:
                b.vz = -b.vz * BOUNCE
                b.vx *= BOUNCE_FRICTION
                b.vy *= BOUNCE_FRICTION
                b.spin *= 0.4
            else:
                b.vz = 0.0
        return
    if speed > 0:
        decel = (ROLL_DECEL + ROLL_DRAG * speed * speed) * dt
        k = max(0.0, speed - decel) / speed
        b.vx *= k
        b.vy *= k
    b.x += b.vx * dt
    b.y += b.vy * dt


def predict_ball(b: BallState, seconds: float, step: float = 0.05) -> list[tuple[float, float, float, float]]:
    """Ball path (t, x, y, z) over the next seconds with the real physics (what any player can
    'read' once the ball has been struck — never the outcome of a future decision)."""
    probe = BallState(b.x, b.y, b.z, b.vx, b.vy, b.vz, spin=b.spin)
    out, t = [], 0.0
    while t < seconds - 1e-9:
        for _ in range(int(round(step / DT))):
            ball_step(probe)
        t += step
        out.append((t, probe.x, probe.y, probe.z))
    return out


def solve_loft(distance: float, angle: float) -> float:
    """Launch speed so the first bounce lands at `distance` with this angle (drag included)."""
    lo, hi = 3.0, 45.0
    for _ in range(18):
        mid = (lo + hi) / 2
        b = BallState(0.0, 0.0, 0.0, mid * math.cos(angle), 0.0, mid * math.sin(angle))
        for _ in range(400):
            prev_vz = b.vz
            ball_step(b)
            if b.z == 0.0 and prev_vz < 0:
                break
        if b.x < distance:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def pass_reach(v0: float) -> float:
    """Distance a ground pass rolls before stopping (same integration as ``ball_step``)."""
    b = BallState(0.0, 0.0, 0.0, v0, 0.0, 0.0)
    for _ in range(2000):
        ball_step(b)
        if b.vx < 0.05:
            break
    return b.x


@dataclass
class Cue:
    t: float
    kind: str
    id: str | None
    extra: dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {"t": round(self.t, 2), "kind": self.kind, "id": self.id, **self.extra}
