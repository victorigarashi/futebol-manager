"""Football Intelligence (V7): decisions separated from locomotion.

Five times per second each team re-plans *where to be and why*; the locomotion
(world.move) executes it physically. Targets have hysteresis (a new spot must be clearly
better), so intentions are stable and nobody changes his mind every frame.

Attack roles: ball carrier, receiver (runs onto the ball's path), close supports (open
angles: passing lanes), width holders, depth runner (on the last defender's shoulder,
running in behind when the carrier can play forward), box attackers (crosses), safety
behind the ball, the passer going again (give-and-go).

Defence roles: one presser (holds the line goal-side and jockeys; the tackle is decided
by the play when the ball is exposed), one cover behind him, markers goal-side of the
dangerous runners, a common back line that steps up / drops as a unit, compactness
towards the ball. Tactics shape all of it (no duplicated tactical system).
"""

from __future__ import annotations

import math

from app.domain.football.world import Athlete, BallState, clamp, dist


class TeamBrain:
    def __init__(self, bodies: list[Athlete], L: float, W: float, s: float, tactics: dict[str, object] | None, difficulty: str = "NORMAL",
                 v8: bool = False) -> None:
        self.v8 = v8
        self.bodies, self.L, self.W, self.s = bodies, L, W, s
        self.attackers = [b for b in bodies if b.team == "A" and b.role != "GK"]
        self.defenders = [b for b in bodies if b.team == "D" and b.role != "GK"]
        t = tactics or {}
        self.style = t.get("style", "POSSESSION")
        self.def_mentality = t.get("def_mentality", "BALANCED")
        self.def_pressure = t.get("def_pressure", "MEDIUM")
        self.difficulty = difficulty
        self.presser: str | None = None
        self.cover: str | None = None
        self.second_presser: str | None = None
        self.passer: str | None = None
        self.passer_until = 0.0
        self.react_until = 0.0     # defenders keep their previous intention until then (reaction)
        # V8 tactical contract (highlights.HighlightMatch._tactics): roles, individual
        # instructions, attacking mentality and cohesion. Absent keys = neutral behaviour.
        self.roles: dict[str, str] = dict(t.get("roles") or {})
        self.instr: dict[str, str] = dict(t.get("instructions") or {})
        self.att_mentality = str(t.get("att_mentality", "BALANCED"))
        self.att_cohesion = float(t.get("att_cohesion", 0.0) or 0.0)
        self.def_cohesion = float(t.get("def_cohesion", 0.0) or 0.0)
        self.third_man: str | None = None

    # ------------------------------------------------------------ helpers
    def openness(self, x: float, y: float) -> float:
        return min((dist(x, y, d.x, d.y) for d in self.defenders), default=15.0)

    def lane_clear(self, ax: float, ay: float, bx: float, by: float) -> float:
        """Smallest distance from a defender to the segment A->B (a passing lane)."""
        best = 15.0
        lx, ly = bx - ax, by - ay
        l2 = lx * lx + ly * ly or 1.0
        for d in self.defenders:
            u = clamp(((d.x - ax) * lx + (d.y - ay) * ly) / l2, 0.0, 1.0)
            best = min(best, dist(d.x, d.y, ax + lx * u, ay + ly * u))
        return best

    def last_line(self) -> float:
        xs = sorted((d.x for d in self.defenders), reverse=True)
        return xs[1] if len(xs) > 1 else (xs[0] if xs else self.L - 12 * self.s)

    def _set(self, body: Athlete, tx: float, ty: float, intensity: float, keep: float = 1.2) -> None:
        """Hysteresis: keep the current target unless the new one is clearly elsewhere."""
        tx, ty = clamp(tx, 0.5, self.L - 0.4), clamp(ty, 0.4, self.W - 0.4)
        if body.tx is not None and dist(body.tx, body.ty, tx, ty) < keep * self.s ** 0.5:
            body.intensity = intensity
            return
        if body.tx is not None and dist(body.tx, body.ty, tx, ty) < 6.0:
            # Small re-plans blend in (an intention drifts, it does not jump).
            tx, ty = body.tx + (tx - body.tx) * 0.6, body.ty + (ty - body.ty) * 0.6
        body.tx, body.ty, body.intensity = tx, ty, intensity

    # ------------------------------------------------------------ plan
    def plan(self, t: float, ball: BallState, owner: Athlete | None, receiver: Athlete | None, skip: set[str]) -> None:
        self._attack(t, ball, owner, receiver, skip)
        if t >= self.react_until:
            self._defend(t, ball, owner, skip)

    def _attack(self, t: float, ball: BallState, owner: Athlete | None, receiver: Athlete | None, skip: set[str]) -> None:
        L, W, s = self.L, self.W, self.s
        bx, by = ball.x, ball.y
        line = self.last_line()
        free = [a for a in self.attackers if a.id not in skip and a is not owner and a is not receiver]
        crossing = (bx > L - 26 * s and min(by, W - by) < 15 * s) or (ball.z > 1.0 and ball.vx > 0 and bx > L - 45 * s)
        # Close supports: the two nearest non-strikers show for the ball at open angles.
        near = sorted((a for a in free if a.role != "ST"), key=lambda a: dist(a.x, a.y, bx, by))[:2]
        taken: list[tuple[float, float]] = []
        show = (8.0, 12.0) if self.style in ("POSSESSION", "SHORT_BUILDUP") else (10.0, 15.0)
        safety = None
        mids = [a for a in free if a.role == "MF"]
        if len(mids) >= 3:
            safety = min(mids, key=lambda a: a.x)
        if self.v8:
            self._choose_third_man(ball, owner, receiver, free)
        for a in free:
            a.look = (bx, by)
            if self.v8 and self._attack_v8(a, t, ball, owner, receiver, line, crossing):
                continue
            if a.id == self.passer and t < self.passer_until:
                # Pass and move: into the space ahead, away from the nearest defender.
                nd = min(self.defenders, key=lambda d: dist(d.x, d.y, a.x, a.y), default=None)
                side = 1 if nd is None or nd.y < a.y else -1
                self._set(a, min(a.x + 10 * s, L - 7 * s), a.y + side * 3 * s, 1.0, 2.0)
                continue
            if crossing and a.role in ("ST", "MF") and a is not safety:
                # Attack the box: near post, far post, penalty spot (by who is closest).
                near_side = 1 if by > W / 2 else -1
                spots = [(L - 6 * s, W / 2 + near_side * 3.0 * s), (L - 7 * s, W / 2 - near_side * 4.5 * s), (L - 11.5 * s, W / 2)]
                spot = min((sp for sp in spots if sp not in taken), key=lambda sp: dist(a.x, a.y, *sp), default=spots[-1])
                taken.append(spot)
                self._set(a, spot[0], spot[1], 1.0)
                continue
            if a.role == "ST":
                # Depth: on the last defender's shoulder; runs in behind when the carrier can play forward.
                can_play = owner is not None and math.cos(owner.facing) > 0.3 and dist(owner.x, owner.y, a.x, a.y) < 40 * s
                behind = (6.0 if self.style in ("COUNTER", "DIRECT") else 4.0) * s
                tx = line + (behind if can_play else -1.0 * s)
                tx = clamp(tx, a.ax - 5 * s, L - 5 * s)
                ys = [a.ay + k * 4 * s for k in (-1, 0, 1)]
                ty = max(ys, key=lambda y: self.openness(tx, y) - abs(y - a.ay) * 0.08)
                self._set(a, tx, ty, 1.0 if can_play else 0.75, 1.5)
                continue
            if a is safety:
                self._set(a, bx - 12 * s, W / 2 + (by - W / 2) * 0.3, 0.7, 2.0)
                continue
            wide = min(a.ay, W - a.ay) < W * 0.2
            if wide and a not in near:
                push = (8 if self.style == "WIDE" else 4) * s
                tx = clamp(max(a.ax, bx + push), a.ax, L - 8 * s)
                ty = (2.5 * s) if a.ay < W / 2 else W - 2.5 * s
                if self.style != "WIDE":
                    ty = a.ay
                self._set(a, tx, ty, 0.85, 2.0)
                continue
            if a in near:
                # Show for the ball: a triangle with the carrier, in a clear lane.
                best, best_score = None, -9e9
                for ang in (-1.9, -1.3, -0.8, -0.45, 0.45, 0.8, 1.3, 1.9):
                    for r in show:
                        cx, cy = bx + math.cos(ang) * r * s, by + math.sin(ang) * r * s
                        if not (2 * s < cy < W - 2 * s) or cx > L - 4 * s:
                            continue
                        if any(dist(cx, cy, *sp) < 6 * s for sp in taken):
                            continue
                        score = min(self.openness(cx, cy), 8) * 0.5 + min(self.lane_clear(bx, by, cx, cy), 5) * 0.7 \
                            + (cx - bx) / s * 0.06 - dist(a.x, a.y, cx, cy) / s * 0.08
                        if score > best_score:
                            best, best_score = (cx, cy), score
                if best:
                    taken.append(best)
                    self._set(a, best[0], best[1], 0.9, 2.5)
                    continue
            # Everybody else keeps the shape, moving with the ball (the block travels together).
            push = 0.55 if not self.v8 else {"VERY_ATTACKING": 0.85, "ATTACKING": 0.7, "DEFENSIVE": 0.38, "VERY_DEFENSIVE": 0.25}.get(self.att_mentality, 0.55)
            progress = max(0.0, bx - L * 0.45) * push
            self._set(a, a.ax + progress, a.ay + (by - a.ay) * 0.18, 0.7, 2.5)

    # ------------------------------------------------------------ V8 tactical behaviours
    def _choose_third_man(self, ball: BallState, owner: Athlete | None, receiver: Athlete | None, free: list[Athlete]) -> None:
        """While a pass travels to a receiver, a THIRD player attacks the space beyond him
        (the classic third-man run). Only if that space really exists."""
        if owner is not None or receiver is None or ball.ground_speed < 3:
            self.third_man = None
            return
        if self.third_man and any(a.id == self.third_man for a in free):
            return
        s = self.s
        best, best_space = None, 6.0 * s ** 0.5
        for a in free:
            if a.id == self.passer or self.roles.get(a.id) in ("CB", "GK") or self.instr.get(a.id) == "HOLD":
                continue
            tx, ty = receiver.x + 11 * s, a.y + (receiver.y - a.y) * 0.3
            space = self.openness(tx, ty)
            if space > best_space and a.x > receiver.x - 14 * s:
                best, best_space = a, space
        self.third_man = best.id if best else None

    def _attack_v8(self, a: Athlete, t: float, ball: BallState, owner: Athlete | None, receiver: Athlete | None, line: float, crossing: bool) -> bool:
        L, W, s = self.L, self.W, self.s
        role, code = self.roles.get(a.id, a.role), self.instr.get(a.id, "")
        bx, by = ball.x, ball.y
        if a.id == self.third_man and receiver is not None:
            self._set(a, min(L - 7 * s, receiver.x + 11 * s), a.y + (receiver.y - a.y) * 0.3, 1.0, 1.5)
            return True
        carrier = owner or receiver
        if role == "FB" and carrier is not None:
            same_side = (a.ay < W / 2) == (carrier.y < W / 2)
            wide_carrier = min(carrier.y, W - carrier.y) < W * 0.28
            touch = 2.5 * s if a.ay < W / 2 else W - 2.5 * s
            if code == "STAY_BACK":
                self._set(a, min(a.ax, bx - 10 * s), a.ay, 0.7, 2.0)
                return True
            if same_side and wide_carrier and carrier.x > a.x - 4 * s and (code == "OVERLAP" or (code == "SUPPORT" and self.style == "WIDE")):
                # Overlap: round the outside of the man on the ball, towards the byline.
                self._set(a, min(L - 6 * s, carrier.x + 10 * s), touch, 1.0, 1.5)
                return True
            if same_side and code in ("SUPPORT", "OVERLAP"):
                self._set(a, carrier.x - 6 * s, touch, 0.85, 2.0)
                return True
        if role == "ST":
            behind = bx < line - 25 * s
            if code == "TARGET" and behind:
                # Pivot: comes short with his back to goal to hold it up and lay it off.
                self._set(a, max(bx + 14 * s, line - 6 * s), a.ay + (by - a.ay) * 0.4, 0.85, 1.5)
                return True
            if code == "FALSE_9" and not crossing:
                self._set(a, max(bx + 8 * s, line - 12 * s), W / 2 + (by - W / 2) * 0.3, 0.8, 1.5)
                return True
            if code == "IN_BEHIND":
                self._set(a, min(L - 6 * s, line + 5 * s), a.ay, 1.0, 1.5)
                return True
        if role == "MF" and code == "HOLD" and not crossing:
            self._set(a, bx - 14 * s, W / 2 + (by - W / 2) * 0.25, 0.7, 2.0)
            return True
        if role == "MF" and code == "ARRIVE" and bx > L - 40 * s:
            self._set(a, L - 11 * s, W / 2 + (a.ay - W / 2) * 0.4, 1.0, 1.5)
            return True
        return False

    def _defend_v8(self, d: Athlete, ball: BallState, owner: Athlete | None, line: float, defenders: list[Athlete]) -> bool:
        L, W, s = self.L, self.W, self.s
        role, code = self.roles.get(d.id, d.role), self.instr.get(d.id, "")
        gx, gy = L, W / 2
        bx, by = (owner.x, owner.y) if owner else (ball.x, ball.y)
        if role == "CB" and code == "COVER":
            self._set(d, min(L - 4 * s, line + 2.5 * s), gy + (by - gy) * 0.3, 0.9, 1.0)
            return True
        if role == "MF" and code == "HOLD":
            # Screen in front of the box, between the ball and the goal.
            dd = max(1.0, dist(bx, by, gx, gy))
            self._set(d, max(line - 9 * s, bx + (gx - bx) / dd * 10 * s), by + (gy - by) * 0.5, 0.9, 1.0)
            return True
        if role == "MF" and owner is not None:
            # Cover shadow: stand in the passing lane from the ball to the most dangerous free attacker.
            marked = [x for x in self.attackers if x is not owner]
            if marked:
                target = min(marked, key=lambda x: dist(x.x, x.y, gx, gy) + dist(x.x, x.y, d.x, d.y) * 0.5)
                if dist(target.x, target.y, d.x, d.y) < 16 * s ** 0.7:
                    k = 0.45
                    self._set(d, bx + (target.x - bx) * k, by + (target.y - by) * k, 0.92, 0.8)
                    return True
        return False

    def _defend(self, t: float, ball: BallState, owner: Athlete | None, skip: set[str]) -> None:
        L, W, s = self.L, self.W, self.s
        gx, gy = L, W / 2
        bx, by = (owner.x, owner.y) if owner else (ball.x, ball.y)
        defenders = [d for d in self.defenders if d.id not in skip]
        if not defenders:
            return
        # Presser: who gets to the ball first (stable unless someone is clearly closer).
        timing = {d.id: d.time_to(bx, by) for d in defenders}
        best = min(defenders, key=lambda d: timing[d.id])
        if self.presser is None or self.presser not in timing or timing[best.id] < timing[self.presser] - 0.35:
            self.presser = best.id
        rest = sorted((d for d in defenders if d.id != self.presser), key=lambda d: timing[d.id])
        self.cover = rest[0].id if rest else None
        self.second_presser = rest[0].id if rest and self.def_pressure == "HIGH" else None
        depth = {"DEFENSIVE": 3.0, "VERY_DEFENSIVE": 5.0, "ATTACKING": -2.5, "VERY_ATTACKING": -4.0}.get(self.def_mentality, 0.0) * s
        # Back line: one line, between the ball and the goal; drops with the deepest runner (no offside here).
        runners = [a for a in self.attackers if a.x > bx - 2 * s]
        deepest = max((a.x for a in runners), default=bx)
        line = clamp(max(bx + 10 * s + depth, deepest + 1.2 * s), L - 38 * s, L - 5.5 * s)
        if L - bx < 20 * s:
            line = max(line, L - 7 * s)
        # Markers: goal-side of the most dangerous attackers (closest to goal), one each.
        danger = sorted((a for a in self.attackers if a is not owner), key=lambda a: dist(a.x, a.y, gx, gy))
        marked: set[str] = set()
        engage = {"HIGH": 1.3, "LOW": 3.2}.get(self.def_pressure, 2.0)
        if self.v8:
            if self.def_pressure == "LOW":
                line = max(line, L - 24 * s) if bx < L - 30 * s else line   # low block: wait near the box
            elif self.def_pressure == "HIGH":
                line = min(line, max(L - 38 * s, bx + 7 * s))              # high line: squeeze the space
        for d in defenders:
            d.look = (bx, by)
            if self.v8 and d.id not in (self.presser, self.second_presser, self.cover) and self._defend_v8(d, ball, owner, line, defenders):
                continue
            if d.id == self.presser or d.id == self.second_presser:
                # Jockey goal-side: close the space, do not dive in (the tackle is a separate decision).
                dd = max(0.5, dist(bx, by, gx, gy))
                gap = engage if owner else 0.4
                tx, ty = bx + (gx - bx) / dd * gap, by + (gy - by) / dd * gap
                if d.id == self.second_presser:
                    ty += 2.0 * s if by < W / 2 else -2.0 * s
                self._set(d, tx, ty, 1.0, 0.3)
                continue
            if d.id == self.cover:
                dd = max(1.0, dist(bx, by, gx, gy))
                gap = min(7.5 * s ** 0.6, dd * 0.55)
                self._set(d, bx + (gx - bx) / dd * gap, by + (gy - by) / dd * gap, 0.95, 0.8)
                continue
            mark = None
            for a in danger:
                if a.id in marked:
                    continue
                if dist(a.x, a.y, d.ax, d.ay) < 20 * s ** 0.7 or (d.role == "DF" and a.role == "ST"):
                    mark = a
                    break
            if mark is not None:
                marked.add(mark.id)
                dm = max(1.0, dist(mark.x, mark.y, gx, gy))
                side = 1.6 * s ** 0.5
                tx = mark.x + (gx - mark.x) / dm * side + (bx - mark.x) * 0.06
                ty = mark.y + (gy - mark.y) / dm * side + (by - mark.y) * 0.1
                if d.role == "DF":
                    tx = max(tx, line - 1.0 * s) if mark.x < line else tx
                self._set(d, tx, ty, 0.95, 0.8)
                continue
            # Zone: the block slides to the ball and stays compact.
            tx = line if d.role == "DF" else min(line - 9 * s, d.ax + (bx - d.ax) * 0.35)
            ty = gy + (d.ay - gy) * 0.78 + (by - gy) * 0.35
            self._set(d, tx, ty, 0.85, 1.5)
