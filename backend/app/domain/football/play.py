"""One action of a decisive moment, played by the V7 physics (authoritative).

Phases: PREP (the carrier turns his body and plants the foot; the ball is at his feet)
-> CONTACT (the ball leaves at the instant of the kick, from where it is) -> FREE BALL
(real physics; everybody keeps playing: receivers run onto the path, defenders commit
to intercept, the keeper reads the real trajectory) -> RECEPTION (first touch in motion:
clean, heavy or missed) -> SETTLE (a few touches until the ball is under control) ->
the next decision opens with everybody still moving. A carry is a dribble by touches:
the ball rolls ahead, is caught up with and pushed again, and is exposed in between.

Nothing here knows a future decision or a random draw before it happens. Same inputs and
seed give the same frames.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from app.domain.football.brain import TeamBrain
from app.domain.football.keeper import Keeper
from app.domain.football.world import (
    ACT_DRIBBLE,
    ACT_GK_HOLD,
    ACT_HEADER,
    ACT_KICK,
    ACT_NONE,
    ACT_RECEIVE,
    ACT_STUMBLE,
    ACT_TACKLE,
    BALL_RADIUS,
    BRAIN_DT,
    CARRY_RANGE,
    DRIBBLE_SPEED,
    DT,
    FRAME_DT,
    LOFT_ANGLE,
    LOFT_RANGE,
    MAX_ACTION_SECONDS,
    PASS_SPEED,
    ROLL_DECEL,
    SHOT_LIFT,
    SHOT_SPEED,
    Athlete,
    BallState,
    Cue,
    ball_step,
    clamp,
    dist,
    move,
    predict_ball,
    separate,
    solve_loft,
    wrap,
)

POST_RADIUS = 0.06
PASS_ASSIST_ANGLE = 0.24
PASS_ASSIST = (0.35, 0.35)
DEFENCE_REACTION = (0.30, 0.14)   # s = a - b * defending/100 before the defence re-plans after a strike
DIFFICULTY = {   # bots differ by decisions and reactions, never by hidden attributes
    "EASY": {"defence": 0.10, "keeper": 0.06, "intercept": -0.07, "tackle": -0.06},
    "NORMAL": {"defence": 0.0, "keeper": 0.0, "intercept": 0.0, "tackle": 0.0},
    "HARD": {"defence": -0.05, "keeper": -0.03, "intercept": 0.05, "tackle": 0.05},
}
SETTLE_SECONDS = 0.42


@dataclass
class PlayResult:
    outcome: str                    # CONTROLLED, LOST, GOAL, SAVED_HELD, OUT, CORNER
    frames: list[list[float]]
    receiver: str | None = None
    detail: str = ""
    shot: bool = False
    on_target: bool = False
    xg: float = 0.0
    keeper: str | None = None
    lost_to: str | None = None
    completed_pass: bool = False
    shooter: str | None = None
    post: bool = False
    cues: list[dict[str, object]] = field(default_factory=list)


class Play:
    def __init__(self, bodies: list[Athlete], ball: BallState, cfg: dict[str, float], rng: random.Random, boost: float = 0.0,
                 tactics: dict[str, str] | None = None, difficulty: str = "NORMAL") -> None:
        self.L, self.W, self.goal, self.goal_h = cfg["length"], cfg["width"], cfg["goal"], cfg["goal_height"]
        self.s = self.L / 105.0
        self.bodies, self.ball, self.rng, self.boost = bodies, ball, rng, boost
        self.by_id = {b.id: b for b in bodies}
        self.diff = DIFFICULTY.get(difficulty, DIFFICULTY["NORMAL"])
        self.attackers = [b for b in bodies if b.team == "A" and b.role != "GK"]
        self.defenders = [b for b in bodies if b.team == "D" and b.role != "GK"]
        gk = next((b for b in bodies if b.team == "D" and b.role == "GK"), None)
        self.keeper = Keeper(gk, self.L, self.W, self.goal, self.goal_h, self.s, rng, self.diff["keeper"]) if gk else None
        self.own_keeper = next((b for b in bodies if b.team == "A" and b.role == "GK"), None)
        self.brain = TeamBrain(bodies, self.L, self.W, self.s, tactics, difficulty)
        self.cues: list[Cue] = []
        self.frames: list[list[float]] = []
        self.t = 0.0
        self.next_frame = 0.0
        self.next_plan = 0.0
        self.owner: Athlete | None = None
        self.receiver: Athlete | None = None
        self.interceptors: set[str] = set()
        self.pending: tuple[str, float, float, float] | None = None
        self.kick_at = 0.0
        self.kicker: Athlete | None = None
        self.kick_t = -9.0
        self.action = ""
        self.shot_live = False
        self.shot_t0 = 0.0
        self.was_shot = False
        self.shooter: Athlete | None = None
        self.on_target = False
        self.xg = 0.0
        self.screened = False
        self.post = False
        self.dribbler: Athlete | None = None
        self.dribble_mode = ""
        self.dribble_target = (0.0, 0.0)
        self.dribble_deadline = 0.0
        self.settle_until = 0.0
        self.last_touch_t = -9.0
        self.cool: dict[str, float] = {}
        self.tackle_cool: dict[str, float] = {}
        self.headed: set[str] = set()
        self.completed_pass = False
        self.after_parry_until: float | None = None

    # ------------------------------------------------------------ recording
    def cue(self, kind: str, body: Athlete | None, **extra: object) -> None:
        self.cues.append(Cue(self.t, kind, body.id if body else None, extra))

    def record(self) -> None:
        b = self.ball
        row = [round(self.t, 3), round(b.x / self.L, 4), round(b.y / self.W, 4), round(max(0.0, b.z), 2)]
        for body in self.bodies:
            row += [round(body.x / self.L, 4), round(body.y / self.W, 4), round(body.facing, 2), int(body.act)]
        self.frames.append(row)

    # ------------------------------------------------------------ helpers
    def pressure_on(self, body: Athlete) -> float:
        nearest = min((dist(body.x, body.y, d.x, d.y) for d in self.defenders), default=20.0)
        return clamp(1 - nearest / 4.5, 0.0, 1.0)

    def xg_at(self, x: float, y: float) -> float:
        d = dist(x, y, self.L, self.W / 2)
        angle = abs(math.atan2(self.goal * (self.L - x), (self.L - x) ** 2 + (y - self.W / 2) ** 2 - (self.goal / 2) ** 2))
        return round(clamp(0.9 * angle * math.exp(-d * (105 / self.L) / 22), 0.01, 0.85), 3)

    def feet(self, body: Athlete, ahead: float = 0.42) -> tuple[float, float]:
        return body.x + math.cos(body.facing) * ahead, body.y + math.sin(body.facing) * ahead

    def attach(self, body: Athlete) -> None:
        fx, fy = self.feet(body)
        b = self.ball
        b.x, b.y, b.z, b.vx, b.vy, b.vz = fx, fy, 0.0, body.vx, body.vy, 0.0
        b.owner = body.id

    # ------------------------------------------------------------ entry point
    def run(self, carrier_id: str, action: str, tx: float, ty: float, power: float) -> PlayResult:
        carrier = self.by_id[carrier_id]
        self.carrier = carrier
        self.action = action
        self.owner = carrier
        self.attach(carrier)
        for body in self.bodies:
            body.act = ACT_NONE
        self.record()
        self.next_frame = FRAME_DT
        if action == "CARRY":
            dx, dy = tx - carrier.x, ty - carrier.y
            d = math.hypot(dx, dy) or 1.0
            reach = min(d, (CARRY_RANGE[0] + CARRY_RANGE[1] * power) * self.s)
            self.start_dribble(carrier, "CARRY", (carrier.x + dx / d * reach, carrier.y + dy / d * reach))
            self.dribble_deadline = reach / max(3.0, carrier.top_speed * 0.8) + 1.6
            self.cue("CARRY", carrier)
            self.owner = None
            self.ball.owner = None
            # First touch of the carry: push the ball the way the coach asked.
            self.touch(carrier, math.atan2(dy, dx), first=True)
        else:
            aim = math.atan2(ty - carrier.y, tx - carrier.x)
            turn = abs(wrap(aim - carrier.facing))
            prep = clamp(0.12 + turn * 0.16 + (0.06 if action in ("SHOT", "LOFT") else 0.0), 0.12, 0.42)
            self.pending = (action, tx, ty, power)
            self.kick_at = prep
            carrier.look = (tx, ty)
            # Plant the foot: keep some of the run (a pass on the move), brake more for a shot.
            keep = 0.55 if action == "PASS" else 0.3
            carrier.tx, carrier.ty, carrier.intensity = carrier.x + carrier.vx * 0.6, carrier.y + carrier.vy * 0.6, keep
            carrier.act = ACT_KICK
        while self.t < MAX_ACTION_SECONDS - 1e-9:
            result = self.tick()
            if result is not None:
                return self.finish(result)
        return self.finish(self.by_proximity())

    # ------------------------------------------------------------ main step
    def tick(self) -> PlayResult | None:
        self.t += DT
        t, b = self.t, self.ball
        if t >= self.next_plan:
            self.next_plan += BRAIN_DT
            skip = {x.id for x in (self.owner, self.receiver, self.dribbler) if x is not None} | self.interceptors
            self.brain.plan(t, b, self.owner or self.dribbler, self.receiver, skip)
            self.plan_ball_runs()
        if self.pending and t >= self.kick_at:
            self.kick(*self.pending)
            self.pending = None
        if self.dribbler is not None:
            res = self.dribble_step()
            if res is not None:
                return res
        p0 = (b.x, b.y, b.z)
        # Everybody moves (the keeper has his own agent).
        for body in self.bodies:
            if self.keeper and body is self.keeper.b:
                continue
            if body.act in (ACT_KICK, ACT_RECEIVE, ACT_TACKLE, ACT_HEADER, ACT_DRIBBLE, ACT_STUMBLE) and t >= body.act_until and body is not self.owner:
                body.act = ACT_NONE if body is not self.dribbler else ACT_DRIBBLE
            if body is self.dribbler:
                dmax = body.top_speed * (DRIBBLE_SPEED[0] + DRIBBLE_SPEED[1] * body.dribbling / 100)
                move(body, t, top=dmax)
            elif body is self.own_keeper:
                body.tx, body.ty, body.intensity = body.ax, body.ay, 0.4
                move(body, t)
            else:
                move(body, t)
        owner_for_keeper = self.owner or self.dribbler
        if self.keeper:
            self.keeper.update(t, b, self.shot_live, self.shot_t0, self.screened, owner_for_keeper)
        if self.owner is not None and b.owner == self.owner.id:
            self.attach(self.owner)
        elif self.keeper and b.owner == self.keeper.b.id:
            kb = self.keeper.b
            b.x, b.y, b.z, b.vx, b.vy, b.vz = kb.x - 0.3, kb.y, 1.0, 0.0, 0.0, 0.0
        else:
            ball_step(b)
        separate(self.bodies)
        res = self.goal_line(p0)
        if res is None:
            res = self.keeper_contact(p0)
        if res is None and b.owner is None:
            res = self.header(p0)
        if res is None and b.owner is None:
            res = self.player_contact(p0)
        if res is None and self.dribbler is not None and b.owner is None:
            res = self.tackles()
        while t >= self.next_frame - 1e-9:
            self.record()
            self.next_frame += FRAME_DT
        if res is not None:
            return res
        if self.after_parry_until is not None and t > self.after_parry_until and b.owner is None:
            return self.by_proximity()
        return None

    # ------------------------------------------------------------ the kick
    def kick(self, action: str, tx: float, ty: float, power: float) -> None:
        c, b, rng, s = self.carrier, self.ball, self.rng, self.s
        aim = math.atan2(ty - c.y, tx - c.x)
        turn = abs(wrap(aim - c.facing))
        pressure = self.pressure_on(c)
        body_pen = (1 + 0.55 * max(0.0, turn - 0.5)) * (1 + 0.25 * c.speed / 9)
        vz = 0.0
        intended = None
        if action == "PASS":
            v0 = PASS_SPEED[0] + PASS_SPEED[1] * power
            sd = 0.07 * (1.3 - c.passing / 100) * (1 + 0.9 * pressure) * (0.7 + 0.6 * power) * body_pen
            intended, aim = self.assist(c, aim, tx, ty)
            horizontal = v0
        elif action == "LOFT":
            distance = (LOFT_RANGE[0] + LOFT_RANGE[1] * power) * s
            distance *= 1 + rng.gauss(0, 0.07 * (1.2 - c.passing / 100))
            angle = LOFT_ANGLE[0] + LOFT_ANGLE[1] * (1 - power)
            intended, aim = self.assist(c, aim, tx, ty, lofted=True)
            v0 = solve_loft(distance, angle)
            sd = 0.055 * (1.3 - c.passing / 100) * (1 + 0.8 * pressure) * body_pen
            horizontal, vz = v0 * math.cos(angle), v0 * math.sin(angle)
        else:  # SHOT
            v0 = SHOT_SPEED[0] + SHOT_SPEED[1] * power
            sd = 0.05 * (1.35 - c.shooting / 100) * (1 + pressure) * (0.75 + 1.6 * max(0.0, power - 0.55)) * body_pen
            vz = max(0.0, SHOT_LIFT[0] + SHOT_LIFT[1] * max(0.0, power - 0.35) + rng.gauss(0, 1.0 * (1.35 - c.shooting / 100) * (1 + pressure * 0.5)))
            horizontal = math.sqrt(max(1.0, v0 * v0 - vz * vz))
            self.shot_live, self.shot_t0, self.was_shot, self.shooter = True, self.t, True, c
            self.xg = self.xg_at(c.x, c.y)
            ahead = (c.x + math.cos(aim) * 6, c.y + math.sin(aim) * 6)
            self.screened = any(dist(d.x, d.y, *ahead) < 1.3 for d in self.defenders)
        angle = aim + rng.gauss(0, sd)
        b.owner = None
        self.owner = None
        b.vx, b.vy, b.vz = math.cos(angle) * horizontal, math.sin(angle) * horizontal, vz
        b.last_touch = "A"
        if action == "SHOT":
            self.on_target = self.predicted_on_target()
        self.kicker, self.kick_t = c, self.t
        c.act, c.act_until = ACT_KICK, self.t + 0.25
        c.look = None
        c.tx, c.ty, c.intensity = c.x + c.vx * 0.8 + math.cos(aim) * 1.5, c.y + c.vy * 0.8 + math.sin(aim) * 1.5, 0.6
        self.cue("KICK", c, action=action, power=round(power, 2), windup=round(self.t, 2))
        if action in ("PASS", "LOFT"):
            self.brain.passer, self.brain.passer_until = c.id, self.t + 1.8
            self.receiver = intended or self.best_receiver()
        avg_def = sum(d.defending for d in self.defenders) / max(1, len(self.defenders))
        self.brain.react_until = self.t + DEFENCE_REACTION[0] - DEFENCE_REACTION[1] * avg_def / 100 + self.diff["defence"] - self.boost
        self.plan_ball_runs()

    def predicted_on_target(self) -> bool:
        for _, x, y, z in predict_ball(self.ball, 3.0, 0.025):
            if x >= self.L:
                return abs(y - self.W / 2) <= self.goal / 2 and z <= self.goal_h
        return False

    def assist(self, carrier: Athlete, aim: float, tx: float, ty: float, lofted: bool = False) -> tuple[Athlete | None, float]:
        """Moderate assistance: a team-mate close to the drawn line is the intended receiver and
        the ball is bent part of the way to where he is running. Never a lock-on; passes into
        empty space stay exactly where the coach drew them."""
        want = dist(carrier.x, carrier.y, tx, ty)
        best, best_score = None, 9.0
        for a in self.attackers:
            if a is carrier:
                continue
            d = dist(a.x, a.y, carrier.x, carrier.y)
            if d < 2.5 or not (0.3 * want <= d <= 1.6 * want + 4):
                continue
            diff = abs(wrap(math.atan2(a.y - carrier.y, a.x - carrier.x) - aim))
            if diff > PASS_ASSIST_ANGLE:
                continue
            score = diff + abs(d - want) / max(want, 1) * 0.15
            if score < best_score:
                best, best_score = a, score
        if best is None:
            return None, aim
        lead = min(1.2, dist(best.x, best.y, carrier.x, carrier.y) / 14)
        lx, ly = best.x + best.vx * lead, best.y + best.vy * lead
        correction = wrap(math.atan2(ly - carrier.y, lx - carrier.x) - aim) * (PASS_ASSIST[0] + PASS_ASSIST[1] * carrier.passing / 100)
        return best, aim + correction

    def best_receiver(self) -> Athlete | None:
        """Who reads this ball best: earliest arrival on its real path (not just the nearest)."""
        path = predict_ball(self.ball, 3.5, 0.1)
        best, best_t = None, 9e9
        for a in self.attackers:
            if a is self.kicker:
                continue
            for pt, px, py, pz in path:
                if pz > 2.4:
                    continue
                if a.time_to(px, py) <= pt + 0.1:
                    if pt < best_t:
                        best, best_t = a, pt
                    break
        return best

    def plan_ball_runs(self) -> None:
        """Receiver runs onto the ball's path; up to two defenders commit to cut it out if they
        can get there first (the others stay in shape)."""
        b = self.ball
        if b.owner is not None or self.dribbler is not None:
            self.interceptors.clear()
            return
        if b.ground_speed < 0.3 and not b.airborne:
            path = [(0.0, b.x, b.y, b.z)]
        else:
            path = predict_ball(b, 3.0, 0.1)
        if not path:
            return
        if self.receiver is None and not self.shot_live:
            # Loose ball: the quickest attacker goes for it (the defence below does the same).
            self.receiver = min(self.attackers, key=lambda a: min((a.time_to(px, py) - pt for pt, px, py, pz in path if pz < 1.0), default=9.0))
        receiver_t = 9.0
        if self.receiver is not None and not self.shot_live:
            r = self.receiver
            spot = next(((pt, px, py) for pt, px, py, pz in path if pz < 2.2 and r.time_to(px, py) <= pt + 0.05), None)
            if spot is None:
                spot = (path[-1][0], path[-1][1], path[-1][2])
            r.tx, r.ty, r.intensity, r.look = spot[1], spot[2], 1.0, (b.x, b.y)
            receiver_t = spot[0]
        if self.t < self.brain.react_until or self.shot_live:
            return
        commits: list[tuple[float, Athlete, float, float]] = []
        for d in self.defenders:
            for pt, px, py, pz in path:
                if pz > 2.0 or pt < 0.15:
                    continue
                # Commit only to a point he really reaches before the ball AND before the receiver.
                if d.time_to(px, py, 0.1) <= pt - 0.05:
                    if pt < receiver_t + 0.05:
                        commits.append((pt, d, px, py))
                    break
        commits.sort(key=lambda c: c[0])
        self.interceptors = set()
        for _pt, d, px, py in commits[:2]:
            d.tx, d.ty, d.intensity, d.look = px, py, 1.0, (b.x, b.y)
            self.interceptors.add(d.id)

    # ------------------------------------------------------------ dribbling (carry and settle)
    def start_dribble(self, body: Athlete, mode: str, target: tuple[float, float]) -> None:
        self.dribbler, self.dribble_mode, self.dribble_target = body, mode, target
        body.act = ACT_DRIBBLE
        self.receiver = None
        self.interceptors.clear()

    def inside(self, x: float, y: float, direction: float, length: float) -> float:
        """A touch never runs the ball out on purpose: near a line the direction bends back
        towards the pitch (and the attacking goal) — the player protects the ball."""
        margin = 1.8
        for _ in range(8):
            ex, ey = x + math.cos(direction) * (length + 1.0), y + math.sin(direction) * (length + 1.0)
            if margin < ex < self.L - 0.8 and margin < ey < self.W - margin:
                return direction
            goal = math.atan2(self.W / 2 - y, self.L - 6 * self.s - x)
            direction += clamp(wrap(goal - direction), -0.35, 0.35)
        return direction

    def touch(self, body: Athlete, direction: float, first: bool = False) -> None:
        b, rng = self.ball, self.rng
        if self.dribble_mode == "SETTLE":
            direction = self.inside(b.x, b.y, direction, 1.6)
        pressure = self.pressure_on(body)
        nearest = min((dist(b.x, b.y, d.x, d.y) for d in self.defenders), default=20.0)
        base = 3.2 if nearest > 8 * self.s ** 0.5 else 2.2 if nearest > 4 else 1.3
        length = base * (1.15 - 0.35 * body.dribbling / 100)
        if self.dribble_mode == "CARRY":
            length = min(length, max(0.8, dist(b.x, b.y, *self.dribble_target)))
        else:
            length = min(length, 1.6)
        ang = direction + rng.gauss(0, 0.05 * (1.3 - body.dribbling / 100) * (1 + pressure))
        along = max(0.0, body.vx * math.cos(ang) + body.vy * math.sin(ang))
        v = along + math.sqrt(2 * (ROLL_DECEL + 0.6) * length)
        b.vx, b.vy, b.vz, b.z = math.cos(ang) * v, math.sin(ang) * v, 0.0, 0.0
        b.owner = None
        b.last_touch = "A"
        self.last_touch_t = self.t
        body.act, body.act_until = ACT_DRIBBLE, self.t + 0.15

    def dribble_step(self) -> PlayResult | None:
        d, b, t = self.dribbler, self.ball, self.t
        if self.dribble_mode == "CARRY":
            gx, gy = self.dribble_target
        else:
            gx, gy = d.x + d.vx * 0.8 + math.cos(d.facing) * 1.0, d.y + d.vy * 0.8 + math.sin(d.facing) * 1.0
            gx, gy = clamp(gx, 2.0, self.L - 2.0), clamp(gy, 2.0, self.W - 2.0)
        fx, fy = self.feet(d, 0.38)
        gap = dist(fx, fy, b.x, b.y)
        direction = math.atan2(gy - b.y, gx - b.x)
        # Run to meet the ball a little behind it (the foot arrives at the ball, not past it).
        lead = 0.22
        px, py = b.x + b.vx * lead - math.cos(direction) * 0.35, b.y + b.vy * lead - math.sin(direction) * 0.35
        d.tx, d.ty, d.intensity, d.look = px, py, 1.0, None
        remaining = dist(b.x, b.y, gx, gy)
        if self.dribble_mode == "SETTLE" and t >= self.settle_until and gap < 0.75:
            return self.gather(d, f"{d.name} domina")
        if self.dribble_mode == "CARRY":
            if (remaining < 1.1 and gap < 0.8) or (t > self.dribble_deadline and gap < 0.9):
                return self.gather(d, f"{d.name} avança")
            if t > self.dribble_deadline + 1.2:
                # Lost the ball's touch for good: it is a loose ball now.
                self.dribbler = None
                self.receiver = None
                return None
        if gap < 0.5 and b.z < 0.35 and t - self.last_touch_t > 0.22:
            ahead = b.vx * math.cos(direction) + b.vy * math.sin(direction)
            along = d.vx * math.cos(direction) + d.vy * math.sin(direction)
            if ahead - along < 0.9:
                self.touch(d, direction)
        return None

    def gather(self, body: Athlete, detail: str) -> PlayResult:
        self.dribbler = None
        self.owner = body
        self.attach(body)
        body.act = ACT_NONE
        return PlayResult("CONTROLLED", self.frames, receiver=body.id, detail=detail, completed_pass=self.completed_pass)

    def tackles(self) -> PlayResult | None:
        d, b, t = self.dribbler, self.ball, self.t
        fx, fy = self.feet(d, 0.38)
        exposure = clamp((dist(fx, fy, b.x, b.y) - 0.3) / 1.3, 0.0, 1.0)
        for x in self.defenders:
            if t < self.tackle_cool.get(x.id, 0.0) or t < x.slow_until:
                continue
            near_ball = dist(x.x, x.y, b.x, b.y)
            near_body = dist(x.x, x.y, d.x, d.y)
            if near_ball > 1.15 and near_body > 0.95:
                continue
            # A defender only goes to ground when he can actually get a foot on the ball.
            if not (exposure > 0.2 or near_body < 0.95 or near_ball < 0.75):
                continue
            self.tackle_cool[x.id] = t + 1.3
            x.act, x.act_until = ACT_TACKLE, t + 0.35
            chance = clamp(0.27 + (x.defending - d.dribbling) / 160 + (x.physical - d.balance) / 400 + 0.28 * exposure
                           + self.boost + self.diff["tackle"] - (d.agility - 60) / 500, 0.08, 0.85)
            roll = self.rng.random()
            if roll < chance:
                self.cue("TACKLE", x)
                if roll < chance * 0.55:
                    self.dribbler = None
                    self.owner = x
                    self.attach(x)
                    return PlayResult("LOST", self.frames, detail=f"Desarme de {x.name}", lost_to=x.id)
                # Poked loose: nobody has it.
                ang = math.atan2(b.y - x.y, b.x - x.x) + self.rng.uniform(-0.9, 0.9)
                sp = self.rng.uniform(3.0, 6.5)
                b.vx, b.vy, b.owner, b.last_touch = math.cos(ang) * sp, math.sin(ang) * sp, None, "D"
                d.slow_until = t + 0.35
                self.dribbler = None
                self.receiver = None
                self.plan_ball_runs()
                return None
            x.slow_until, x.act, x.act_until = t + 0.75, ACT_STUMBLE, t + 0.6
            self.cue("DRIBBLE", d, past=x.id)
        return None

    # ------------------------------------------------------------ contacts
    def goal_line(self, p0: tuple[float, float, float]) -> PlayResult | None:
        b, L, W = self.ball, self.L, self.W
        if b.owner is not None:
            return None
        if b.x >= L:
            k = (L - p0[0]) / (b.x - p0[0]) if b.x != p0[0] else 1.0
            cy, cz = p0[1] + (b.y - p0[1]) * k, p0[2] + (b.z - p0[2]) * k
            off = abs(cy - W / 2)
            if off <= self.goal / 2 + BALL_RADIUS and abs(cz - self.goal_h) <= POST_RADIUS + BALL_RADIUS:
                self.cue("BAR", None)
                self.post = True
                b.x, b.y, b.z = L - 0.25, cy, max(0.3, cz - 0.25)
                b.vx, b.vy, b.vz = -abs(b.vx) * self.rng.uniform(0.25, 0.45), b.vy * 0.5, -abs(b.vz) * 0.4 - 1.0
                self.end_shot()
                return None
            if cz < self.goal_h and abs(off - self.goal / 2) <= POST_RADIUS + BALL_RADIUS:
                inner = off < self.goal / 2
                self.cue("POST", None)
                self.post = True
                if inner and self.rng.random() < 0.4:
                    return self.scored(cy, cz, "Na trave… e entra!")
                speed = math.hypot(b.vx, b.vy)
                away = -1 if cy > W / 2 else 1
                out_dir = away if inner else -away
                ang = math.pi + out_dir * self.rng.uniform(0.25, 0.9)
                sp = speed * self.rng.uniform(0.3, 0.5)
                b.x, b.y = L - 0.25, cy
                b.vx, b.vy = math.cos(ang) * sp, math.sin(ang) * sp
                self.end_shot()
                return None
            if cz <= self.goal_h - BALL_RADIUS and off <= self.goal / 2 - BALL_RADIUS:
                return self.scored(cy, cz, "Gol")
            self.cue("OUT", None)
            if b.last_touch == "D":
                return PlayResult("CORNER", self.frames, detail="Escanteio", **self.shot_fields())
            over = off <= self.goal / 2 + 1 and cz > self.goal_h
            detail = ("Por cima do gol" if over else "Para fora") if self.was_shot else "Bola pela linha de fundo"
            return PlayResult("OUT", self.frames, detail=detail, **self.shot_fields())
        if b.x <= 0 or b.y <= 0 or b.y >= W:
            self.cue("OUT", None)
            detail = "Para fora" if self.was_shot else "Conduziu para fora" if self.dribbler else "Bola fora"
            return PlayResult("OUT", self.frames, detail=detail, **self.shot_fields())
        return None

    def scored(self, cy: float, cz: float, detail: str) -> PlayResult:
        b = self.ball
        b.x, b.y, b.z = self.L + 0.6, cy, min(max(0.0, cz), self.goal_h - 0.3)
        b.vx, b.vy, b.vz = 2.0, b.vy * 0.2, 0.0
        shooter = self.shooter or self.carrier
        self.cue("GOAL", shooter)
        return PlayResult("GOAL", self.frames, detail=detail, shot=self.was_shot, on_target=True, xg=self.xg, shooter=shooter.id, post=self.post)

    def shot_fields(self) -> dict[str, object]:
        if not self.was_shot:
            return {"post": self.post}
        return {"shot": True, "on_target": self.on_target, "xg": self.xg, "shooter": self.shooter.id if self.shooter else None, "post": self.post,
                "keeper": self.keeper.b.id if self.keeper and self.keeper.done_contact else None}

    def end_shot(self) -> None:
        self.shot_live = False
        if self.after_parry_until is None:
            self.after_parry_until = self.t + 3.5
        self.receiver = None
        self.plan_ball_runs()

    def keeper_contact(self, p0: tuple[float, float, float]) -> PlayResult | None:
        if not self.keeper or self.ball.owner is not None:
            return None
        k = self.keeper
        res = k.claim_contact(self.t, self.ball) if self.ball.airborne and not self.shot_live else None
        if res is None and (self.shot_live or (self.ball.vx > 2 and self.ball.x > self.L - 3 * self.s)):
            res = k.contact(self.t, p0, self.ball)
        if res is None:
            return None
        self.cues.extend(k.cues)
        k.cues.clear()
        if res == "HOLD":
            if self.was_shot and self.shot_live:
                self.shot_live = False
                return PlayResult("SAVED_HELD", self.frames, detail="Defesa do goleiro", shot=True, on_target=self.on_target, xg=self.xg,
                                  keeper=k.b.id, shooter=self.shooter.id if self.shooter else None, post=self.post)
            return PlayResult("LOST", self.frames, detail="O goleiro fica com a bola", lost_to=k.b.id, **self.shot_fields())
        self.end_shot()
        return None

    def header(self, p0: tuple[float, float, float]) -> PlayResult | None:
        b = self.ball
        if not (0.85 <= b.z <= 2.7) or b.vz > 1.0:
            return None
        att = [a for a in self.attackers if a.id not in self.headed and a is not self.kicker and dist(a.x, a.y, b.x, b.y) < 1.05
               and b.z <= 2.1 + a.physical / 100 * 0.6]
        dfn = [d for d in self.defenders if d.id not in self.headed and dist(d.x, d.y, b.x, b.y) < 1.05 and b.z <= 2.1 + d.physical / 100 * 0.6]
        if not att and not dfn:
            return None
        a = min(att, key=lambda x: dist(x.x, x.y, b.x, b.y)) if att else None
        d = min(dfn, key=lambda x: dist(x.x, x.y, b.x, b.y)) if dfn else None
        for x in (a, d):
            if x:
                self.headed.add(x.id)
        if a and d:
            p_att = clamp(0.5 + (a.physical - d.physical) / 120 + (a.pace - d.pace) / 400, 0.2, 0.8)
            winner = a if self.rng.random() < p_att else d
        else:
            winner = a or d
            if winner.team == "A" and self.rng.random() > 0.85:
                return None   # misjudged the flight
        winner.act, winner.act_until = ACT_HEADER, self.t + 0.4
        self.cue("HEADER", winner)
        hz = b.z
        if winner.team == "D":
            ang = math.pi + self.rng.uniform(-0.9, 0.9)
            sp = 9 + winner.physical / 100 * 6
            b.vx, b.vy, b.vz = math.cos(ang) * sp, math.sin(ang) * sp, 3.0
            b.last_touch = "D"
            self.shot_live = False
            return PlayResult("LOST", self.frames, detail=f"{winner.name} afasta de cabeça", lost_to=winner.id, **self.shot_fields())
        L, W, s = self.L, self.W, self.s
        in_zone = b.x > L - 20 * s and abs(b.y - W / 2) < 13 * s
        if not in_zone:
            b.vx, b.vy, b.vz, b.z = winner.vx * 0.5, winner.vy * 0.5, 0.0, 0.0
            self.completed_pass = self.action in ("PASS", "LOFT")
            self.start_dribble(winner, "SETTLE", (winner.x, winner.y))
            self.settle_until = self.t + SETTLE_SECONDS
            return None
        keeper_y = self.keeper.b.y if self.keeper else W / 2
        side = -1 if keeper_y > W / 2 else 1
        ty = W / 2 + side * (self.goal / 2 - 0.5) * self.rng.uniform(0.3, 1.0)
        aim = math.atan2(ty - b.y, L - b.x)
        skill = (winner.shooting * 0.5 + winner.physical * 0.5) / 100
        angle = aim + self.rng.gauss(0, 0.09 * (1.4 - skill))
        sp = 10.0 + 7.0 * winner.physical / 100
        b.vx, b.vy, b.z, b.vz = math.cos(angle) * sp, math.sin(angle) * sp, hz, -1.2 + self.rng.uniform(-0.6, 0.8)
        b.last_touch = "A"
        self.shot_live, self.shot_t0, self.was_shot, self.shooter = True, self.t, True, winner
        self.xg = round(self.xg_at(winner.x, winner.y) * 0.7, 3)
        self.on_target = self.predicted_on_target()
        if self.keeper:
            self.keeper.react_at = None
            self.keeper.done_contact = False
        self.receiver = None
        return None

    def player_contact(self, p0: tuple[float, float, float]) -> PlayResult | None:
        b, t = self.ball, self.t
        if b.z > 0.8 or self.dribbler is not None:
            return None   # a dribbled ball is contested by tackles(), not by a free touch
        sx, sy = b.x - p0[0], b.y - p0[1]
        l2 = sx * sx + sy * sy
        hits: list[tuple[float, float, Athlete]] = []
        for body in self.bodies:
            if body.role == "GK" or body is self.dribbler:
                continue
            if body is self.kicker and t - self.kick_t < 0.35:
                continue
            if t < self.cool.get(body.id, 0.0):
                continue
            u = 0.0 if l2 < 1e-12 else clamp(((body.x - p0[0]) * sx + (body.y - p0[1]) * sy) / l2, 0.0, 1.0)
            d = dist(body.x, body.y, p0[0] + sx * u, p0[1] + sy * u)
            reach = 0.55 if body.team == "A" else 0.48
            if body is self.receiver:
                reach = 0.9    # the intended receiver attacks the ball (steps across his marker)
            elif body.id in self.interceptors:
                reach = 0.85 + 0.15 * body.defending / 100   # stretching / sliding to cut it out
            if d <= reach:
                hits.append((u, d, body))
        if not hits:
            return None
        hits.sort(key=lambda h: (h[0], h[1]))
        _, _, body = hits[0]
        speed = b.ground_speed
        if body.team == "A":
            return self.receive(body, speed)
        return self.defender_touch(body, speed)

    def receive(self, body: Athlete, speed: float) -> PlayResult | None:
        b, t, rng = self.ball, self.t, self.rng
        pressure = self.pressure_on(body)
        incoming = math.atan2(-b.vy, -b.vx) if speed > 0.5 else body.facing
        orient = abs(wrap(incoming - body.facing)) / math.pi    # 0 = facing the ball, 1 = back to it
        control = (0.6 * body.dribbling + 0.4 * body.passing) / 100
        q = 0.72 + 0.32 * control - 0.016 * max(0.0, speed - 11) - 0.15 * pressure - (0.1 if b.z > 0.3 else 0.0) - 0.06 * orient
        if speed < 2.0:
            q = 0.97
        roll = rng.random()
        if roll < clamp(q, 0.15, 0.98):
            # Clean first touch, in the direction he is running (or towards the goal when standing).
            run = math.atan2(body.vy, body.vx) if body.speed > 1.5 else math.atan2(self.W / 2 - body.y, self.L - body.x) * 0.5 + body.facing * 0.5
            run = self.inside(body.x, body.y, run, body.speed * 0.6 + 1.0)
            out = body.speed * 1.0 + 1.0
            b.vx, b.vy, b.vz, b.z = math.cos(run) * out, math.sin(run) * out, 0.0, 0.0
            b.last_touch = "A"
            self.completed_pass = body is not self.carrier and self.action in ("PASS", "LOFT") or self.completed_pass
            body.act, body.act_until = ACT_RECEIVE, t + 0.25
            self.cue("CONTROL", body)
            self.shot_live = False
            self.start_dribble(body, "SETTLE", (body.x, body.y))
            self.settle_until = t + SETTLE_SECONDS
            self.last_touch_t = t
            return None
        if roll < q + 0.16:
            # Heavy touch: it bounces off him, still live.
            ang = body.facing + rng.uniform(-0.8, 0.8)
            sp = max(2.5, speed * rng.uniform(0.35, 0.55))
            b.vx, b.vy, b.vz = math.cos(ang) * sp, math.sin(ang) * sp, 0.0
            b.last_touch = "A"
            self.cue("TOUCH", body)
            self.cool[body.id] = t + 0.55
            self.receiver = None
            self.shot_live = False
            self.plan_ball_runs()
            return None
        # Misjudged: the ball runs past him.
        b.vx *= 0.9
        b.vy *= 0.9
        self.cool[body.id] = t + 0.8
        return None

    def defender_touch(self, body: Athlete, speed: float) -> PlayResult | None:
        b, t, rng = self.ball, self.t, self.rng
        if self.shot_live:
            if rng.random() < clamp(0.25 + 0.25 * body.defending / 100 + self.boost, 0.15, 0.6):
                ang = math.atan2(b.vy, b.vx) + math.pi + rng.uniform(-1.0, 1.0)
                sp = speed * rng.uniform(0.25, 0.45)
                b.vx, b.vy, b.vz = math.cos(ang) * sp, math.sin(ang) * sp, rng.uniform(0.0, 2.5)
                b.last_touch = "D"
                body.act, body.act_until = ACT_TACKLE, t + 0.35
                self.cue("BLOCK", body)
                self.end_shot()
                return None
            self.cool[body.id] = t + 1.0
            return None
        committed = body.id in self.interceptors
        # Committed (he read the pass and attacked the ball) vs. a ball that just runs near him.
        base = 0.24 + 0.44 * body.defending / 100 if committed else 0.04 + 0.2 * body.defending / 100
        chance = clamp(base - 0.022 * max(0.0, speed - 10) + self.boost + self.diff["intercept"], 0.05, 0.92)
        if speed < 3.0:
            chance = max(chance, 0.85)
        body.act, body.act_until = ACT_TACKLE if committed else ACT_RECEIVE, t + 0.3
        if rng.random() < chance:
            self.cue("INTERCEPT", body)
            self.owner = body
            self.attach(body)
            return PlayResult("LOST", self.frames, detail=f"Interceptação de {body.name}", lost_to=body.id, **self.shot_fields())
        ang = math.atan2(b.vy, b.vx) + rng.uniform(-0.5, 0.5)
        sp = speed * 0.65
        b.vx, b.vy = math.cos(ang) * sp, math.sin(ang) * sp
        b.last_touch = "D"
        self.cue("DEFLECT", body)
        self.cool[body.id] = t + 0.8
        body.slow_until = t + 0.35
        self.receiver = None
        self.plan_ball_runs()
        return None

    # ------------------------------------------------------------ endings
    def by_proximity(self) -> PlayResult:
        b = self.ball
        nearest = min((x for x in self.bodies if x.role != "GK"), key=lambda x: dist(x.x, x.y, b.x, b.y))
        self.dribbler = None
        if nearest.team == "A":
            self.owner = nearest
            self.attach(nearest)
            return PlayResult("CONTROLLED", self.frames, receiver=nearest.id, detail=f"{nearest.name} fica com a sobra", **self.shot_fields())
        return PlayResult("LOST", self.frames, detail="A defesa recupera", lost_to=nearest.id, **self.shot_fields())

    def finish(self, result: PlayResult) -> PlayResult:
        """A short tail after the decisive moment: players slow down naturally instead of
        freezing on the spot; nothing in the tail can change the result."""
        terminal = result.outcome in ("GOAL", "OUT", "CORNER", "SAVED_HELD", "LOST")
        tail = 0.5 if terminal else 0.0
        end = self.t + tail
        if self.frames and self.frames[-1][0] < round(self.t, 3) - 1e-6:
            end = max(end, self.next_frame)   # finish on the 10 Hz grid the renderers interpolate on
        while self.t < end - 1e-9:
            self.t += DT
            for body in self.bodies:
                if body.act in (ACT_KICK, ACT_RECEIVE, ACT_TACKLE, ACT_HEADER, ACT_DRIBBLE, ACT_STUMBLE) and self.t >= body.act_until:
                    body.act = ACT_NONE
                if self.keeper and body is self.keeper.b and body.act != ACT_GK_HOLD:
                    self.keeper.update(self.t, self.ball, False, 0.0, False, None)
                    continue
                if result.outcome == "CONTROLLED":
                    body.tx, body.ty = body.x + body.vx * 0.6, body.y + body.vy * 0.6
                else:
                    body.tx, body.ty, body.intensity = body.x + body.vx * 0.35, body.y + body.vy * 0.35, 0.6
                move(body, self.t)
            b = self.ball
            if self.keeper and b.owner == self.keeper.b.id:
                kb = self.keeper.b
                b.x, b.y, b.z, b.vx, b.vy, b.vz = kb.x - 0.3, kb.y, 1.0, 0.0, 0.0, 0.0
            elif b.owner and b.owner in self.by_id:
                self.attach(self.by_id[b.owner])
            elif b.x > self.L:
                b.vx *= 0.5
                b.vy *= 0.5
                b.x = min(b.x + b.vx * DT, self.L + 1.6)
            else:
                ball_step(b)
            while self.t >= self.next_frame - 1e-9:
                self.record()
                self.next_frame += FRAME_DT
        if not self.frames:
            self.record()
        if self.keeper:
            self.cues.extend(self.keeper.cues)
            self.keeper.cues.clear()
        result.frames = self.frames
        result.cues = [c.as_dict() for c in sorted(self.cues, key=lambda c: c.t)]
        if self.was_shot:
            # Whatever ended the action (a rebound controlled, a clearance...), the shot counts.
            result.shot, result.on_target, result.xg = True, self.on_target, self.xg
            result.shooter = result.shooter or (self.shooter.id if self.shooter else None)
            if self.keeper and self.keeper.done_contact and result.keeper is None:
                result.keeper = self.keeper.b.id
        if result.outcome == "CONTROLLED":
            result.completed_pass = result.completed_pass or (self.completed_pass and result.receiver != self.carrier.id)
        return result
