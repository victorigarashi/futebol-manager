"""AI decisions for the ball carrier (bots, timeouts, disconnections) — V7.

Utility AI over the real situation: every option is scored with what a player can see
(positions, velocities, time for each defender to reach the passing lane), never with a
future random draw or a human gesture. Difficulty changes the quality of the choice
(noise, risk-taking), never the attributes.
"""

from __future__ import annotations

import math
import random
import statistics

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


def aim_shot(carrier: Athlete, defenders: list[Athlete], keeper: Athlete | None, L: float, W: float, goal: float, s: float, d_goal: float,
             rng: random.Random, noise: float) -> tuple[float, float, float]:
    """V8 shot placement: the point of the goal mouth that the blockers' bodies and the
    keeper's reach leave most open (what a finisher sees), not a fixed 'far corner'."""
    best, best_score = W / 2, -9.0
    for k in (-0.88, -0.7, -0.45, -0.2, 0.2, 0.45, 0.7, 0.88):
        ty = W / 2 + k * goal / 2
        lx, ly = L - carrier.x, ty - carrier.y
        l2 = lx * lx + ly * ly or 1.0
        block = 2.0
        for x in defenders:
            u = clamp(((x.x - carrier.x) * lx + (x.y - carrier.y) * ly) / l2, 0.0, 1.0)
            if u > 0.05:
                block = min(block, dist(x.x, x.y, carrier.x + lx * u, carrier.y + ly * u))
        gap = abs(ty - keeper.y) if keeper else goal / 2
        score = min(block, 1.5) * 1.2 + min(gap, 3.0) * 0.6 - abs(k) * 0.15 + rng.gauss(0, 0.25 * noise)
        if score > best_score:
            best, best_score = ty, score
    power = clamp((0.55 if d_goal < 14 * s else 0.72) + rng.uniform(0, 0.2), 0, 1)
    clear = -0.8 if best_score < 0.6 else 0.0   # every lane blocked: a shot is a poor option
    return best, power, clear


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
              difficulty: str = "NORMAL", profile: str = "v7", tactics: dict[str, object] | None = None) -> dict[str, object]:
    v8 = profile == "v8"
    t = tactics or {}
    style = str(t.get("style", "POSSESSION"))
    mentality = str(t.get("att_mentality", "BALANCED"))
    # V8: the attacking style and mentality shape the choice (no bonus to any outcome).
    risk_w = 2.0 if not v8 else {"POSSESSION": 2.6, "SHORT_BUILDUP": 2.8, "DIRECT": 1.6, "COUNTER": 1.7, "WIDE": 2.0}.get(style, 2.0)
    through_bonus = 0.0 if not v8 else {"DIRECT": 0.5, "COUNTER": 0.6}.get(style, 0.0)
    wide_bonus = 0.8 if v8 and style == "WIDE" else 0.0
    shot_bias = 0.0 if not v8 else {"ATTACKING": 0.3, "VERY_ATTACKING": 0.5, "DEFENSIVE": -0.2, "VERY_DEFENSIVE": -0.35}.get(mentality, 0.0)
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
        shot_value = 1.4 + 16 * xg + (0.5 if pressure > 2.5 else 0.0) - (0.5 if d_goal > 26 * s else 0.0) + shot_bias
    if kind == "PENALTY" or must_shoot and d_goal < 38 * s:
        shot_value = 99.0
    options: list[tuple[float, dict[str, object]]] = []
    if shot_value > 0:
        if v8:
            ty, power, clear = aim_shot(carrier, defenders, keeper, L, W, goal, s, d_goal, rng, noise)
            shot_value += clear
        else:
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
        value = gain * 0.075 + min(free, 7) * 0.25 - risk * risk_w + (1.0 if in_box else 0.0) + rng.gauss(0, noise * 0.35)
        if v8:
            if min(m.y, W - m.y) < 12 * s and m.x > carrier.x:
                value += wide_bonus
            if lofted and in_box:
                # A cross only makes sense if the man in the box can win it (space or strength).
                rival = min(defenders, key=lambda x: dist(x.x, x.y, tx, ty), default=None)
                if rival is not None and dist(rival.x, rival.y, tx, ty) < 1.8 and m.physical < rival.physical + 5:
                    value -= 1.2
            if m.vx > 4 and free > 3:
                value += 0.3      # a team-mate already running into space (one-two, third man)
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
                v2 = (sx - carrier.x) / s * 0.09 + min(space, 8) * 0.25 - risk2 * risk_w + 0.4 + through_bonus + rng.gauss(0, noise * 0.4)
                p2 = power_for_pass(dist(carrier.x, carrier.y, sx, sy) + 3.0)
                options.append((v2, {"type": "PASS", "x": sx, "y": sy, "power": round(p2, 3)}))
    if v8 and style in ("DIRECT", "COUNTER") and carrier.x < L * 0.62:
        # Long ball over the line for the most advanced forward (direct / counter style):
        # into the space behind the defence, not to feet. Still has to beat the defenders' reach.
        forwards = [m for m in mates if m.role == "ST"] or sorted(mates, key=lambda m: -m.x)[:1]
        deepest = sorted((x.x for x in defenders), reverse=True)[:4]
        line = statistics.mean(deepest) if deepest else L - 20 * s      # the back four's average depth
        for f in forwards:
            tx, ty = min(L - 10 * s, line + 6 * s), clamp(f.y + f.vy * 0.5, 6 * s, W - 6 * s)
            flight = dist(carrier.x, carrier.y, tx, ty)
            if flight < 22 * s or flight > 58 * s:
                continue
            race = f.time_to(tx, ty) - min((x.time_to(tx, ty) for x in defenders), default=9.0)
            value = 0.9 + (tx - carrier.x) / s * 0.03 - max(0.0, race) * 0.5 + (0.7 if style == "DIRECT" else 0.4) + rng.gauss(0, noise * 0.4)
            power = clamp((flight / s - LOFT_RANGE[0]) / LOFT_RANGE[1], 0.0, 1.0)
            options.append((value, {"type": "LOFT", "x": tx, "y": ty, "power": round(power, 3)}))
    if v8 and style == "WIDE" and carrier.x > L - 32 * s and min(carrier.y, W - carrier.y) < 16 * s:
        # Wide play: from the flank in the final third the natural ball is the cross into the box.
        for spot in ((L - 7 * s, W / 2 + (3 if carrier.y > W / 2 else -3) * s), (L - 9 * s, W / 2 - (4 if carrier.y > W / 2 else -4) * s)):
            flight = dist(carrier.x, carrier.y, *spot)
            power = clamp((flight / s - LOFT_RANGE[0]) / LOFT_RANGE[1], 0.0, 1.0)
            near = min((dist(m.x, m.y, *spot) for m in mates), default=20.0)
            options.append((1.6 - near * 0.08 + rng.gauss(0, noise * 0.35), {"type": "LOFT", "x": spot[0], "y": spot[1], "power": round(power, 3)}))
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
        if v8 and d_goal < 30 * s:
            # In range of goal a carry is worth the chance it creates (xG where it ends, on the
            # shot's own scale) minus the risk of losing it on the way — not just open grass.
            near_path = min((dist(x.x, x.y, (carrier.x + tx) / 2, (carrier.y + ty) / 2) for x in defenders), default=20.0)
            keep = 0.92 if near_path > 6 * s ** 0.5 else 0.7 if near_path > 3 else 0.45
            value = keep * (1.2 + 15 * xg_of(tx, ty, L, W, goal)) - 0.25 + rng.gauss(0, noise * 0.3)
        options.append((value, {"type": "CARRY", "x": tx, "y": ty, "power": 0.45}))
    if not options:
        return {"type": "SHOT", "x": L, "y": W / 2, "power": 0.8}
    return max(options, key=lambda o: o[0])[1]
