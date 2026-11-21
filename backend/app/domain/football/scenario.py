"""Opening dynamics and training drills (V7).

`kickoff_dynamics` gives an opportunity its *movement* at the first decision: on a
counter the attack is already sprinting and the defence is running back; in a build-up
everybody is jogging into shape. So a move never starts from statues.

Drills (Football Lab only, never in competitions) keep a subset of the players of the
same real squads: 1v GK, 2v1, 3v2, counter 3v3, crossing, rebound.
"""

from __future__ import annotations

import math
import random

from app.domain.football.world import Athlete, clamp

DRILLS = {
    "DRILL_1V_GK": "Treino: atacante contra o goleiro",
    "DRILL_2V1": "Treino: dois atacantes contra um defensor",
    "DRILL_3V2": "Treino: três contra dois",
    "DRILL_COUNTER": "Treino: contra-ataque 3 × 3",
    "DRILL_CROSS": "Treino: cruzamento e área",
    "OVERLOAD": "Superioridade numérica",
}


def kickoff_dynamics(bodies: list[Athlete], carrier_id: str, kind: str, L: float, W: float, rng: random.Random) -> None:
    run = {"COUNTER": (5.2, -4.0), "ONE_ON_ONE": (5.5, -5.0), "THROUGH": (3.0, -2.2), "WING": (3.4, -1.8), "OVERLOAD": (4.2, -3.0),
           "DRILL_COUNTER": (5.0, -4.0)}.get(kind, (1.6, -0.8))
    if kind in ("PENALTY", "FREE_KICK", "CORNER"):
        run = (0.0, 0.0)
    for b in bodies:
        if b.role == "GK":
            b.vx = b.vy = 0.0
            b.facing = 0.0 if b.team == "A" else math.pi
            continue
        if b.team == "A":
            sp = run[0] * rng.uniform(0.75, 1.1)
            ang = rng.uniform(-0.25, 0.25) + (0.15 if b.y < W / 2 else -0.15) * (b.id != carrier_id)
            b.vx, b.vy = math.cos(ang) * sp, math.sin(ang) * sp
            b.facing = ang if sp > 0.5 else 0.0
        else:
            sp = abs(run[1]) * rng.uniform(0.7, 1.1)
            # Running back towards their goal (x = L), but looking at the ball.
            b.vx, b.vy = sp, rng.uniform(-0.6, 0.6)
            b.facing = math.pi + rng.uniform(-0.4, 0.4)
        if b.id == carrier_id:
            b.facing = math.atan2(b.vy, b.vx) if math.hypot(b.vx, b.vy) > 0.5 else 0.0


def drill(kind: str, bodies: list[Athlete], carrier_id: str, L: float, W: float, rng: random.Random) -> tuple[list[Athlete], str]:
    """Keep only the players of the drill (same real athletes, same attributes)."""
    s = L / 105.0
    attackers = sorted((b for b in bodies if b.team == "A" and b.role != "GK"), key=lambda b: -(b.shooting + b.pace))
    defenders = sorted((b for b in bodies if b.team == "D" and b.role != "GK"), key=lambda b: -b.defending)
    keeper = next(b for b in bodies if b.team == "D" and b.role == "GK")
    n_att, n_def = {"DRILL_1V_GK": (1, 0), "DRILL_2V1": (2, 1), "DRILL_3V2": (3, 2), "DRILL_COUNTER": (3, 3), "DRILL_CROSS": (3, 2)}.get(kind, (3, 2))
    att, dfn = attackers[:n_att], defenders[:n_def]
    carrier = att[0]
    keeper.x, keeper.y = L - 1.2 * s, W / 2
    if kind == "DRILL_1V_GK":
        carrier.x, carrier.y = L - rng.uniform(22, 30) * s, W / 2 + rng.uniform(-8, 8) * s
    elif kind == "DRILL_CROSS":
        carrier.x, carrier.y = L - rng.uniform(12, 18) * s, (5 if rng.random() < 0.5 else W / s - 5) * s
        for i, a in enumerate(att[1:]):
            a.x, a.y = L - (14 + 4 * i) * s, W / 2 + (-4 + 8 * i) * s
        for i, d in enumerate(dfn):
            d.x, d.y = L - (8 + 2 * i) * s, W / 2 + (-3 + 6 * i) * s
    else:
        start = L - {"DRILL_2V1": 34, "DRILL_3V2": 40, "DRILL_COUNTER": 52}.get(kind, 40) * s
        lanes = [W / 2, W / 2 - 14 * s, W / 2 + 14 * s]
        for i, a in enumerate(att):
            a.x, a.y = start - (0 if i == 0 else rng.uniform(2, 6) * s), clamp(lanes[i] + rng.uniform(-3, 3) * s, 3 * s, W - 3 * s)
        for i, d in enumerate(dfn):
            d.x = start + rng.uniform(10, 16) * s
            d.y = clamp(W / 2 + (i - (len(dfn) - 1) / 2) * 10 * s + rng.uniform(-2, 2) * s, 3 * s, W - 3 * s)
    kept = att + dfn + [keeper]
    for b in kept:
        b.ax, b.ay = b.x, b.y
    return kept, carrier.id


def overload(bodies: list[Athlete], carrier_id: str, L: float, W: float, rng: random.Random) -> str:
    """A real-match 3v2: the attack has broken a line and arrives with one more player."""
    s = L / 105.0
    attackers = sorted((b for b in bodies if b.team == "A" and b.role != "GK"), key=lambda b: -b.pace)[:3]
    defenders = sorted((b for b in bodies if b.team == "D" and b.role == "DF"), key=lambda b: abs(b.y - W / 2))[:2]
    x0 = L - rng.uniform(36, 44) * s
    for i, a in enumerate(attackers):
        a.x, a.y = x0 - (0 if i == 0 else rng.uniform(1, 4) * s), clamp(W / 2 + (i - 1) * 13 * s + rng.uniform(-3, 3) * s, 3 * s, W - 3 * s)
    for i, d in enumerate(defenders):
        d.x, d.y = x0 + rng.uniform(11, 15) * s, W / 2 + (-5 + 10 * i) * s
    others = [b for b in bodies if b.role != "GK" and b not in attackers and b not in defenders]
    for b in others:
        if b.team == "D":
            b.x = min(b.x, x0 - rng.uniform(2, 8) * s)        # beaten: behind the ball
        else:
            b.x = min(b.x, x0 - rng.uniform(6, 14) * s)
    for b in bodies:
        b.ax, b.ay = b.x, b.y
    return attackers[1].id if len(attackers) > 1 else carrier_id
