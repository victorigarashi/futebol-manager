"""Football Gameplay Engine V7 (authoritative, deterministic, pure).

Football Game Core: world.py (athletes, ball, locomotion), keeper.py (goalkeeper agent),
brain.py (team AI), play.py (one action), choice.py (AI decisions), scenario.py (opening
dynamics and drills). The Football Match Orchestrator stays in highlights.HighlightMatch
(clock, opportunities, pauses, decisions, reconnection), which calls the functions below.
"""

from __future__ import annotations

import math
import random
from dataclasses import fields

from app.domain.football.choice import ai_choice
from app.domain.football.play import Play, PlayResult
from app.domain.football.scenario import DRILLS, drill, kickoff_dynamics, overload
from app.domain.football.world import (
    CARRY_RANGE,
    FRAME_DT,
    LOFT_ANGLE,
    LOFT_RANGE,
    PASS_SPEED,
    ROLL_DECEL,
    ROLL_DRAG,
    SHOT_SPEED,
    Athlete,
    BallState,
)

ENGINE = "v7"
_ATHLETE_FIELDS = {f.name for f in fields(Athlete)}
_PERSISTED = ("id", "name", "number", "team", "role", "x", "y", "pace", "passing", "shooting", "dribbling", "defending", "physical",
              "keeping", "ax", "ay", "vx", "vy", "facing")


def athletes(rows: list[dict[str, object]]) -> list[Athlete]:
    return [Athlete(**{k: v for k, v in row.items() if k in _ATHLETE_FIELDS}) for row in rows]


def rows(bodies: list[Athlete]) -> list[dict[str, object]]:
    return [{k: (round(getattr(b, k), 4) if isinstance(getattr(b, k), float) else getattr(b, k)) for k in _PERSISTED} for b in bodies]


def resolve(body_rows: list[dict[str, object]], ball_row: dict[str, object], carrier_id: str, action: str, tx: float, ty: float, power: float,
            cfg: dict[str, float], rng: random.Random, boost: float, tactics: dict[str, str] | None, difficulty: str) -> tuple[PlayResult, list[dict], dict]:
    bodies = athletes(body_rows)
    ball = BallState(float(ball_row.get("x", 0.0)), float(ball_row.get("y", 0.0)))
    play = Play(bodies, ball, cfg, rng, boost, tactics, difficulty)
    result = play.run(carrier_id, action, tx, ty, power)
    return result, rows(bodies), {"x": ball.x, "y": ball.y, "vx": 0.0, "vy": 0.0, "z": 0.0, "vz": 0.0, "air_left": 0.0, "air_total": 0.0}


def choose(body_rows: list[dict[str, object]], carrier_id: str, cfg: dict[str, float], actions_done: int, kind: str, rng: random.Random,
           difficulty: str) -> dict[str, object]:
    return ai_choice(athletes(body_rows), carrier_id, cfg, actions_done, kind, rng, difficulty)


def opening(body_rows: list[dict[str, object]], carrier_id: str, kind: str, cfg: dict[str, float], rng: random.Random) -> tuple[list[dict], str]:
    """Drills / overload placement and the opening movement of every opportunity."""
    bodies = athletes(body_rows)
    L, W = cfg["length"], cfg["width"]
    if kind.startswith("DRILL_"):
        bodies, carrier_id = drill(kind, bodies, carrier_id, L, W, rng)
    elif kind == "OVERLOAD":
        carrier_id = overload(bodies, carrier_id, L, W, rng)
    kickoff_dynamics(bodies, carrier_id, kind, L, W, rng)
    return rows(bodies), carrier_id


def physics_view(scale: float, assist_angle: float) -> dict[str, object]:
    """What the client needs to forecast the line of a gesture with the SAME formulas."""
    return {"model": ENGINE, "pass": PASS_SPEED, "roll": [ROLL_DECEL, ROLL_DRAG], "decel": ROLL_DECEL, "loft_range": LOFT_RANGE,
            "loft_angle": LOFT_ANGLE, "shot": SHOT_SPEED, "carry": CARRY_RANGE, "assist_angle": assist_angle, "frame_dt": FRAME_DT,
            "scale": scale}


def world_facing(angle: float, right: bool) -> float:
    return angle if right else (angle + math.pi + math.pi) % (2 * math.pi) - math.pi


__all__ = ["DRILLS", "ENGINE", "choose", "opening", "physics_view", "resolve", "world_facing"]
