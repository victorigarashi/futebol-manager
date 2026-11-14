"""Incremental, deterministic agent-based football engine.

One tick is one second of game time. Every player is an agent that moves toward a
target derived from the team shape, the ball and the coach's tactics; the ball
carrier chooses between shooting, passing, crossing, carrying and holding. Every
outcome (pass, duel, shot, foul) is resolved from player attributes, distances and
the seeded RNG — there is no pre-drawn score and no tactical goal bonus.

The engine can be advanced tick by tick, accepts coach commands between ticks and
is fully reproducible from (inputs, seed, command log).
"""

from __future__ import annotations

import math
import random
from collections import deque
from dataclasses import dataclass, field

from app.domain.tactics import Tactics

TICKS_PER_HALF = 2700
FULL_TIME_TICK = TICKS_PER_HALF * 2

PITCH = {
    "ELEVEN_A_SIDE": {"length": 105.0, "width": 68.0, "goal": 7.32, "box": 16.5, "shot_range": 30.0, "xg_scale": 1.0, "max_subs": 5, "windows": 3},
    "FIVE_A_SIDE": {"length": 40.0, "width": 22.0, "goal": 3.0, "box": 6.0, "shot_range": 15.0, "xg_scale": 1.6, "max_subs": 3, "windows": 99},
}

# Real engine parameters per tactic. Every number is consumed below.
MENTALITY = {
    #                 line   length  support runners  shot_bias  loss_cost
    "VERY_DEFENSIVE": (0.21, 0.33, 0, 0.12, -0.008, 1.30),
    "DEFENSIVE":      (0.25, 0.36, 1, 0.20, -0.004, 1.15),
    "BALANCED":       (0.29, 0.40, 1, 0.28, 0.000, 1.00),
    "ATTACKING":      (0.32, 0.44, 2, 0.36, 0.004, 0.90),
    "VERY_ATTACKING": (0.35, 0.48, 2, 0.45, 0.008, 0.80),
}
PRESSURE = {
    #          pressers trigger(depth) tackle_rate foul_extra line_push drain
    "LOW":    (1, 0.38, 0.08, 0.000, -0.03, 0.80),
    "MEDIUM": (1, 0.62, 0.11, 0.015, 0.00, 1.00),
    "HIGH":   (2, 1.10, 0.14, 0.035, 0.03, 1.90),
}
STYLE = {
    #                 risk  progress long_bonus width  hold  counter cross
    "POSSESSION":    (1.55, 0.80, -0.04, 1.00, 0.06, 0.0, 0.6),
    "COUNTER":       (0.95, 1.10, 0.02, 0.95, 0.00, 1.0, 0.8),
    "DIRECT":        (0.70, 1.45, 0.07, 0.95, 0.00, 0.3, 1.0),
    "SHORT_BUILDUP": (1.30, 0.90, -0.08, 1.00, 0.03, 0.0, 0.7),
    "WIDE":          (1.05, 1.00, 0.00, 1.18, 0.02, 0.0, 1.6),
}

EVENT_KINDS = {"KICK_OFF", "SHOT", "SAVE", "GOAL", "CORNER", "FOUL", "CARD", "SUBSTITUTION",
               "TACTICS", "HALF_TIME", "SECOND_HALF", "FULL_TIME", "BIG_CHANCE"}


@dataclass(frozen=True)
class PlayerInput:
    id: str
    name: str
    position: str
    slot_position: str
    slot_x: float  # lateral 0..100 from formation_slots
    slot_y: float  # depth 0..100 from formation_slots (89 = goalkeeper)
    overall: int
    attributes: dict[str, int] = field(default_factory=dict)
    number: int = 0


@dataclass(frozen=True)
class TeamInput:
    club_code: str
    formation_code: str
    starters: tuple[PlayerInput, ...]
    bench: tuple[PlayerInput, ...]
    tactics: Tactics = Tactics()


def derived_attributes(player: PlayerInput) -> dict[str, float]:
    """Catalog attributes when present; otherwise a transparent profile from overall.

    The profile only distributes the supplied overall by position (it never raises the
    player's level) and is computed at runtime — nothing is written to the catalog.
    """
    o = float(player.overall)
    base = {
        "GK": {"pace": o - 20, "passing": o - 18, "shooting": o - 45, "dribbling": o - 25, "defending": o - 30, "physical": o - 8, "keeping": o},
        "DF": {"pace": o - 4, "passing": o - 8, "shooting": o - 28, "dribbling": o - 12, "defending": o + 3, "physical": o + 2, "keeping": 20},
        "MF": {"pace": o - 3, "passing": o + 3, "shooting": o - 8, "dribbling": o + 1, "defending": o - 8, "physical": o - 4, "keeping": 20},
        "ST": {"pace": o + 2, "passing": o - 6, "shooting": o + 3, "dribbling": o, "defending": o - 30, "physical": o - 2, "keeping": 20},
    }.get(player.position, {})
    attrs = {key: float(max(15, min(99, value))) for key, value in base.items()}
    for key in ("pace", "passing", "shooting", "dribbling", "defending", "physical"):
        if key in player.attributes:
            attrs[key] = float(player.attributes[key])
    keeper = [player.attributes[k] for k in ("gk_diving", "gk_handling", "gk_reflexes", "gk_positioning") if k in player.attributes]
    if keeper:
        attrs["keeping"] = sum(keeper) / len(keeper)
    # Playing out of position costs real ability (same penalty as lineup evaluation).
    if player.slot_position != player.position:
        penalty = 12 if "GK" in (player.slot_position, player.position) else 6
        for key in attrs:
            attrs[key] = max(10.0, attrs[key] - penalty)
        if player.slot_position == "GK":
            attrs["keeping"] = max(10.0, min(attrs["keeping"], o - 35))
    return attrs


class Agent:
    __slots__ = ("id", "name", "side", "number", "role", "position", "ax", "ay", "x", "y", "pace", "passing",
                 "shooting", "dribbling", "defending", "physical", "keeping", "stamina", "yellow", "sent_off",
                 "active", "stun", "index", "stats", "entered_tick", "left_tick", "overall", "intensity")

    def __init__(self, player: PlayerInput, side: int, index: int) -> None:
        a = derived_attributes(player)
        self.id, self.name, self.side, self.index = player.id, player.name, side, index
        self.number = player.number
        self.role = player.slot_position
        self.position = player.position
        self.overall = player.overall
        self.ax = (100 - player.slot_y) / 100  # depth from own goal (0.11 GK … 0.82 ST)
        self.ay = player.slot_x / 100
        self.pace, self.passing, self.shooting = a["pace"], a["passing"], a["shooting"]
        self.dribbling, self.defending, self.physical, self.keeping = a["dribbling"], a["defending"], a["physical"], a["keeping"]
        self.x = self.y = 0.0
        self.stamina = 1.0
        self.yellow = 0
        self.sent_off = False
        self.active = False
        self.stun = 0
        self.entered_tick: int | None = None
        self.left_tick: int | None = None
        self.intensity = 0.0
        self.stats = {k: 0 for k in ("passes", "passes_completed", "key_passes", "shots", "shots_on_target", "goals", "assists",
                                     "tackles", "interceptions", "fouls", "saves", "dribbles", "losses", "distance")}

    def skill(self, value: float) -> float:
        # Fatigue degrades execution: an exhausted player keeps ~70% of his level.
        return value * (0.70 + 0.30 * self.stamina)


class MatchEngine:
    def __init__(self, match_id: str, mode: str, home: TeamInput, away: TeamInput, seed: int) -> None:
        if mode not in PITCH:
            raise ValueError("Modo inválido.")
        self.match_id, self.mode, self.seed = match_id, mode, seed
        self.cfg = PITCH[mode]
        self.L, self.W = self.cfg["length"], self.cfg["width"]
        self.rng = random.Random(seed)
        self.inputs = (home, away)
        self.clubs = (home.club_code, away.club_code)
        self.tactics = [home.tactics, away.tactics]
        self.agents: list[Agent] = []
        self.team_agents: list[list[Agent]] = [[], []]
        for side, team in enumerate((home, away)):
            for player in (*team.starters, *team.bench):
                agent = Agent(player, side, len(self.agents))
                self.agents.append(agent)
                self.team_agents[side].append(agent)
            for agent in self.team_agents[side][:len(team.starters)]:
                agent.active = True
                agent.entered_tick = 0
        self.by_id = {agent.id: agent for agent in self.agents}
        self.tick = 0
        self.score = [0, 0]
        self.events: list[dict[str, object]] = []
        self.team_stats = [self._empty_stats(), self._empty_stats()]
        self.subs_used = [0, 0]
        self.windows_used = [0, 0]
        self.pending_subs: list[list[tuple[str, str, str]]] = [[], []]  # (command_id, out, in)
        self.command_log: list[dict[str, object]] = []
        self.applied_commands: dict[str, dict[str, object]] = {}
        self.frames: deque[tuple] = deque(maxlen=1200)
        # Ball state
        self.bx, self.by = self.L / 2, self.W / 2
        self.owner: Agent | None = None
        self.received_tick = 0
        self.flight: dict[str, object] | None = None
        self.dead: dict[str, object] | None = None
        self.last_pass: tuple[Agent, int] | None = None
        self.possession_side = 0
        self.possession_since = 0
        self.phase = "FIRST_HALF"
        self._place_kickoff(0)
        self._event("KICK_OFF", 0, None, self.bx, self.by)
        self._record_frame()

    # ------------------------------------------------------------------ geometry
    @staticmethod
    def _empty_stats() -> dict[str, float]:
        return {k: 0 for k in ("possession_ticks", "passes", "passes_completed", "shots", "shots_on_target", "goals", "xg",
                               "corners", "fouls", "yellow_cards", "red_cards", "tackles", "interceptions", "saves",
                               "recoveries", "high_recoveries", "final_third_entries", "distance", "box_touches", "through_balls")}

    def fwd(self, side: int, x: float) -> float:
        """Distance from the side's own goal line (its attacking direction is +)."""
        return x if side == 0 else self.L - x

    def abs_x(self, side: int, f: float) -> float:
        return f if side == 0 else self.L - f

    def goal_x(self, side: int) -> float:
        """x of the goal the side attacks."""
        return self.L if side == 0 else 0.0

    def shot_xg(self, side: int, x: float, y: float) -> float:
        gx = self.goal_x(side)
        dx = abs(gx - x)
        dy = y - self.W / 2
        dist = math.hypot(dx, dy)
        half = self.cfg["goal"] / 2
        angle = abs(math.atan2(half - dy, dx) - math.atan2(-half - dy, dx))
        logit = -1.35 - 0.13 * dist * self.cfg["xg_scale"] + 1.6 * angle
        return 1 / (1 + math.exp(-logit))

    def active(self, side: int) -> list[Agent]:
        return [a for a in self.team_agents[side] if a.active]

    # ------------------------------------------------------------------ events
    def _event(self, kind: str, side: int | None, agent: Agent | None, x: float, y: float, outcome: str = "", other: Agent | None = None, xg: float = 0.0, extra: dict[str, object] | None = None) -> dict[str, object]:
        event = {
            "event_id": f"{self.match_id}:{len(self.events) + 1:05d}", "match_id": self.match_id, "kind": kind,
            "team": self.clubs[side] if side is not None else None, "tick": self.tick,
            "minute": min(90, self.tick // 60 + (1 if self.tick % 60 else 0)) if self.tick else 0,
            "x": round(min(1, max(0, x / self.L)), 4), "y": round(min(1, max(0, y / self.W)), 4), "outcome": outcome,
            "player_id": agent.id if agent else None, "player_name": agent.name if agent else None,
            "secondary_player_id": other.id if other else None, "secondary_player_name": other.name if other else None,
            "xg": round(xg, 4), "score": {"home": self.score[0], "away": self.score[1]},
        }
        if extra:
            event.update(extra)
        self.events.append(event)
        return event

    # ------------------------------------------------------------------ set up
    def _formation_spot(self, agent: Agent, kickoff: bool = False) -> tuple[float, float]:
        depth = agent.ax * (0.46 if kickoff else 0.55) if agent.role != "GK" else 0.02
        f = max(1.0, min(self.L / 2 - 1.0, depth * self.L)) if kickoff else depth * self.L
        return self.abs_x(agent.side, f), agent.ay * self.W

    def _place_kickoff(self, side: int) -> None:
        for agent in self.agents:
            if agent.active:
                agent.x, agent.y = self._formation_spot(agent, kickoff=True)
        takers = sorted(self.active(side), key=lambda a: -a.ax)
        taker = takers[0]
        taker.x, taker.y = self.L / 2, self.W / 2
        self.bx, self.by = self.L / 2, self.W / 2
        self._give(taker, kickoff=True)

    def _give(self, agent: Agent, kickoff: bool = False) -> None:
        previous = self.possession_side
        self.owner = agent
        self.flight = None
        self.bx, self.by = agent.x, agent.y
        self.received_tick = self.tick
        if agent.side != previous or kickoff:
            self.possession_since = self.tick
            if not kickoff:
                stats = self.team_stats[agent.side]
                stats["recoveries"] += 1
                if self.fwd(agent.side, agent.x) > self.L * 0.6:
                    stats["high_recoveries"] += 1
        self.possession_side = agent.side
        if self.fwd(agent.side, agent.x) > self.L - self.cfg["box"] and abs(agent.y - self.W / 2) < self.cfg["box"] * 1.25:
            self.team_stats[agent.side]["box_touches"] += 1

    # ------------------------------------------------------------------ commands
    def queue_tactics(self, side: int, tactics: Tactics, command_id: str) -> dict[str, object]:
        self.command_log.append({"tick": self.tick, "side": side, "kind": "TACTICS", "command_id": command_id, "tactics": tactics.view()})
        previous = self.tactics[side]
        self.tactics[side] = tactics
        changes = {k: v for k, v in tactics.view().items() if previous.view()[k] != v}
        status = {"command_id": command_id, "kind": "TACTICS", "status": "APPLIED", "applied_tick": self.tick, "tactics": tactics.view()}
        self.applied_commands[command_id] = status
        if changes:
            self._event("TACTICS", side, None, self.bx, self.by, ",".join(f"{k}={v}" for k, v in changes.items()), extra={"tactics": tactics.view()})
        return status

    def substitution_error(self, side: int, out_id: str, in_id: str) -> str | None:
        out_agent, in_agent = self.by_id.get(out_id), self.by_id.get(in_id)
        if not out_agent or not in_agent or out_agent.side != side or in_agent.side != side:
            return "Atleta não pertence ao seu time nesta partida."
        if self.phase == "FULL_TIME":
            return "A partida já terminou."
        if not out_agent.active:
            return "O jogador que sai não está em campo."
        if in_agent.active or in_agent.entered_tick is not None:
            return "O substituto já participou da partida e não pode entrar."
        pending = self.pending_subs[side]
        if any(o == out_id or i == in_id for _, o, i in pending):
            return "Já existe uma substituição pendente com esses jogadores."
        if self.subs_used[side] + len(pending) >= self.cfg["max_subs"]:
            return f"Limite de {self.cfg['max_subs']} substituições atingido."
        if self.windows_used[side] >= self.cfg["windows"] and self.phase != "HALF_TIME" and not pending:
            return "Sem janelas de substituição restantes (somente no intervalo)."
        return None

    def queue_substitution(self, side: int, out_id: str, in_id: str, command_id: str) -> dict[str, object]:
        error = self.substitution_error(side, out_id, in_id)
        if error:
            raise ValueError(error)
        self.pending_subs[side].append((command_id, out_id, in_id))
        self.command_log.append({"tick": self.tick, "side": side, "kind": "SUBSTITUTION", "command_id": command_id, "out": out_id, "in": in_id})
        status = {"command_id": command_id, "kind": "SUBSTITUTION", "status": "PENDING", "requested_tick": self.tick, "out_player_id": out_id, "in_player_id": in_id}
        self.applied_commands[command_id] = status
        if self.dead is not None or self.phase == "HALF_TIME":
            self._apply_pending_subs()
        return status

    def _apply_pending_subs(self) -> None:
        for side in (0, 1):
            pending = self.pending_subs[side]
            if not pending:
                continue
            if self.phase != "HALF_TIME" and self.tick > 0:
                self.windows_used[side] += 1
            for command_id, out_id, in_id in pending:
                out_agent, in_agent = self.by_id[out_id], self.by_id[in_id]
                status = self.applied_commands[command_id]
                if not out_agent.active or in_agent.entered_tick is not None:
                    status.update(status="REJECTED", reason="O jogador saiu de campo antes da paralisação.")
                    continue
                in_agent.role, in_agent.ax, in_agent.ay = out_agent.role, out_agent.ax, out_agent.ay
                # Re-evaluate the incoming player for the vacated slot (out-of-position cost).
                in_agent.active, in_agent.entered_tick = True, self.tick
                in_agent.x, in_agent.y = self.L / 2, 0.0 if out_agent.y < self.W / 2 else self.W
                out_agent.active, out_agent.left_tick = False, self.tick
                if self.owner is out_agent:
                    self._give(in_agent)
                self.subs_used[side] += 1
                status.update(status="APPLIED", applied_tick=self.tick)
                self._event("SUBSTITUTION", side, in_agent, in_agent.x, in_agent.y, "IN", other=out_agent,
                            extra={"command_id": command_id, "stamina_out": round(out_agent.stamina, 3)})
            pending.clear()

    # ------------------------------------------------------------------ main loop
    @property
    def finished(self) -> bool:
        return self.phase == "FULL_TIME"

    def advance_to(self, target_tick: int) -> None:
        target_tick = min(FULL_TIME_TICK, target_tick)
        while self.tick < target_tick and not self.finished:
            self.step()

    def run_to_end(self) -> None:
        self.advance_to(FULL_TIME_TICK)

    def step(self) -> None:
        if self.finished:
            return
        if self.phase == "HALF_TIME":
            self._start_second_half()
        self.tick += 1
        if self.dead is not None:
            self._dead_ball_tick()
        else:
            self._live_tick()
        self._move_agents()
        if self.owner is not None:
            self.bx, self.by = self.owner.x, self.owner.y
            self.team_stats[self.owner.side]["possession_ticks"] += 1
        if self.tick == TICKS_PER_HALF and self.phase == "FIRST_HALF":
            self._half_time()
        elif self.tick >= FULL_TIME_TICK:
            self._full_time()
        self._record_frame()

    def _half_time(self) -> None:
        self.phase = "HALF_TIME"
        self.dead = None
        self.flight = None
        self._event("HALF_TIME", None, None, self.L / 2, self.W / 2)
        for agent in self.agents:
            if agent.active:
                agent.stamina = min(1.0, agent.stamina + 0.06)
        self._apply_pending_subs()

    def _start_second_half(self) -> None:
        self._apply_pending_subs()
        self.phase = "SECOND_HALF"
        self._place_kickoff(1)
        self._event("SECOND_HALF", 1, None, self.bx, self.by)

    def _full_time(self) -> None:
        self.phase = "FULL_TIME"
        self.owner = None
        for side in (0, 1):
            for command_id, *_ in self.pending_subs[side]:
                self.applied_commands[command_id].update(status="REJECTED", reason="A partida terminou antes de uma paralisação.")
            self.pending_subs[side].clear()
        for agent in self.agents:
            if agent.active:
                agent.left_tick = FULL_TIME_TICK
        self._event("FULL_TIME", None, None, self.L / 2, self.W / 2)

    # ------------------------------------------------------------------ dead ball
    def _stop(self, restart: str, side: int, x: float, y: float, duration: int) -> None:
        self.owner = None
        self.flight = None
        self.bx, self.by = x, y
        candidates = [a for a in self.active(side) if (a.role != "GK" or restart == "GOAL_KICK")]
        if restart == "GOAL_KICK":
            keeper = next((a for a in candidates if a.role == "GK"), None)
            taker = keeper or min(candidates, key=lambda a: (a.x - x) ** 2 + (a.y - y) ** 2)
        else:
            taker = min(candidates, key=lambda a: (a.x - x) ** 2 + (a.y - y) ** 2)
        self.dead = {"restart": restart, "side": side, "x": x, "y": y, "resume": self.tick + duration, "taker": taker}
        self._apply_pending_subs()

    def _dead_ball_tick(self) -> None:
        dead = self.dead
        assert dead is not None
        if self.tick < dead["resume"]:
            return
        taker: Agent = dead["taker"]
        if not taker.active:
            taker = min(self.active(dead["side"]), key=lambda a: (a.x - dead["x"]) ** 2 + (a.y - dead["y"]) ** 2)
        taker.x, taker.y = dead["x"], dead["y"]
        restart, side = dead["restart"], dead["side"]
        self.dead = None
        if restart == "KICK_OFF":
            self._place_kickoff(side)
            self._event("KICK_OFF", side, None, self.bx, self.by)
            return
        self._give(taker)
        self.received_tick = self.tick - 1  # restarts are played immediately
        if restart == "CORNER":
            self._corner(taker)
        elif restart == "FREE_KICK" and self.shot_xg(side, taker.x, taker.y) > 0.025:
            if self.rng.random() < 0.55:
                self._shoot(taker, set_piece=True)

    def _corner(self, taker: Agent) -> None:
        side = taker.side
        attackers = [a for a in self.active(side) if a is not taker and a.role != "GK"]
        defenders = [a for a in self.active(1 - side) if a.role != "GK"]
        # Bodies attack the box: the best headers become the cross targets.
        target = max(attackers, key=lambda a: a.physical + self.rng.random() * 25)
        tx = self.abs_x(side, self.L - self.cfg["box"] * 0.45)
        ty = self.W / 2 + self.rng.uniform(-0.3, 0.3) * self.cfg["box"]
        target.x, target.y = tx, ty
        marker = max(defenders, key=lambda a: a.physical + a.defending * 0.5 + self.rng.random() * 25) if defenders else None
        delivery = taker.skill(taker.passing)
        contest = 0.24 + (target.skill(target.physical) - (marker.skill(marker.physical) if marker else 40)) / 160 + (delivery - 70) / 300
        taker.stats["passes"] += 1
        self.team_stats[side]["passes"] += 1
        if self.rng.random() < max(0.12, min(0.62, contest)):
            taker.stats["passes_completed"] += 1
            self.team_stats[side]["passes_completed"] += 1
            self.last_pass = (taker, self.tick)
            self.bx, self.by = tx, ty
            self.owner = target
            self.possession_side = side
            self._shoot(target, header=True)
        elif marker is not None:
            marker.x, marker.y = tx, ty
            marker.stats["interceptions"] += 1
            self.team_stats[1 - side]["interceptions"] += 1
            self._give(marker)
            self._clearance(marker)

    # ------------------------------------------------------------------ live play
    def _live_tick(self) -> None:
        if self.flight is not None:
            if self.tick >= self.flight["arrive"]:
                self._resolve_flight()
            else:
                f = self.flight
                mix = (self.tick - f["start"]) / max(1, f["arrive"] - f["start"])
                self.bx = f["fx"] + (f["tx"] - f["fx"]) * mix
                self.by = f["fy"] + (f["ty"] - f["fy"]) * mix
            return
        if self.owner is None:
            self._loose_ball()
            return
        if self._duel():
            return
        owner = self.owner
        if owner is not None and self.tick > self.received_tick:
            # Tempo: a first touch, then the player looks up. Calmer styles keep it longer.
            settle = 0.62 if self.tactics[owner.side].style in ("POSSESSION", "SHORT_BUILDUP") else 0.50
            held = self.tick - self.received_tick
            if (held == 1 and self.rng.random() < settle) or (held == 2 and self.rng.random() < settle * 0.6):
                return
            self._decide(owner)

    def _loose_ball(self) -> None:
        nearest = min((a for a in self.agents if a.active and a.stun == 0), key=lambda a: (a.x - self.bx) ** 2 + (a.y - self.by) ** 2)
        if (nearest.x - self.bx) ** 2 + (nearest.y - self.by) ** 2 < 6.25:
            if nearest.side != self.possession_side:
                nearest.stats["interceptions"] += 1
                self.team_stats[nearest.side]["interceptions"] += 1
            self._give(nearest)

    def _duel(self) -> bool:
        owner = self.owner
        assert owner is not None
        side = 1 - owner.side
        pressure_cfg = PRESSURE[self.tactics[side].pressure]
        # Around our own area everybody attacks the ball, whatever the pressing plan.
        danger = self.fwd(owner.side, owner.x) > self.L - self.cfg["box"] * 1.6
        attempt_rate = min(0.6, pressure_cfg[2] * 2.6) if danger else pressure_cfg[2]
        for defender in self.active(side):
            if defender.stun or defender.role == "GK" and self.fwd(side, defender.x) > self.cfg["box"]:
                continue
            if (defender.x - owner.x) ** 2 + (defender.y - owner.y) ** 2 > 4.0:
                continue
            if self.rng.random() > attempt_rate:
                continue
            tired = 1 - defender.stamina
            foul_p = (0.028 + pressure_cfg[3] + max(0.0, 70 - defender.defending) / 450 + tired * 0.08) * (0.35 if danger else 1.0)
            if self.rng.random() < foul_p:
                self._foul(defender, owner)
                return True
            win_p = 0.50 + (defender.skill(defender.defending) - owner.skill(owner.dribbling)) / 110
            if self.rng.random() < max(0.15, min(0.85, win_p)):
                defender.stats["tackles"] += 1
                owner.stats["losses"] += 1
                self.team_stats[side]["tackles"] += 1
                self._give(defender)
                self.received_tick = self.tick
            else:
                defender.stun = 2
                owner.stats["dribbles"] += 1
            return True
        return False

    def _foul(self, defender: Agent, victim: Agent) -> None:
        side = defender.side
        defender.stats["fouls"] += 1
        self.team_stats[side]["fouls"] += 1
        self._event("FOUL", side, defender, victim.x, victim.y, "FREE_KICK", other=victim)
        danger = self.fwd(victim.side, victim.x) / self.L
        card_p = 0.08 + 0.10 * danger + (0.04 if self.tactics[side].pressure == "HIGH" else 0)
        roll = self.rng.random()
        if roll < 0.0015:
            self._send_off(defender, "RED")
        elif roll < card_p:
            defender.yellow += 1
            self.team_stats[side]["yellow_cards"] += 1
            if defender.yellow >= 2:
                self._send_off(defender, "SECOND_YELLOW")
            else:
                self._event("CARD", side, defender, defender.x, defender.y, "YELLOW")
        self._stop("FREE_KICK", victim.side, victim.x, victim.y, 12)

    def _send_off(self, agent: Agent, outcome: str) -> None:
        self.team_stats[agent.side]["red_cards"] += 1
        self._event("CARD", agent.side, agent, agent.x, agent.y, outcome)
        agent.active, agent.sent_off, agent.left_tick = False, True, self.tick
        if agent.role == "GK":
            # Someone must play in goal: the deepest outfield player takes the gloves.
            remaining = [a for a in self.active(agent.side) if a.role != "GK"]
            if remaining:
                stand_in = min(remaining, key=lambda a: a.ax)
                stand_in.role, stand_in.ax, stand_in.ay = "GK", agent.ax, 0.5
                stand_in.keeping = min(stand_in.keeping, 30.0)
        if self.owner is agent:
            self.owner = None

    # ------------------------------------------------------------------ decisions
    def value(self, side: int, x: float, y: float) -> float:
        """Possession value of `side` holding the ball at (x, y): territory + chance quality."""
        u = self.fwd(side, x) / self.L
        return 0.006 + 0.06 * u * u + 0.55 * self.shot_xg(side, x, y)

    def _shot_lane_factor(self, shooter: Agent) -> float:
        """Bodies between the shooter and the goal reduce the quality of the attempt."""
        side = shooter.side
        gx, gy = self.goal_x(side), self.W / 2
        dx, dy = gx - shooter.x, gy - shooter.y
        d2 = dx * dx + dy * dy or 1.0
        factor = 1.0
        for opp in self.team_agents[1 - side]:
            if not opp.active or opp.role == "GK":
                continue
            t = ((opp.x - shooter.x) * dx + (opp.y - shooter.y) * dy) / d2
            if 0 < t < 1:
                off = abs((opp.x - shooter.x) * dy - (opp.y - shooter.y) * dx) / d2 ** 0.5
                if off < 1.0 + 2.5 * t:
                    factor *= 0.62
        return factor

    def _decide(self, owner: Agent) -> None:
        side = owner.side
        tactics = self.tactics[side]
        mentality, style = MENTALITY[tactics.mentality], STYLE[tactics.style]
        rng = self.rng
        opponents = self.active(1 - side)
        f_owner = self.fwd(side, owner.x)
        nearest_opp = min(((o.x - owner.x) ** 2 + (o.y - owner.y) ** 2 for o in opponents), default=400.0) ** 0.5
        press = max(0.0, 1 - nearest_opp / 4.0)
        risk = mentality[5] * style[0] * 1.8  # losing the ball also costs shape and a transition
        held = self.tick - self.received_tick
        counter_phase = style[5] > 0 and self.tick - self.possession_since < 10
        progress_weight = style[1] * (1.6 if counter_phase else 1.0) * (0.85 + 0.1 * mentality[2])
        v_here = self.value(side, owner.x, owner.y)
        loss_here = self.value(1 - side, owner.x, owner.y)
        noise = 0.0035

        p_hold = 0.985 - 0.35 * press
        best_kind, best_target = "hold", None
        best_value = p_hold * v_here - (1 - p_hold) * loss_here * risk - 0.0012 * held + style[4] * 0.01 + rng.random() * noise

        dist_goal = math.hypot(self.goal_x(side) - owner.x, owner.y - self.W / 2)
        if dist_goal < self.cfg["shot_range"] and owner.role != "GK":
            xg = self.shot_xg(side, owner.x, owner.y) * (1 - 0.35 * press)
            value = xg * self._shot_lane_factor(owner) * 1.1 + 0.005 + mentality[4] + (owner.shooting - 65) / 4000 + rng.random() * noise
            if value > best_value:
                best_kind, best_value = "shoot", value

        width_bias = style[3] - 1.0
        pass_skill = owner.skill(owner.passing)
        crossing_zone = f_owner > self.L * 0.70 and abs(owner.y - self.W / 2) > self.W * 0.26
        for mate in self.team_agents[side]:
            if not mate.active or mate is owner or mate.stun:
                continue
            dx, dy = mate.x - owner.x, mate.y - owner.y
            dist = math.hypot(dx, dy)
            if dist < 3.0 or dist > self.L * 0.62:
                continue
            f_mate = self.fwd(side, mate.x)
            if mate.role == "GK" and press < 0.5:
                continue
            lane = 0.0
            marked = 9.0
            for opp in opponents:
                ox, oy = opp.x - owner.x, opp.y - owner.y
                t = max(0.0, min(1.0, (ox * dx + oy * dy) / (dist * dist)))
                lx, ly = ox - t * dx, oy - t * dy
                lane_d2 = lx * lx + ly * ly
                if lane_d2 < 9.0:
                    lane += (1 - lane_d2 / 9.0) * (0.6 + opp.defending / 200)
                md = ((opp.x - mate.x) ** 2 + (opp.y - mate.y) ** 2) ** 0.5
                if md < marked:
                    marked = md
            long_ball = dist > (28 if self.mode == "ELEVEN_A_SIDE" else 14)
            success = 0.995 - dist * 0.0028 * (1.55 - pass_skill / 100) - lane * 0.055 - max(0.0, 3.0 - marked) * (0.05 + 0.10 * (f_mate > self.L * 0.7)) - press * 0.06
            if long_ball:
                success -= 0.10 * (1.2 - pass_skill / 100)
            if tactics.style == "SHORT_BUILDUP" and long_ball and f_owner < self.L * 0.4:
                success -= 0.10  # the plan forbids hoofing it from the back
            cross = crossing_zone and f_mate > self.L - self.cfg["box"] and abs(mate.y - self.W / 2) < self.cfg["box"]
            if cross:
                success -= 0.18
            success = max(0.08, min(0.97, success))
            progress = (f_mate - f_owner) / self.L
            v_mate = self.value(side, mate.x, mate.y)
            if cross:
                v_mate *= 0.55 + 0.25 * style[6]  # a header is worse than a shot on the ground
            mid_x, mid_y = (owner.x + mate.x) / 2, (owner.y + mate.y) / 2
            value = success * (v_mate + 0.02 * progress * progress_weight) - (1 - success) * self.value(1 - side, mid_x, mid_y) * risk
            if long_ball:
                value += style[2] * 0.02
            if width_bias and abs(mate.y - self.W / 2) > self.W * 0.3:
                value += width_bias * 0.012
            value += rng.random() * noise
            if value > best_value:
                best_kind, best_value, best_target = "pass", value, (mate, success, dist)

        # Through balls: race a runner against the defence into the space behind the line.
        opp_line_abs = self.L - self._last_defender_f(1 - side)
        for mate in self.team_agents[side]:
            if not mate.active or mate is owner or mate.role in ("GK", "DF") and tactics.mentality not in ("ATTACKING", "VERY_ATTACKING"):
                continue
            f_mate = self.fwd(side, mate.x)
            if f_mate < f_owner + 3 or abs(f_mate - opp_line_abs) > 5:
                continue
            space = min(16.0 if self.mode == "ELEVEN_A_SIDE" else 6.0, (self.L - 4.0) - opp_line_abs)
            if space < 5.0 * (1 if self.mode == "ELEVEN_A_SIDE" else 0.4):
                continue
            tpf = opp_line_abs + space * 0.8
            tx, ty = self.abs_x(side, tpf), mate.y + (self.W / 2 - mate.y) * 0.25
            run_speed = 5.0 + mate.pace * 0.033
            run_time = math.hypot(tx - mate.x, ty - mate.y) / run_speed
            def_time = min((math.hypot(tx - o.x, ty - o.y) / (5.0 + o.pace * 0.033) + (0.6 if o.role == "GK" else 0.0)
                            for o in opponents), default=9.0)
            dist = math.hypot(tx - owner.x, ty - owner.y)
            margin = def_time - run_time
            success = 1 / (1 + math.exp(-1.4 * (margin - 0.2))) * (1.02 - dist * 0.004 * (1.6 - pass_skill / 100)) - press * 0.08
            success = max(0.05, min(0.9, success))
            value = success * (self.value(side, tx, ty) + 0.02 * progress_weight) - (1 - success) * self.value(1 - side, (owner.x + tx) / 2, (owner.y + ty) / 2) * risk
            value += (style[5] * 0.012 if counter_phase else 0.0) + style[2] * 0.01 + rng.random() * noise
            if value > best_value:
                best_kind, best_value, best_target = "through", value, (mate, success, dist, (tx, ty), run_time)

        if owner.role != "GK":
            step = 4.0 if self.mode == "ELEVEN_A_SIDE" else 2.2
            cx = self.abs_x(side, min(self.L - 1, f_owner + step))
            cy = owner.y + (self.W / 2 - owner.y) * 0.12
            ahead = min(((o.x - cx) ** 2 + (o.y - cy) ** 2 for o in opponents), default=400.0) ** 0.5
            press_ahead = max(0.0, 1 - ahead / 7.0)
            in_box = self.fwd(side, cx) > self.L - self.cfg["box"]
            p_keep = 0.965 - 0.30 * press_ahead - 0.15 * press - (0.12 if in_box else 0.0) + (owner.skill(owner.dribbling) - 65) / 600
            v_new = self.value(side, cx, cy)
            value = p_keep * (v_new + 0.012 * progress_weight * step / self.L * 10) - (1 - p_keep) * self.value(1 - side, cx, cy) * risk
            value -= 0.0015 + 0.002 * held  # carries end: players look up and release
            value += rng.random() * noise
            if value > best_value:
                best_kind, best_value, best_target = "carry", value, (cx, cy)

        if best_kind == "shoot":
            self._shoot(owner)
        elif best_kind == "pass":
            mate, success, dist = best_target
            self._pass(owner, mate, success, dist)
        elif best_kind == "through":
            mate, success, dist, point, run_time = best_target
            self._pass(owner, mate, success, dist, target=point, min_duration=math.ceil(run_time))
            self.team_stats[side]["through_balls"] += 1
        elif best_kind == "carry":
            owner.x, owner.y = self._clamp(best_target[0], best_target[1])
            self._check_entry(owner)

    def _check_entry(self, agent: Agent) -> None:
        f = self.fwd(agent.side, agent.x)
        if f > self.L * 2 / 3 and f - 4 <= self.L * 2 / 3:
            self.team_stats[agent.side]["final_third_entries"] += 1
        if f > self.L - self.cfg["box"] and abs(agent.y - self.W / 2) < self.cfg["box"] * 1.25:
            self.team_stats[agent.side]["box_touches"] += 1

    def _pass(self, owner: Agent, mate: Agent, success: float, dist: float, target: tuple[float, float] | None = None, min_duration: int = 1) -> None:
        side = owner.side
        owner.stats["passes"] += 1
        self.team_stats[side]["passes"] += 1
        speed = 17.0 if dist < 25 else 21.0
        duration = max(1, min_duration, round(dist / speed))
        if target is not None:
            tx, ty = self._clamp(*target)
        else:
            lead = 2.0 if self.mode == "ELEVEN_A_SIDE" else 1.0
            tx = mate.x + (lead if side == 0 else -lead) * (1 if self.fwd(side, mate.x) > self.fwd(side, owner.x) else 0)
            tx, ty = self._clamp(tx, mate.y)
        outcome = "COMPLETE"
        interceptor = None
        if self.rng.random() >= success:
            # Find who reads the lane best; with nobody close the ball runs out.
            opponents = self.active(1 - side)
            def lane_distance(o: Agent) -> float:
                dx, dy = tx - owner.x, ty - owner.y
                t = max(0.0, min(1.0, ((o.x - owner.x) * dx + (o.y - owner.y) * dy) / max(1e-6, dx * dx + dy * dy)))
                return math.hypot(o.x - owner.x - t * dx, o.y - owner.y - t * dy) - o.defending / 40
            interceptor = min(opponents, key=lane_distance) if opponents else None
            if interceptor and lane_distance(interceptor) < 6.0:
                outcome = "INTERCEPTED"
                tx, ty = interceptor.x, interceptor.y
            else:
                outcome = "OUT"
                interceptor = None
                ty = -0.5 if mate.y < self.W / 2 else self.W + 0.5
        self.flight = {"fx": owner.x, "fy": owner.y, "tx": tx, "ty": ty, "start": self.tick, "arrive": self.tick + duration,
                       "kind": "pass", "outcome": outcome, "passer": owner, "receiver": mate, "interceptor": interceptor, "side": side}
        self.owner = None
        self.last_pass = (owner, self.tick)

    def _resolve_flight(self) -> None:
        f = self.flight
        assert f is not None
        self.bx, self.by = f["tx"], f["ty"]
        self.flight = None
        side = f["side"]
        passer: Agent = f["passer"]
        if f["outcome"] == "COMPLETE":
            receiver: Agent = f["receiver"]
            if not receiver.active:
                self.owner = None
                return
            # A tight marker contests the first touch.
            markers = [o for o in self.team_agents[1 - side] if o.active and o.role != "GK" and
                       (o.x - f["tx"]) ** 2 + (o.y - f["ty"]) ** 2 < 3.2]
            if markers:
                marker = max(markers, key=lambda o: o.defending)
                contest = 0.05 + (marker.skill(marker.defending) - receiver.skill(receiver.dribbling)) / 200
                if self.fwd(side, f["tx"]) > self.L - self.cfg["box"] * 1.3:
                    contest += 0.40
                if self.rng.random() < max(0.03, min(0.70, contest)):
                    passer.stats["losses"] += 1
                    marker.stats["interceptions"] += 1
                    self.team_stats[1 - side]["interceptions"] += 1
                    marker.x, marker.y = f["tx"], f["ty"]
                    if self._deflect_for_corner(side, f["tx"], f["ty"]):
                        return
                    self._give(marker)
                    return
            passer.stats["passes_completed"] += 1
            self.team_stats[side]["passes_completed"] += 1
            receiver.x, receiver.y = f["tx"], f["ty"]
            self._give(receiver)
            self._check_entry(receiver)
        elif f["outcome"] == "INTERCEPTED":
            interceptor: Agent = f["interceptor"]
            passer.stats["losses"] += 1
            if interceptor.active:
                interceptor.stats["interceptions"] += 1
                self.team_stats[interceptor.side]["interceptions"] += 1
                interceptor.x, interceptor.y = f["tx"], f["ty"]
                if self._deflect_for_corner(side, f["tx"], f["ty"]):
                    return
                self._give(interceptor)
            else:
                self.owner = None
        else:
            passer.stats["losses"] += 1
            y = 0.0 if f["ty"] < self.W / 2 else self.W
            self._stop("THROW_IN", 1 - side, f["tx"], y, 6)

    def _deflect_for_corner(self, attacking_side: int, x: float, y: float) -> bool:
        """Balls cut out inside the defenders' own box are often put behind."""
        if self.fwd(attacking_side, x) < self.L - self.cfg["box"] * 1.2 or self.rng.random() > 0.38:
            return False
        gx = self.goal_x(attacking_side)
        corner_y = 0.3 if y < self.W / 2 else self.W - 0.3
        self.team_stats[attacking_side]["corners"] += 1
        self._event("CORNER", attacking_side, None, gx, corner_y, "AWARDED")
        self._stop("CORNER", attacking_side, gx, corner_y, 14)
        return True

    def _clearance(self, agent: Agent) -> None:
        side = agent.side
        tx = self.abs_x(side, min(self.L * 0.62, self.fwd(side, agent.x) + self.L * 0.38))
        ty = self.rng.uniform(0.15, 0.85) * self.W
        receivers = [a for a in self.active(side) if a is not agent]
        mate = min(receivers, key=lambda a: (a.x - tx) ** 2 + (a.y - ty) ** 2) if receivers else agent
        self._pass(agent, mate, 0.45, math.hypot(tx - agent.x, ty - agent.y))

    def _shoot(self, shooter: Agent, header: bool = False, set_piece: bool = False) -> None:
        side = shooter.side
        rng = self.rng
        opponents = self.active(1 - side)
        nearest = min(((o.x - shooter.x) ** 2 + (o.y - shooter.y) ** 2 for o in opponents if o.role != "GK"), default=100.0) ** 0.5
        press = max(0.0, 1 - nearest / 3.0)
        xg = self.shot_xg(side, shooter.x, shooter.y) * (1 - 0.35 * press) * (0.5 + 0.5 * self._shot_lane_factor(shooter))
        if header:
            xg *= 0.32 + shooter.physical / 600
        if set_piece:
            xg = min(xg, 0.07)
        shooting = shooter.skill(shooter.shooting if not header else (shooter.physical + shooter.shooting) / 2)
        xg = max(0.005, min(0.85, xg * (0.80 + shooting / 250)))
        stats = self.team_stats[side]
        shooter.stats["shots"] += 1
        stats["shots"] += 1
        stats["xg"] += xg
        assist = None
        if self.last_pass and self.last_pass[0].side == side and self.last_pass[0] is not shooter and self.tick - self.last_pass[1] <= 4:
            assist = self.last_pass[0]
            assist.stats["key_passes"] += 1
        keeper = next((a for a in opponents if a.role == "GK"), None)
        keeping = keeper.skill(keeper.keeping) if keeper else 10.0
        p_goal = min(0.95, xg * (1 + (64 - keeping) / 110))
        p_on = max(p_goal + 0.05, min(0.75, 0.10 + shooting / 380 + xg * 0.9 - press * 0.10))
        blocked_p = 0.22 * press + 0.06
        gx = self.goal_x(side)
        goal_y = self.W / 2 + rng.uniform(-0.45, 0.45) * self.cfg["goal"]
        roll = rng.random()
        if xg >= 0.30:
            self._event("BIG_CHANCE", side, shooter, shooter.x, shooter.y, "", xg=xg)
        if roll < p_goal:
            shooter.stats["shots_on_target"] += 1
            shooter.stats["goals"] += 1
            stats["shots_on_target"] += 1
            stats["goals"] += 1
            self.score[side] += 1
            if assist:
                assist.stats["assists"] += 1
            self._event("SHOT", side, shooter, shooter.x, shooter.y, "GOAL", xg=xg, extra={"header": header})
            self._event("GOAL", side, shooter, gx, goal_y, "SCORED", other=assist, xg=xg, extra={"header": header})
            self._stop("KICK_OFF", 1 - side, self.L / 2, self.W / 2, 30)
        elif roll < p_on:
            shooter.stats["shots_on_target"] += 1
            stats["shots_on_target"] += 1
            if keeper:
                keeper.stats["saves"] += 1
            self.team_stats[1 - side]["saves"] += 1
            self._event("SHOT", side, shooter, shooter.x, shooter.y, "ON_TARGET", xg=xg, extra={"header": header})
            self._event("SAVE", 1 - side, keeper, gx, goal_y, "SAVED", other=shooter, xg=xg)
            parry = rng.random()
            if parry < 0.30:
                stats["corners"] += 1
                self._event("CORNER", side, None, gx, 0 if shooter.y < self.W / 2 else self.W, "AWARDED")
                self._stop("CORNER", side, gx, 0.3 if shooter.y < self.W / 2 else self.W - 0.3, 14)
            elif parry < 0.42:
                self.owner = None
                self.bx = self.abs_x(side, self.L - self.cfg["box"] * 0.5)
                self.by = goal_y
            elif keeper:
                self._give(keeper)
        elif roll < p_on + blocked_p * (1 - p_on):
            self._event("SHOT", side, shooter, shooter.x, shooter.y, "BLOCKED", xg=xg, extra={"header": header})
            if rng.random() < 0.40:
                stats["corners"] += 1
                self._event("CORNER", side, None, gx, 0 if shooter.y < self.W / 2 else self.W, "AWARDED")
                self._stop("CORNER", side, gx, 0.3 if shooter.y < self.W / 2 else self.W - 0.3, 14)
            else:
                self.owner = None
                self.bx = shooter.x + (1.5 if side == 1 else -1.5)
        else:
            self._event("SHOT", side, shooter, shooter.x, shooter.y, "OFF_TARGET", xg=xg, extra={"header": header})
            gk_x = self.abs_x(1 - side, self.cfg["box"] * 0.35)
            self._stop("GOAL_KICK", 1 - side, gk_x, self.W / 2, 8)

    # ------------------------------------------------------------------ movement
    def _clamp(self, x: float, y: float) -> tuple[float, float]:
        return max(0.5, min(self.L - 0.5, x)), max(0.5, min(self.W - 0.5, y))

    def _move_agents(self) -> None:
        L, W = self.L, self.W
        ball_x, ball_y = self.bx, self.by
        if self.flight is not None:
            ball_x, ball_y = self.flight["tx"], self.flight["ty"]
        in_play = self.dead is None and self.phase != "HALF_TIME"
        poss = self.owner.side if self.owner is not None else (self.flight["side"] if self.flight is not None else self.possession_side)
        dead_restart = self.dead["restart"] if self.dead else None
        chasers: dict[int, tuple[float, float]] = {}
        if self.flight is not None:
            target = self.flight["interceptor"] if self.flight["outcome"] == "INTERCEPTED" else self.flight["receiver"] if self.flight["outcome"] == "COMPLETE" else None
            if target is not None:
                chasers[target.index] = (self.flight["tx"], self.flight["ty"])
        elif self.owner is None and self.dead is None and self.phase in ("FIRST_HALF", "SECOND_HALF"):
            for side_ in (0, 1):
                near = [a for a in self.team_agents[side_] if a.active and a.role != "GK"]
                if near:
                    chaser = min(near, key=lambda a: (a.x - ball_x) ** 2 + (a.y - ball_y) ** 2)
                    chasers[chaser.index] = (ball_x, ball_y)
        moves: list[tuple[Agent, float, float, float, float]] = []
        for side in (0, 1):
            tactics = self.tactics[side]
            ment, press_cfg, style = MENTALITY[tactics.mentality], PRESSURE[tactics.pressure], STYLE[tactics.style]
            team = self.active(side)
            if not team:
                continue
            ball_f = self.fwd(side, ball_x)
            attacking = poss == side
            opp_line = self._last_defender_f(1 - side)
            offside_f = max(ball_f, L - opp_line) if attacking else L
            if attacking:
                line = max(0.12 * L, min(0.62 * L, (ment[0] + 0.07) * L + 0.42 * (ball_f - 0.45 * L)))
                length = ment[1] * L * 1.25
                width = style[3]
                follow = 0.18
            else:
                line = max(0.08 * L, min(0.52 * L, (ment[0] + press_cfg[4]) * L + 0.30 * (ball_f - 0.5 * L)))
                # The back line is never caught behind the ball: drop goal-side of it.
                line = min(line, max(4.5, ball_f - 3.0))
                length = ment[1] * L * 0.80 * (0.75 if ball_f < 0.3 * L else 1.0)
                width = 0.72
                follow = 0.38
            outfield = [a for a in team if a.role != "GK"]
            min_ax = min((a.ax for a in outfield), default=0.3)
            max_ax = max((a.ax for a in outfield), default=0.8)
            span = max(0.05, max_ax - min_ax)
            # Pressing: the closest players attack the ball inside the trigger zone.
            pressers: set[int] = set()
            supporters: set[int] = set()
            runners: set[int] = set()
            if in_play and not attacking and self.owner is not None:
                # How far the carrier has advanced toward our goal (0 = his own goal line).
                advanced = self.fwd(1 - side, self.owner.x) / L
                ranked = sorted(outfield, key=lambda a: (a.x - ball_x) ** 2 + (a.y - ball_y) ** 2)
                count = press_cfg[0]
                if advanced >= 1 - press_cfg[1]:
                    pressers = {a.index for a in ranked[:count]}
                elif (ranked[0].x - ball_x) ** 2 + (ranked[0].y - ball_y) ** 2 < 25:
                    pressers = {ranked[0].index}  # close enough to engage anyway
                if advanced > 0.72:
                    pressers.add(ranked[0].index)  # nobody walks into our box unchallenged
            elif in_play and attacking:
                ranked = sorted((a for a in outfield if a is not self.owner), key=lambda a: (a.x - ball_x) ** 2 + (a.y - ball_y) ** 2)
                supporters = {a.index for a in ranked[: ment[2] + (1 if tactics.style in ("POSSESSION", "SHORT_BUILDUP") else 0)]}
                forwards = sorted(outfield, key=lambda a: -a.ax)
                run_p = ment[3] + (0.25 if tactics.style in ("COUNTER", "DIRECT") else 0)
                if self.tick - self.possession_since < 12 and tactics.style == "COUNTER":
                    run_p += 0.3
                for a in forwards[:3]:
                    if self.rng.random() < run_p:
                        runners.add(a.index)
            # Forwards allowed to stay upfield when the ball is deep in our half.
            stay_up = {a.index for a in sorted(outfield, key=lambda a: -a.ax)[:ment[2]]} if not attacking else set()
            # Man-marking assignment in our half: each dangerous opponent gets one marker.
            marks: dict[int, Agent] = {}
            if in_play and not attacking:
                threats = [o for o in self.team_agents[1 - side] if o.active and o.role != "GK" and o is not self.owner
                           and self.fwd(side, o.x) < L * 0.55]
                threats.sort(key=lambda o: self.fwd(side, o.x))
                free = [a for a in outfield if a.index not in pressers]
                for opp in threats:
                    if not free:
                        break
                    marker = min(free, key=lambda a: (a.x - opp.x) ** 2 + (a.y - opp.y) ** 2)
                    if (marker.x - opp.x) ** 2 + (marker.y - opp.y) ** 2 < 400:
                        marks[marker.index] = opp
                        free.remove(marker)
            for agent in team:
                if agent.stun:
                    agent.stun -= 1
                if agent is self.owner:
                    agent.intensity = 0.7
                    self._drain(agent, 0.7, press_cfg[5])
                    continue
                intensity = 0.45
                if agent.role == "GK":
                    gf = 1.5 + max(0.0, min(9.0, (ball_f - 0) / L * 12)) if not attacking else min(0.30 * L, 2 + ball_f * 0.18)
                    gy = W / 2 + (ball_y - W / 2) * 0.25
                    tx, ty = self.abs_x(side, gf), gy
                elif dead_restart and self.dead and agent is self.dead["taker"]:
                    tx, ty = self.dead["x"], self.dead["y"]
                    intensity = 0.9
                else:
                    s = (agent.ax - min_ax) / span
                    tf = line + s * length
                    ty = W * (0.5 + (agent.ay - 0.5) * width) + (ball_y - W / 2) * follow
                    if attacking:
                        tf = min(tf, offside_f - 0.8)
                        if agent.index in supporters:
                            # Offer a short, open angle next to the ball.
                            angle_side = 1 if agent.ay >= 0.5 else -1
                            tf = ball_f + (2.5 if agent.ax > (self.owner.ax if self.owner else 0.5) else -4.0)
                            ty = ball_y + angle_side * (7.0 if self.mode == "ELEVEN_A_SIDE" else 3.5)
                            intensity = 0.75
                        if agent.index in runners:
                            tf = max(tf, min(offside_f - 0.5, ball_f + 18.0))
                            intensity = 1.0
                    else:
                        if ball_f < 0.36 * L and agent.index not in stay_up and tf > ball_f + 1.5:
                            # Low block: get behind the ball and protect the area.
                            tf = max(ball_f - 2.0, min(tf, ball_f + 1.5))
                            intensity = max(intensity, 0.9)
                        if agent.index in pressers and self.owner is not None:
                            tf, ty = self.fwd(side, self.owner.x), self.owner.y
                            intensity = 1.0
                        else:
                            mark = marks.get(agent.index)
                            if mark is not None:
                                # Goal-side marking: stand between the opponent and our goal.
                                gx_f, gy = 0.0, W / 2
                                mf = self.fwd(side, mark.x)
                                vx, vy = gx_f - mf, gy - mark.y
                                norm = math.hypot(vx, vy) or 1.0
                                gap = 1.6 if mf < L * 0.3 else 3.0
                                tf, ty = mf + vx / norm * gap, mark.y + vy / norm * gap
                                intensity = 0.85
                        if self.fwd(side, agent.x) > tf + 8:
                            intensity = 0.95  # recovery run behind the ball
                        elif (agent.x - ball_x) ** 2 + (agent.y - ball_y) ** 2 < 400:
                            intensity = max(intensity, 0.8)  # track runners near the ball
                    if dead_restart == "KICK_OFF":
                        spot = self._formation_spot(agent, kickoff=True)
                        tf, ty = self.fwd(side, spot[0]), spot[1]
                    tx = self.abs_x(side, max(1.0, min(L - 1.0, tf)))
                    ty = max(1.0, min(W - 1.0, ty))
                if agent.index in chasers:
                    tx, ty = chasers[agent.index]
                    intensity = 1.0
                moves.append((agent, tx, ty, intensity, press_cfg[5] * (1.0 + 0.12 * max(0, ment[2] - 1))))
        # Simultaneous update: every target above was computed from the same snapshot,
        # so neither team reacts to positions the other has already changed this tick.
        for agent, tx, ty, intensity, drain_factor in moves:
            top = 5.0 + agent.pace * 0.033
            speed = top * (0.66 + 0.34 * agent.stamina) * intensity
            dx, dy = tx - agent.x, ty - agent.y
            dist = math.hypot(dx, dy)
            if dist > 0.05:
                move = min(dist, speed)
                agent.x += dx / dist * move
                agent.y += dy / dist * move
                agent.stats["distance"] += move
                self.team_stats[agent.side]["distance"] += move
                actual = move / top
            else:
                actual = 0.1
            agent.intensity = actual
            self._drain(agent, actual, drain_factor)

    def _drain(self, agent: Agent, intensity: float, factor: float) -> None:
        drain = (0.000032 + 0.000115 * intensity * intensity * factor) * (1.18 - agent.physical / 250)
        agent.stamina = max(0.25, agent.stamina - drain)

    def _last_defender_f(self, side: int) -> float:
        outfield = [self.fwd(side, a.x) for a in self.active(side) if a.role != "GK"]
        return min(outfield) if outfield else 0.0

    # ------------------------------------------------------------------ output
    def _record_frame(self) -> None:
        players = []
        for agent in self.agents:
            if agent.active:
                players.extend((round(agent.x / self.L, 4), round(agent.y / self.W, 4)))
            else:
                players.extend((-1, -1))
        owner = self.owner.index if self.owner is not None else -1
        self.frames.append((self.tick, round(self.bx / self.L, 4), round(self.by / self.W, 4), owner, players))

    def frames_since(self, tick: int, limit: int = 400) -> list[dict[str, object]]:
        rows = [frame for frame in self.frames if frame[0] > tick]
        return [{"t": t, "b": [bx, by, owner], "p": players} for t, bx, by, owner, players in rows[-limit:]]

    def minute(self) -> float:
        return round(self.tick / 60, 2)

    def statistics(self) -> dict[str, dict[str, float]]:
        total = max(1, self.team_stats[0]["possession_ticks"] + self.team_stats[1]["possession_ticks"])
        result = {}
        for side in (0, 1):
            stats = dict(self.team_stats[side])
            stats["possession"] = round(stats["possession_ticks"] * 100 / total, 1)
            stats["xg"] = round(stats["xg"], 2)
            stats["distance"] = round(stats["distance"] / 1000, 1)
            stats["pass_accuracy"] = round(stats["passes_completed"] * 100 / max(1, stats["passes"]), 1)
            active = [a for a in self.team_agents[side] if a.entered_tick is not None]
            stats["avg_stamina"] = round(sum(a.stamina for a in self.active(side)) / max(1, len(self.active(side))), 3)
            stats["players_used"] = len(active)
            result[self.clubs[side]] = stats
        return result

    def rating(self, agent: Agent) -> float:
        s = agent.stats
        conceded = self.score[1 - agent.side]
        played = ((agent.left_tick if agent.left_tick is not None else self.tick) - (agent.entered_tick or 0)) / FULL_TIME_TICK
        if agent.entered_tick is None or played <= 0:
            return 0.0
        accuracy = s["passes_completed"] / s["passes"] if s["passes"] else 0.8
        value = 6.2 + s["goals"] * 1.0 + s["assists"] * 0.6 + s["key_passes"] * 0.12 + s["shots_on_target"] * 0.12
        value += (s["tackles"] + s["interceptions"]) * 0.07 + s["dribbles"] * 0.05 + s["saves"] * 0.28
        value += (accuracy - 0.8) * 1.5 * min(1.0, s["passes"] / 20) - s["losses"] * 0.025
        if agent.role in ("GK", "DF"):
            value -= conceded * 0.25 * played
            if conceded == 0 and played > 0.6:
                value += 0.4
        value -= agent.yellow * 0.3 + (1.5 if agent.sent_off else 0)
        if self.score[agent.side] > self.score[1 - agent.side]:
            value += 0.15
        return round(max(3.0, min(10.0, value)), 1)

    def player_views(self, side: int) -> list[dict[str, object]]:
        rows = []
        for agent in self.team_agents[side]:
            rows.append({
                "id": agent.id, "name": agent.name, "number": agent.number, "role": agent.role, "position": agent.position,
                "overall": agent.overall, "index": agent.index, "on_pitch": agent.active, "sent_off": agent.sent_off,
                "yellow_cards": agent.yellow, "stamina": round(agent.stamina, 3), "entered_tick": agent.entered_tick,
                "left_tick": agent.left_tick, "available": agent.entered_tick is None and not agent.active,
                "rating": self.rating(agent), "stats": {k: (round(v) if k == "distance" else v) for k, v in agent.stats.items()},
                "attributes": {"pace": round(agent.pace), "passing": round(agent.passing), "shooting": round(agent.shooting),
                               "dribbling": round(agent.dribbling), "defending": round(agent.defending),
                               "physical": round(agent.physical), "keeping": round(agent.keeping)},
            })
        return rows

    def summary(self) -> dict[str, object]:
        return {
            "id": self.match_id, "home": self.clubs[0], "away": self.clubs[1], "tick": self.tick, "minute": self.minute(),
            "phase": self.phase, "home_goals": self.score[0], "away_goals": self.score[1],
            "home_xg": round(self.team_stats[0]["xg"], 3), "away_xg": round(self.team_stats[1]["xg"], 3),
            "statistics": self.statistics(), "events": list(self.events),
            "tactics": {"home": self.tactics[0].view(), "away": self.tactics[1].view()},
            "formations": {"home": self.inputs[0].formation_code, "away": self.inputs[1].formation_code},
            "lineups": {"home": self.player_views(0), "away": self.player_views(1)},
            "substitutions": {"home": {"used": self.subs_used[0], "windows_used": self.windows_used[0], "pending": len(self.pending_subs[0])},
                              "away": {"used": self.subs_used[1], "windows_used": self.windows_used[1], "pending": len(self.pending_subs[1])},
                              "max": self.cfg["max_subs"], "windows": self.cfg["windows"] if self.cfg["windows"] < 99 else None},
            "ball_in_play": self.dead is None and self.phase in ("FIRST_HALF", "SECOND_HALF"),
            "pitch": {"length": self.L, "width": self.W, "goal": self.cfg["goal"], "box": self.cfg["box"]},
        }


def replay_engine(match_id: str, mode: str, home: TeamInput, away: TeamInput, seed: int,
                  command_log: list[dict[str, object]], until_tick: int) -> MatchEngine:
    """Rebuild an engine deterministically from its inputs and command log."""
    engine = MatchEngine(match_id, mode, home, away, seed)
    for command in sorted(command_log, key=lambda c: int(c["tick"])):
        engine.advance_to(int(command["tick"]))
        side = int(command["side"])
        if command["kind"] == "TACTICS":
            from app.domain.tactics import tactics_from_payload
            engine.queue_tactics(side, tactics_from_payload(command["tactics"]), str(command["command_id"]))
        elif command["kind"] == "SUBSTITUTION":
            try:
                engine.queue_substitution(side, str(command["out"]), str(command["in"]), str(command["command_id"]))
            except ValueError:
                pass
    engine.advance_to(until_tick)
    return engine
