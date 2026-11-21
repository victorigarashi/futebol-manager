/**
 * Player kinematics: the current V6 rules (replicated from highlights.py for comparison)
 * and the proposed model.
 *
 * V6 (`_steer`): desired velocity = min(top, 2.2 * distance) towards the target, and the
 * velocity change is clamped PER AXIS to accel*DT. Consequences: diagonal acceleration is
 * up to sqrt(2) x the nominal one and a change of direction becomes an L-shaped path.
 *
 * Proposed: force-velocity sprint (a = aMax * (1 - v / vMax), i.e. v(t) = vMax(1 - e^(-t/tau)))
 * and a friction circle: |dv/dt| <= aMax(v) with the lateral part <= mu*g, braking <= bMax.
 * The ball model is in ball.ts.
 */
export type V2 = { x: number; y: number };
export const V6 = { DT: 0.1, BASE: 5.6, PACE: 3.4, ACCEL: [6.0, 3.5] as const, CARRY_ACCEL: 11.0, GROUND_DECEL: 5.0, SHOT_DECEL: 1.5, LOFT_RANGE: [12, 46] as const, LOFT_SPEED: [11, 15] as const, CARRY_TOUCH: [0.95, 0.55] as const };

export type Mover = { p: V2; v: V2 };
export function v6Steer(b: Mover, target: V2, pace: number, dt = V6.DT, accel?: number): void {
  const a = accel ?? V6.ACCEL[0] + V6.ACCEL[1] * pace / 100;
  const top = V6.BASE + pace / 100 * V6.PACE;
  const dx = target.x - b.p.x, dy = target.y - b.p.y;
  const d = Math.hypot(dx, dy);
  const desired = Math.min(top, d * 2.2);
  const dvx = d > 1e-6 ? dx / d * desired : 0, dvy = d > 1e-6 ? dy / d * desired : 0;
  const step = a * dt;
  b.v.x += Math.max(-step, Math.min(step, dvx - b.v.x));
  b.v.y += Math.max(-step, Math.min(step, dvy - b.v.y));
  b.p.x += b.v.x * dt; b.p.y += b.v.y * dt;
}

export type PlayerModel = { vMax: number; aMax: number; brake: number; grip: number };
export function modelFromPace(pace: number): PlayerModel {
  const k = pace / 100;
  return { vMax: 7.4 + 2.0 * k, aMax: 7.8 + 2.2 * k, brake: 8.5 + 1.0 * k, grip: 7.5 };
}
/** One step of the proposed model: arrive at `target` with a friction-circle limit. */
export function steer(b: Mover, target: V2, m: PlayerModel, dt: number, intensity = 1): void {
  const dx = target.x - b.p.x, dy = target.y - b.p.y;
  const d = Math.hypot(dx, dy);
  const speed = Math.hypot(b.v.x, b.v.y);
  // arrive: the highest speed from which we can still stop at the target
  const vStop = Math.sqrt(2 * m.brake * Math.max(0, d - 0.1));
  const desired = Math.min(m.vMax * intensity, vStop);
  const wx = d > 1e-6 ? dx / d * desired : 0, wy = d > 1e-6 ? dy / d * desired : 0;
  let ax = (wx - b.v.x) / dt, ay = (wy - b.v.y) / dt;
  // split into tangential (along v) and lateral components
  const tx = speed > 0.3 ? b.v.x / speed : (d > 0 ? dx / d : 1), ty = speed > 0.3 ? b.v.y / speed : (d > 0 ? dy / d : 0);
  let at = ax * tx + ay * ty;
  let al = -ax * ty + ay * tx;
  const forward = m.aMax * Math.max(0, 1 - speed / m.vMax);    // propulsive limit falls with speed
  at = Math.max(-m.brake, Math.min(forward, at));
  al = Math.max(-m.grip, Math.min(m.grip, al));
  // friction circle: total horizontal force bounded by grip+propulsion
  const lim = Math.max(m.brake, m.grip);
  const mag = Math.hypot(at, al);
  if (mag > lim) { at *= lim / mag; al *= lim / mag; }
  ax = at * tx - al * ty; ay = at * ty + al * tx;
  b.v.x += ax * dt; b.v.y += ay * dt;
  b.p.x += b.v.x * dt; b.p.y += b.v.y * dt;
}

/** Straight sprint from rest: time to reach 5/10/20/30 m and the distance-time curve. */
export function sprintCurve(kind: "v6" | "model", pace: number, T = 5, dt = 0.02): { t: number; x: number; v: number }[] {
  const b: Mover = { p: { x: 0, y: 0 }, v: { x: 0, y: 0 } };
  const out = [{ t: 0, x: 0, v: 0 }];
  const m = modelFromPace(pace);
  const step = kind === "v6" ? V6.DT : dt;
  for (let t = step; t <= T + 1e-9; t += step) {
    if (kind === "v6") v6Steer(b, { x: 200, y: 0 }, pace); else steer(b, { x: 200, y: 0 }, m, dt);
    out.push({ t, x: b.p.x, v: Math.hypot(b.v.x, b.v.y) });
  }
  return out;
}
export function splitTime(curve: { t: number; x: number }[], d: number): number | null {
  for (let i = 1; i < curve.length; i += 1) if (curve[i].x >= d) { const a = curve[i - 1], b = curve[i]; return a.t + (d - a.x) / (b.x - a.x) * (b.t - a.t); }
  return null;
}

/** A 90° cut at speed: run along +x, then the target jumps to the side. Returns the path. */
export function cutPath(kind: "v6" | "model", pace: number, speed: number, angleDeg = 90): V2[] {
  const b: Mover = { p: { x: 0, y: 0 }, v: { x: speed, y: 0 } };
  const m = modelFromPace(pace);
  const a = angleDeg * Math.PI / 180;
  const target = { x: Math.cos(a) * 30, y: Math.sin(a) * 30 };
  const out: V2[] = [{ ...b.p }];
  const dt = kind === "v6" ? V6.DT : 0.02;
  for (let t = 0; t < 2.5; t += dt) {
    if (kind === "v6") v6Steer(b, target, pace); else steer(b, target, m, dt);
    out.push({ ...b.p });
  }
  return out;
}
/** Peak acceleration magnitude produced by a steering rule in a diagonal start (exposes the per-axis clamp). */
export function diagonalAccel(kind: "v6" | "model", pace: number): number {
  const b: Mover = { p: { x: 0, y: 0 }, v: { x: 0, y: 0 } };
  if (kind === "v6") { v6Steer(b, { x: 50, y: 50 }, pace); return Math.hypot(b.v.x, b.v.y) / V6.DT; }
  steer(b, { x: 50, y: 50 }, modelFromPace(pace), 0.02);
  return Math.hypot(b.v.x, b.v.y) / 0.02;
}

/** V6 lofted ball: constant horizontal speed, height 4*3.2*p(1-p)*min(1, T/1.6). */
export function v6LoftProfile(distance: number, power: number): { x: number; z: number }[] {
  const v0 = V6.LOFT_SPEED[0] + V6.LOFT_SPEED[1] * power;
  const T = distance / v0;
  const out: { x: number; z: number }[] = [];
  for (let i = 0; i <= 40; i += 1) { const p = i / 40; out.push({ x: distance * p, z: 4 * 3.2 * p * (1 - p) * Math.min(1, T / 1.6) }); }
  return out;
}

/** Dribble: distance ball-foot over time. V6 ties the ball to the carrier; the touch model kicks a loose ball. */
export function carryGap(kind: "v6" | "touch", speed: number, dribbling: number, T = 3, dt = 0.02): { t: number; gap: number }[] {
  const out: { t: number; gap: number }[] = [];
  if (kind === "v6") {
    const touch = V6.CARRY_TOUCH[0] - V6.CARRY_TOUCH[1] * dribbling / 100;
    for (let t = 0; t <= T; t += dt) { const stride = (t % 0.5) / 0.5; out.push({ t, gap: 0.35 + touch * (1 - stride) * 0.9 }); }
    return out;
  }
  // loose ball pushed ahead each touch (speed * 1.45 + 0.6), rolling resistance + skid as in ball.ts (simplified 1D)
  let px = 0, bx = 0.3, bv = 0, next = 0;
  const cycle = 2.4 / Math.max(1, speed) * 1.0;   // one touch per dribble cycle (stride ~2.4 m)
  for (let t = 0; t <= T; t += dt) {
    // close control: a touch only when the ball is back within reach; better dribblers touch softer
    if (t >= next && bx - px < 0.45) { bv = speed * (1.28 - 0.1 * dribbling / 100) + 0.5; next = t + cycle; }
    bv = Math.max(0, bv - (0.065 * 9.81 + 0.22 * bv + 0.002 * bv * bv) * dt);
    bx += bv * dt; px += speed * dt;
    out.push({ t, gap: bx - px });
  }
  return out;
}
