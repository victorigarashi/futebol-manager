"""Goalkeeper Engine (V7): a specialised agent with a body.

States: POSITIONING -> SET (shooter in range) -> [shot struck] REACTION (no knowledge of the
shot before it is struck) -> STEP (shuffle) | DIVE (committed, physical lateral launch)
| JUMP (high ball) -> CATCH / PARRY / TOUCH (contact by sweeping the ball's real path
against the hands) -> DOWN -> RISE -> POSITIONING. Crosses: CLAIM when the predicted
drop is in his area and he gets there first.

The save is decided by geometry first (did the hands meet the ball?) and only then by
handling (catch, parry or a touch that is not enough). A ball out of physical reach is
never saved.
"""

from __future__ import annotations

import math
import random

from app.domain.football.world import (
    ACT_GK_DIVE,
    ACT_GK_DOWN,
    ACT_GK_HOLD,
    ACT_GK_JUMP,
    ACT_GK_RISE,
    ACT_GK_SET,
    ACT_GK_STEP,
    ACT_NONE,
    DT,
    Athlete,
    BallState,
    Cue,
    clamp,
    dist,
    move,
    predict_ball,
    wrap,
)

REACTION = (0.30, 0.16)          # s: a - b * keeping/100 (+0.07 if screened)
SHUFFLE_SPEED = (3.6, 1.4)       # lateral shuffle top speed m/s
SHUFFLE_ACCEL = 11.0             # keepers are explosive over 1-2 m
DIVE_SPEED = (3.4, 2.6)          # lateral launch m/s = a + b * keeping/100
DIVE_TIME = 0.55                 # in the air, then down
DOWN_TIME = (0.75, 0.25)         # on the ground: a - b * keeping/100
RISE_TIME = 0.45
ARM_STANDING = (0.62, 0.25)      # lateral reach on his feet (m)
ARM_DIVING = (0.95, 0.35)        # extra reach beyond the body when fully stretched
HAND_RADIUS = 0.24
TOP_REACH = (2.15, 0.3)          # standing jump reach (m): a + b * keeping/100
CLAIM_REACH = 2.55


def _seg_point(px, py, pz, ax, ay, az, bx, by, bz):
    """Distance from point P to segment AB and the parameter u along AB (3D)."""
    abx, aby, abz = bx - ax, by - ay, bz - az
    l2 = abx * abx + aby * aby + abz * abz
    u = 0.0 if l2 < 1e-12 else clamp(((px - ax) * abx + (py - ay) * aby + (pz - az) * abz) / l2, 0.0, 1.0)
    cx, cy, cz = ax + abx * u, ay + aby * u, az + abz * u
    return math.sqrt((px - cx) ** 2 + (py - cy) ** 2 + (pz - cz) ** 2), u


def seg_seg(p0, p1, q0, q1, samples: int = 6) -> tuple[float, float, float]:
    """Approximate minimum distance between the ball's path P0->P1 and the hands segment
    Q0->Q1 (swept test: no tunnelling at 34 m/s). Returns (distance, u along hands, s along path)."""
    best = (9e9, 0.0, 0.0)
    for k in range(samples + 1):
        s = k / samples
        px, py, pz = (p0[i] + (p1[i] - p0[i]) * s for i in range(3))
        d, u = _seg_point(px, py, pz, *q0, *q1)
        if d < best[0]:
            best = (d, u, s)
    return best


class Keeper:
    def __init__(self, body: Athlete, L: float, W: float, goal: float, goal_h: float, s: float, rng: random.Random,
                 reaction_extra: float = 0.0) -> None:
        self.b, self.L, self.W, self.goal, self.goal_h, self.s, self.rng = body, L, W, goal, goal_h, s, rng
        self.k = body.keeping / 100
        self.state = "POSITIONING"
        self.until = 0.0
        self.react_at: float | None = None
        self.dive_dir = 0
        self.dive_level = "mid"
        self.dive_t0 = 0.0
        self.reaction_extra = reaction_extra
        self.done_contact = False
        self.claiming = False
        self.cues: list[Cue] = []

    # ------------------------------------------------------------ where the hands are
    def hands(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        b, k = self.b, self.k
        if self.state == "DIVE":
            # The body flies sideways: from the hip to the hands, at the chosen height.
            progress = clamp((self.t - self.dive_t0) / 0.32, 0.25, 1.0)
            reach = (ARM_STANDING[0] + ARM_DIVING[0] * progress + (ARM_STANDING[1] + ARM_DIVING[1]) * k)
            z = {"low": 0.25, "mid": 0.85, "high": 1.75 + 0.25 * k}[self.dive_level]
            hip = (b.x, b.y, max(0.3, z * 0.6))
            hand = (b.x + 0.15, b.y + self.dive_dir * reach, z)
            return hip, hand
        if self.state == "JUMP":
            top = TOP_REACH[0] + TOP_REACH[1] * k
            return (b.x, b.y - 0.45, top - 0.35), (b.x, b.y + 0.45, top)
        if self.state in ("DOWN", "RISE"):
            return (b.x, b.y - 0.6, 0.15), (b.x, b.y + 0.6, 0.2)
        arm = ARM_STANDING[0] + ARM_STANDING[1] * k
        # Standing: hands cover from the grass to above the head across the body.
        return (b.x, b.y - arm, 0.25), (b.x, b.y + arm, 1.75)

    # ------------------------------------------------------------ behaviour
    def update(self, t: float, ball: BallState, shot_live: bool, shot_t0: float, screened: bool, owner: Athlete | None) -> None:
        self.t = t
        b = self.b
        b.look = (ball.x, ball.y)
        if self.state == "HOLD":
            b.tx, b.ty = b.x, b.y
            move(b, t)
            return
        if self.state == "DIVE":
            # Ballistic lateral launch, then down on the grass (no steering in the air).
            b.vy -= math.copysign(min(abs(b.vy), 4.5 * DT), b.vy)
            b.vx *= 0.96
            b.x += b.vx * DT
            b.y += b.vy * DT
            if t >= self.until:
                self.state, self.until = "DOWN", t + DOWN_TIME[0] - DOWN_TIME[1] * self.k
                b.act = ACT_GK_DOWN
            return
        if self.state == "DOWN":
            b.vx *= 0.6
            b.vy *= 0.6
            b.x += b.vx * DT
            b.y += b.vy * DT
            if t >= self.until:
                self.state, self.until = "RISE", t + RISE_TIME
                b.act = ACT_GK_RISE
            return
        if self.state == "RISE":
            b.vx = b.vy = 0.0
            if t >= self.until:
                self.state = "POSITIONING"
                b.act = ACT_NONE
            return
        if self.state == "JUMP" and t >= self.until:
            self.state = "POSITIONING"
            b.act = ACT_NONE
        if shot_live and ball.vx > 0.5:
            if self.react_at is None:
                self.react_at = shot_t0 + REACTION[0] - REACTION[1] * self.k + (0.07 if screened else 0.0) + self.reaction_extra
            if t < self.react_at:
                # Still reading the shot: he keeps his inertia, no anticipation.
                b.tx, b.ty = b.x + b.vx * 0.1, b.y + b.vy * 0.1
                self._shuffle(t)
                return
            self._react(t, ball)
            return
        self.react_at = None
        self._position(t, ball, owner)

    def _react(self, t: float, ball: BallState) -> None:
        b = self.b
        path = predict_ball(ball, 1.6, 0.025)
        cross = next(((pt, px, py, pz) for pt, px, py, pz in path if px >= b.x - 0.05), None)
        if cross is None:
            b.tx, b.ty = b.x, clamp(ball.y, self.W / 2 - self.goal / 2, self.W / 2 + self.goal / 2)
            self._shuffle(t)
            return
        tc, _, yc, zc = cross
        need = yc - b.y
        arm = ARM_STANDING[0] + ARM_STANDING[1] * self.k
        top = TOP_REACH[0] + TOP_REACH[1] * self.k
        shuffle = (SHUFFLE_SPEED[0] + SHUFFLE_SPEED[1] * self.k) * max(0.0, tc - 0.12) * 0.75
        if abs(need) <= arm + shuffle and zc <= 1.85:
            b.tx, b.ty = b.x, yc - math.copysign(min(abs(need), arm * 0.4), need)
            b.act = ACT_GK_STEP
            self._shuffle(t)
            return
        if abs(need) <= arm + 0.5 and zc > 1.85 and zc < top + 0.6:
            self.state, self.until = "JUMP", t + 0.6
            b.act = ACT_GK_JUMP
            self.cues.append(Cue(t, "DIVE", b.id, {"dy": 0.0, "level": "high"}))
            return
        # Too far to shuffle: commit to a dive (once), towards where the ball will cross.
        self.dive_dir = 1 if need > 0 else -1
        self.dive_level = "low" if zc < 0.55 else "high" if zc > 1.4 else "mid"
        speed = DIVE_SPEED[0] + DIVE_SPEED[1] * self.k
        b.vy = self.dive_dir * speed + b.vy * 0.4
        b.vx = 0.6
        b.facing = 0.0 + math.pi   # facing the play (towards x = 0)
        self.state, self.until, self.dive_t0 = "DIVE", t + DIVE_TIME, t
        b.act = ACT_GK_DIVE
        self.cues.append(Cue(t, "DIVE", b.id, {"dy": round(self.dive_dir * 0.05, 3), "level": self.dive_level}))

    def _shuffle(self, t: float) -> None:
        b = self.b
        b.intensity = 1.0
        move(b, t, top=SHUFFLE_SPEED[0] + SHUFFLE_SPEED[1] * self.k, accel=SHUFFLE_ACCEL)
        b.facing = wrap(math.pi)  # keeps facing the play while side-stepping

    def _position(self, t: float, ball: BallState, owner: Athlete | None) -> None:
        """Angle play: on the line from the centre of the goal to the ball, a little off the
        line as the ball gets closer, never abandoning the goal."""
        b, L, W, s = self.b, self.L, self.W, self.s
        gx, gy = L, W / 2
        bx, by = ball.x, ball.y
        # Cross / high ball dropping into his area: come and claim it if he gets there first.
        if ball.z > 0.8 and ball.vz < 4 and ball.vx > 0:
            land = next(((pt, px, py) for pt, px, py, pz in predict_ball(ball, 2.0, 0.05) if pz < CLAIM_REACH and pt > 0.15), None)
            if land and land[1] > L - 6.5 * s and abs(land[2] - gy) < 10 * s ** 0.8:
                if b.time_to(land[1], land[2]) < land[0] + 0.05:
                    self.claiming = True
                    b.tx, b.ty, b.intensity = land[1], land[2], 1.0
                    move(b, t)
                    return
        self.claiming = False
        d = dist(bx, by, gx, gy)
        depth = clamp(0.6 + d * 0.055, 0.6, 3.6) * s ** 0.5
        if owner is not None and d < 14 * s:
            depth = clamp(depth + 0.8, 0.6, 5.5 * s ** 0.5)   # closing down a close-range shooter
        ux, uy = (bx - gx) / max(d, 1e-6), (by - gy) / max(d, 1e-6)
        tx, ty = gx + ux * depth, gy + uy * depth
        ty = clamp(ty, gy - self.goal / 2 - 0.3, gy + self.goal / 2 + 0.3)
        tx = clamp(tx, L - 6 * s, L - 0.4)
        b.tx, b.ty = tx, ty
        threatened = owner is not None and owner.team == "A" and d < 30 * s and abs(wrap(owner.facing - math.atan2(gy - owner.y, gx - owner.x))) < 1.1
        if threatened and dist(b.x, b.y, tx, ty) < 0.6:
            b.act = ACT_GK_SET        # feet set, weight forward: ready for the shot
            b.tx, b.ty = b.x, b.y
        elif b.act == ACT_GK_SET:
            b.act = ACT_NONE
        b.intensity = 0.9
        if abs(ty - b.y) > abs(tx - b.x):
            self._shuffle(t)
        else:
            move(b, t)

    # ------------------------------------------------------------ contact
    def contact(self, t: float, p0: tuple[float, float, float], ball: BallState) -> str | None:
        """Sweep the ball's step against the hands. Returns HOLD / PARRY / TOUCH or None."""
        if self.done_contact or self.state in ("DOWN", "RISE", "HOLD"):
            return None
        p1 = (ball.x, ball.y, ball.z)
        if self.state == "DIVE":
            q0, q1 = self.hands()
            d, u, s = seg_seg(p0, p1, q0, q1)
            if d > HAND_RADIUS + 0.11:
                return None
        else:
            # On his feet (positioning, set, stepping, jumping): he covers a frontal window,
            # arm's width to each side, from the grass to his (jumping) reach.
            plane = self.b.x - 0.15
            if not (p0[0] <= plane <= p1[0] or p1[0] <= plane <= p0[0]):
                return None
            s = (plane - p0[0]) / (p1[0] - p0[0]) if p1[0] != p0[0] else 0.0
            yc, zc = p0[1] + (p1[1] - p0[1]) * s, p0[2] + (p1[2] - p0[2]) * s
            arm = ARM_STANDING[0] + ARM_STANDING[1] * self.k + HAND_RADIUS
            top = (TOP_REACH[0] + TOP_REACH[1] * self.k) if self.state == "JUMP" else 1.95 + 0.15 * self.k
            if self.state in ("DOWN", "RISE"):
                arm, top = 0.9, 0.45
            dy = yc - self.b.y
            if abs(dy) > arm or zc > top + 0.11:
                return None
            u = 0.5 + dy / arm * 0.5
        self.done_contact = True
        speed = math.sqrt(ball.vx ** 2 + ball.vy ** 2 + ball.vz ** 2)
        # Central = close to the body / both hands behind the ball; tip = fingertips.
        central = 1 - abs(u - 0.5) * 2 if self.state not in ("DIVE",) else 1 - u
        tip = self.state == "DIVE" and u > 0.8
        catch_p = clamp(0.12 + 0.55 * self.k + 0.35 * central - max(0.0, speed - 13) * 0.03, 0.02, 0.9) * (0.25 if tip else 1.0)
        keep_out = clamp(0.55 + 0.38 * self.k + 0.25 * central - max(0.0, speed - 24) * 0.035, 0.3, 0.98) * (0.7 if tip else 1.0)
        roll = self.rng.random()
        hx = p0[0] + (p1[0] - p0[0]) * s
        hy = p0[1] + (p1[1] - p0[1]) * s
        hz = p0[2] + (p1[2] - p0[2]) * s
        ball.x, ball.y, ball.z = min(hx, self.L - 0.25), hy, max(0.0, hz)
        if roll < catch_p:
            ball.vx = ball.vy = ball.vz = 0.0
            ball.owner = self.b.id
            self.state = "HOLD" if self.state != "DIVE" else self.state
            self.b.act = ACT_GK_HOLD
            self.cues.append(Cue(t, "SAVE", self.b.id, {"hold": True, "dy": round(self.dive_dir * 0.05, 3), "high": hz > 1.4}))
            return "HOLD"
        if roll < keep_out:
            # Parried: away from goal, towards the side of the dive (or over / round the post).
            out = self.dive_dir or (1 if hy > self.W / 2 else -1)
            ang = math.pi - out * self.rng.uniform(0.35, 1.25)
            sp = speed * self.rng.uniform(0.22, 0.42)
            if tip and self.rng.random() < 0.55:
                ang = out * self.rng.uniform(0.25, 0.7)   # tipped round the post (it carries on, wide)
            ball.vx, ball.vy = math.cos(ang) * sp, math.sin(ang) * sp
            ball.vz = 2.2 + self.rng.uniform(0, 2.0) if hz > 1.3 else self.rng.uniform(0.3, 1.5)
            ball.last_touch = "D"
            self.cues.append(Cue(t, "SAVE", self.b.id, {"hold": False, "dy": round(out * 0.05, 3), "high": hz > 1.4}))
            return "PARRY"
        # A touch that is not enough: slower and deflected, the ball carries on.
        ang = math.atan2(ball.vy, ball.vx) + self.rng.uniform(-0.18, 0.18)
        sp = math.hypot(ball.vx, ball.vy) * self.rng.uniform(0.6, 0.85)
        ball.vx, ball.vy = math.cos(ang) * sp, math.sin(ang) * sp
        ball.last_touch = "D"
        self.cues.append(Cue(t, "DIVE", self.b.id, {"dy": round(self.dive_dir * 0.05, 3), "touched": True}))
        return "TOUCH"

    def claim_contact(self, t: float, ball: BallState) -> str | None:
        """Coming for a cross: catch or punch when the ball reaches his hands."""
        if not self.claiming or self.done_contact:
            return None
        b = self.b
        if dist(b.x, b.y, ball.x, ball.y) > 0.9 or ball.z > CLAIM_REACH + 0.25 * self.k:
            return None
        self.done_contact = True
        if self.rng.random() < 0.55 + 0.35 * self.k:
            ball.vx = ball.vy = ball.vz = 0.0
            ball.owner = b.id
            self.state = "HOLD"
            b.act = ACT_GK_HOLD
            self.cues.append(Cue(t, "CLAIM", b.id))
            return "HOLD"
        ang = math.pi + self.rng.uniform(-0.8, 0.8)
        ball.vx, ball.vy, ball.vz = math.cos(ang) * 11, math.sin(ang) * 11, 4.0
        ball.last_touch = "D"
        self.cues.append(Cue(t, "SAVE", b.id, {"hold": False, "punch": True, "dy": 0.0, "high": True}))
        return "PARRY"
