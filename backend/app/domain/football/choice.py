"""AI decisions for the ball carrier (bots, timeouts, disconnections) — V7.

Utility AI over the real situation: every option is scored with what a player can see
(positions, velocities, time for each defender to reach the passing lane), never with a
future random draw or a human gesture. Difficulty changes the quality of the choice
(noise, risk-taking), never the attributes.
"""

from __future__ import annotations

import math
import random

from app.domain.football.world import LOFT_RANGE, PASS_SPEED, Athlete, clamp, dist, pass_reach

NOISE = {"EASY": 0.9, "NORMAL": 0.45, "HARD": 0.2}
MAX_ACTIONS = 8
_REACH_TABLE: list[tuple[float, float]] = []


def power_for_pass(distance: float) -> float:
    """Inverse of the rolling physics: the power whose pass stops `distance` metres away."""
    if not _REACH_TABLE:
        for i in range(0, 101):
            p = i / 100
            _REACH_TABLE.append((p, pass_reach(PASS_SPEED[0] + PASS_SPEED[1] * p)))
    for p, reach in _REACH_TABLE:
        if reach >= distance:
            return p
    return 1.0


def xg_of(x: float, y: float, L: float, W: float, goal: float) -> float:
    d = dist(x, y, L, W / 2)
    angle = abs(math.atan2(goal * (L - x), (L - x) ** 2 + (y - W / 2) ** 2 - (goal / 2) ** 2))
    return clamp(0.9 * angle * math.exp(-d * (105 / L) / 22), 0.01, 0.85)


def lane_risk(carrier: Athlete, tx: float, ty: float, defenders: list[Athlete], ball_speed: float) -> float:
    """How likely a defender gets to the lane before the ball: time margin along the path."""
    d = dist(carrier.x, carrier.y, tx, ty) or 1.0
    risk = 0.0
    # Somebody already standing in the lane (a presser in front of the ball) blocks it.
    lx, ly = tx - carrier.x, ty - carrier.y
    for x in defenders:
        u = clamp(((x.x - carrier.x) * lx + (x.y - carrier.y) * ly) / (d * d), 0.0, 1.0)
        gap = dist(x.x, x.y, carrier.x + lx * u, carrier.y + ly * u)
        if gap < 1.1:
            risk = max(risk, (1.1 - gap) * 1.5)
    for k in range(1, 9):
        u = k / 8
        px, py = carrier.x + (tx - carrier.x) * u, carrier.y + (ty - carrier.y) * u
        t_ball = d * u / max(4.0, ball_speed * (1 - 0.25 * u))
        for x in defenders:
            margin = x.time_to(px, py, 0.15) - t_ball
            if margin < 0.25:
                risk = max(risk, (0.25 - margin) * 1.6)
    return risk


def ai_choice(bodies: list[Athlete], carrier_id: str, cfg: dict[str, float], actions_done: int, kind: str, rng: random.Random,
              difficulty: str = "NORMAL") -> dict[str, object]:
    L, W, goal = cfg["length"], cfg["width"], cfg["goal"]
    s = L / 105
    noise = NOISE.get(difficulty, 0.45)
    carrier = next(b for b in bodies if b.id == carrier_id)
    defenders = [b for b in bodies if b.team == "D" and b.role != "GK"]
    keeper = next((b for b in bodies if b.team == "D" and b.role == "GK"), None)
    mates = [b for b in bodies if b.team == "A" and b.role != "GK" and b is not carrier]
    d_goal = dist(carrier.x, carrier.y, L, W / 2)
    angle_ok = abs(carrier.y - W / 2) < (L - carrier.x) * 1.3 + 4 * s
    must_shoot = actions_done >= MAX_ACTIONS - 1 or kind == "PENALTY"
    pressure = min((dist(carrier.x, carrier.y, d.x, d.y) for d in defenders), default=20.0)
    shot_value = 0.0
    if kind == "PENALTY" or (angle_ok and d_goal < 32 * s):
        xg = xg_of(carrier.x, carrier.y, L, W, goal)
        shot_value = 1.4 + 16 * xg + (0.5 if pressure > 2.5 else 0.0) - (0.5 if d_goal > 26 * s else 0.0)
    if kind == "PENALTY" or must_shoot and d_goal < 38 * s:
        shot_value = 99.0
    options: list[tuple[float, dict[str, object]]] = []
    if shot_value > 0:
        side = 1 if keeper is None or keeper.y <= W / 2 else -1
        if rng.random() < 0.3:
            side = -side
        ty = W / 2 + side * (goal / 2) * rng.uniform(0.5, 0.88)
        power = clamp(0.6 + rng.uniform(0, 0.25) + (0.1 if d_goal > 20 * s else 0.0), 0, 1)
        options.append((shot_value + rng.gauss(0, noise * 0.3), {"type": "SHOT", "x": L, "y": ty, "power": round(power, 3)}))
    for m in mates:
        d = dist(m.x, m.y, carrier.x, carrier.y)
        if d < 4 * s or d > 46 * s:
            continue
        lead = min(1.2, d / 15)
        tx, ty = m.x + m.vx * lead, m.y + m.vy * lead
        free = min((dist(tx, ty, x.x, x.y) for x in defenders), default=10.0)
        gain = (tx - carrier.x) / s
        in_box = tx > L - 16.5 * s and abs(ty - W / 2) < 12 * s
        wide_delivery = carrier.x > L - 26 * s and min(carrier.y, W - carrier.y) < 15 * s
        lofted = wide_delivery and in_box or d > 32 * s
        speed = 18.0 if lofted else PASS_SPEED[0] + PASS_SPEED[1] * 0.6
        risk = lane_risk(carrier, tx, ty, defenders, speed) * (0.35 if lofted else 1.0)
        value = gain * 0.075 + min(free, 7) * 0.25 - risk * 2.0 + (1.0 if in_box else 0.0) + rng.gauss(0, noise * 0.35)
        if lofted:
            flight = dist(carrier.x, carrier.y, tx, ty) / s
            power = clamp((flight - LOFT_RANGE[0]) / LOFT_RANGE[1], 0.0, 1.0)
            options.append((value - 0.15, {"type": "LOFT", "x": tx, "y": ty, "power": round(power, 3)}))
        else:
            # A firm pass: it would roll on well past him (arrives at ~6-9 m/s, harder to cut out).
            power = power_for_pass(dist(carrier.x, carrier.y, tx, ty) * 1.45 + 5)
            options.append((value, {"type": "PASS", "x": tx, "y": ty, "power": round(power, 3)}))
        # Through ball: into the space in front of a runner (not to his feet).
        if m.role == "ST" or m.vx > 3:
            line = max((x.x for x in defenders), default=L - 12 * s)
            sx, sy = min(L - 7 * s, max(m.x, line) + 7 * s), m.y + m.vy * 0.4
            space = min((dist(sx, sy, x.x, x.y) for x in defenders), default=10.0)
            if space > 4 * s ** 0.5 and sx > carrier.x:
                risk2 = lane_risk(carrier, sx, sy, defenders, 16.0)
                v2 = (sx - carrier.x) / s * 0.09 + min(space, 8) * 0.25 - risk2 * 2.0 + 0.4 + rng.gauss(0, noise * 0.4)
                p2 = power_for_pass(dist(carrier.x, carrier.y, sx, sy) + 3.0)
                options.append((v2, {"type": "PASS", "x": sx, "y": sy, "power": round(p2, 3)}))
    # Carry / dribble: space ahead, or a 1v1 a good dribbler can attack.
    ahead = [x for x in defenders if x.x > carrier.x - 1 and abs(x.y - carrier.y) < 9 * s]
    space_ahead = min((dist(carrier.x, carrier.y, x.x, x.y) for x in ahead), default=30.0)
    for ang in (0.0, 0.45, -0.45):
        tx, ty = min(carrier.x + math.cos(ang) * 10 * s, L - 5 * s), clamp(carrier.y + math.sin(ang) * 10 * s, 3 * s, W - 3 * s)
        if dist(tx, ty, carrier.x, carrier.y) < 3 * s:
            continue
        free = min((dist(tx, ty, x.x, x.y) for x in defenders), default=20.0)
        value = min(space_ahead, 14) * 0.11 + min(free, 8) * 0.12 + (carrier.dribbling - 60) / 60 + rng.gauss(0, noise * 0.35)
        if space_ahead < 3:
            value -= 0.8
        options.append((value, {"type": "CARRY", "x": tx, "y": ty, "power": 0.45}))
    if not options:
        return {"type": "SHOT", "x": L, "y": W / 2, "power": 0.8}
    return max(options, key=lambda o: o[0])[1]
