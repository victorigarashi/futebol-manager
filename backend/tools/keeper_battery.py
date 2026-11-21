"""Goalkeeper test battery (V7): reproducible shots against a keeper alone.

Each scenario is played with N seeds by the real action physics (play.Play): shooter and
keeper only, so the result depends on the shot and the keeper, nothing else. Reports
goal / save (held + parried) / wide and checks physical plausibility.

    cd backend && ../.venv/bin/python tools/keeper_battery.py [seeds] [keeping]
"""

import json
import random
import sys

sys.path.insert(0, ".")

from app.domain.football.play import Play  # noqa: E402
from app.domain.football.world import Athlete, BallState  # noqa: E402
from app.domain.highlights import HL_PITCH  # noqa: E402

CFG = HL_PITCH["ELEVEN_A_SIDE"]
L, W = CFG["length"], CFG["width"]
# name: (distance from goal line, lateral offset, aim y offset from centre, power)
SCENARIOS = {
    "central_11m_forte": (11, 0, 0.0, 0.85),
    "canto_esq_16m": (16, 0, -3.0, 0.75),
    "canto_dir_16m": (16, 0, 3.0, 0.75),
    "rasteiro_canto_14m": (14, -4, 3.2, 0.5),
    "colocado_alto_18m": (18, 3, -3.1, 0.9),
    "perto_6m": (6, 2, -2.5, 0.7),
    "longe_28m": (28, 0, 2.8, 0.95),
    "fraco_central_15m": (15, 0, 0.3, 0.25),
    "forte_angulo_12m": (12, 10, 3.0, 0.9),
    "bola_ao_alcance_20m": (20, 0, 1.0, 0.6),
    "fora_do_alcance_canto_9m": (9, 0, -3.45, 0.95),
}


def athlete(i, team, role, x, y, attrs):
    return Athlete(f"{team}{i}", f"{team}{i}", i, team, role, x, y, *attrs)


def play(scenario, seed, keeping):
    d, off, aim, power = scenario
    shooter = athlete(9, "A", "ST", L - d, W / 2 + off, (80, 75, 82, 80, 30, 75, 20))
    keeper = athlete(1, "D", "GK", L - 1.0, W / 2, (50, 50, 20, 40, 30, 70, keeping))
    shooter.facing = 0.0
    keeper.facing = 3.14159
    for b in (shooter, keeper):
        b.ax, b.ay = b.x, b.y
    p = Play([shooter, keeper], BallState(shooter.x + 0.4, shooter.y), CFG, random.Random(seed))
    return p.run(shooter.id, "SHOT", L, W / 2 + aim, power)


def main(seeds=40, keeping=75):
    out = {}
    for name, sc in SCENARIOS.items():
        tally = {"GOAL": 0, "SAVE": 0, "WIDE": 0, "OTHER": 0}
        for seed in range(seeds):
            r = play(sc, seed, keeping)
            saved = any(c["kind"] in ("SAVE", "CLAIM") for c in r.cues)
            key = "GOAL" if r.outcome == "GOAL" else "SAVE" if saved else "WIDE" if r.outcome in ("OUT",) else "OTHER"
            tally[key] += 1
        out[name] = tally
    return out


if __name__ == "__main__":
    seeds = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    keepers = [int(sys.argv[2])] if len(sys.argv) > 2 else [55, 75, 90]
    print(json.dumps({k: main(seeds, k) for k in keepers}, indent=1))
