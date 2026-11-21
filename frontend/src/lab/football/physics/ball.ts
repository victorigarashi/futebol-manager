/**
 * Football ball physics (research prototype, deterministic, no dependencies).
 *
 * Coordinates: metres, x along the pitch, y across, z up (same as highlights.py).
 * Model:
 *  - air: gravity + quadratic drag with drag crisis (Cd 0.45 below ~8 m/s -> 0.22 above
 *    ~12 m/s) + Magnus lift (Cl = 1.0 * spin ratio, capped);
 *  - ground: the ball SLIDES until its spin matches its speed, then ROLLS. A football is a
 *    hollow sphere (I = 2/3 m r^2): a ball struck along the ground with no spin keeps
 *    3/5 of its speed once rolling. Rolling resistance of grass + drag afterwards;
 *  - bounce: normal restitution (speed dependent) and tangential friction impulse that
 *    also changes spin (topspin skids on, backspin checks up);
 *  - posts/crossbar: swept-sphere test against cylinders (continuous, no tunnelling).
 *
 * Every number is in BALL_DEFAULTS and documented in docs/research/football-lab/PHYSICS.md.
 */
export type Vec3 = { x: number; y: number; z: number };
export type BallState = { p: Vec3; v: Vec3; w: Vec3; t: number };
export type BallParams = {
  mass: number; radius: number; airDensity: number;
  cdLow: number; cdHigh: number; crisis: [number, number];
  liftGain: number; liftMax: number; spinDecay: number;
  rollResist: number;        // rolling resistance coefficient (decel = c * g)
  grassDrag: number;         // speed-proportional grass resistance (1/s): blades deform more at speed
  slideFriction: number;     // kinetic friction while the ball skids on grass
  restitution: [number, number];  // e at low and high impact speed
  bounceFriction: number;    // tangential friction coefficient at impact
  gravity: number;
  substep: number;           // max seconds per integration step
};
export const BALL_DEFAULTS: BallParams = {
  mass: 0.43, radius: 0.11, airDensity: 1.2,
  cdLow: 0.45, cdHigh: 0.22, crisis: [8, 12],
  liftGain: 1.0, liftMax: 0.3, spinDecay: 0.05,
  rollResist: 0.065, grassDrag: 0.22, slideFriction: 0.55,
  restitution: [0.72, 0.55], bounceFriction: 0.45,
  gravity: 9.81, substep: 1 / 240,
};

export type Goal = { x: number; y0: number; y1: number; height: number; postRadius: number; dir: 1 | -1 };
export type BallEvent = { t: number; kind: "bounce" | "post" | "bar" | "rest" | "goal" | "out"; at: Vec3; speed: number };

const len = (v: Vec3) => Math.hypot(v.x, v.y, v.z);
const smooth = (a: number, b: number, x: number) => { const t = Math.max(0, Math.min(1, (x - a) / (b - a))); return t * t * (3 - 2 * t); };

export function newBall(p: Vec3, v: Vec3 = { x: 0, y: 0, z: 0 }, w: Vec3 = { x: 0, y: 0, z: 0 }): BallState {
  return { p: { ...p }, v: { ...v }, w: { ...w }, t: 0 };
}

export function dragCoefficient(speed: number, P = BALL_DEFAULTS): number {
  return P.cdLow + (P.cdHigh - P.cdLow) * smooth(P.crisis[0], P.crisis[1], speed);
}

/** Advance the ball by dt (internally sub-stepped). Returns events (bounces, woodwork, rest). */
export function stepBall(b: BallState, dt: number, P: BallParams = BALL_DEFAULTS, goals: Goal[] = []): BallEvent[] {
  const events: BallEvent[] = [];
  let left = dt;
  while (left > 1e-9) {
    const speed = len(b.v);
    const h = Math.min(left, P.substep, speed > 0 ? 0.04 / speed : P.substep);   // <= 4 cm per sub-step
    subStep(b, h, P, goals, events);
    left -= h;
  }
  return events;
}

function subStep(b: BallState, h: number, P: BallParams, goals: Goal[], events: BallEvent[]) {
  const r = P.radius, g = P.gravity, m = P.mass;
  const A = Math.PI * r * r;
  const k = (0.5 * P.airDensity * A) / m;
  const onGround = b.p.z <= r + 1e-4 && Math.abs(b.v.z) < 0.35;
  const speed = len(b.v);
  const prev = { ...b.p };
  if (onGround) {
    b.p.z = r; b.v.z = 0;
    // contact point velocity = v + w x (-r z)  ->  (vx - wy r, vy + wx r)
    const sx = b.v.x - b.w.y * r, sy = b.v.y + b.w.x * r;
    const slip = Math.hypot(sx, sy);
    if (slip > 0.05) {
      // sliding: friction opposes slip; it slows the ball and spins it up (hollow sphere)
      const a = P.slideFriction * g;
      const fx = -sx / slip * a, fy = -sy / slip * a;
      const dvx = fx * h, dvy = fy * h;
      b.v.x += dvx; b.v.y += dvy;
      // torque r x F gives angular accel = (r * F) / I, I = 2/3 m r^2 -> alpha = 1.5 a / r
      b.w.y += -1.5 * dvx / r; b.w.x += 1.5 * dvy / r;
      const sx2 = b.v.x - b.w.y * r, sy2 = b.v.y + b.w.x * r;
      if (sx * sx2 + sy * sy2 < 0) { // slip reversed within the step: lock into rolling
        rollLock(b, r);
      }
    } else {
      rollLock(b, r);
      const sp = Math.hypot(b.v.x, b.v.y);
      if (sp > 0) {
        const dec = P.rollResist * g + P.grassDrag * sp + k * dragCoefficient(sp, P) * sp * sp;
        const ns = Math.max(0, sp - dec * h);
        b.v.x *= ns / sp; b.v.y *= ns / sp;
        rollLock(b, r);
        if (ns === 0 && speed > 0) events.push({ t: b.t, kind: "rest", at: { ...b.p }, speed: 0 });
      }
    }
    b.w.z *= Math.max(0, 1 - 2.0 * h);
  } else {
    const cd = dragCoefficient(speed, P);
    let ax = -k * cd * speed * b.v.x, ay = -k * cd * speed * b.v.y, az = -g - k * cd * speed * b.v.z;
    const wm = len(b.w);
    if (wm > 1e-3 && speed > 1e-3) {
      const S = (r * wm) / speed;
      const cl = Math.min(P.liftMax, P.liftGain * S);
      // direction w x v (normalised), magnitude k * cl * v^2
      let mx = b.w.y * b.v.z - b.w.z * b.v.y, my = b.w.z * b.v.x - b.w.x * b.v.z, mz = b.w.x * b.v.y - b.w.y * b.v.x;
      const mm = Math.hypot(mx, my, mz);
      if (mm > 1e-9) { const f = (k * cl * speed * speed) / mm; mx *= f; my *= f; mz *= f; ax += mx; ay += my; az += mz; }
    }
    b.v.x += ax * h; b.v.y += ay * h; b.v.z += az * h;
    const decay = Math.max(0, 1 - P.spinDecay * h);
    b.w.x *= decay; b.w.y *= decay; b.w.z *= decay;
  }
  b.p.x += b.v.x * h; b.p.y += b.v.y * h; b.p.z += b.v.z * h;
  // ground impact
  if (b.p.z < r && b.v.z < 0) {
    const vn = -b.v.z;
    const e = P.restitution[0] + (P.restitution[1] - P.restitution[0]) * smooth(2, 12, vn);
    b.p.z = r;
    b.v.z = vn * e < 0.35 ? 0 : vn * e;
    // tangential impulse limited by friction (Coulomb), drives the contact point towards rolling
    const sx = b.v.x - b.w.y * r, sy = b.v.y + b.w.x * r;
    const slip = Math.hypot(sx, sy);
    if (slip > 1e-6) {
      const maxDv = P.bounceFriction * (1 + e) * vn;
      const needed = slip / (1 + 1.5);     // impulse that would stop the slip (hollow sphere)
      const dv = Math.min(maxDv, needed);
      const dvx = -sx / slip * dv, dvy = -sy / slip * dv;
      b.v.x += dvx; b.v.y += dvy;
      b.w.y += -1.5 * dvx / r; b.w.x += 1.5 * dvy / r;
    }
    if (vn > 1) events.push({ t: b.t + h, kind: "bounce", at: { ...b.p }, speed: vn });
  }
  for (const goal of goals) woodwork(b, prev, goal, events, h);
  b.t += h;
}

function rollLock(b: BallState, r: number) {
  // rolling without slipping: w = (-vy/r, vx/r)
  b.w.x = -b.v.y / r; b.w.y = b.v.x / r;
}

/** Swept sphere against the two posts (vertical) and the bar (horizontal along y). */
function woodwork(b: BallState, _prev: Vec3, goal: Goal, events: BallEvent[], h: number) {
  const R = goal.postRadius + 0.11;
  const tryCylinder = (kind: "post" | "bar", axisPoint: Vec3, axis: "z" | "y", lo: number, hi: number) => {
    // distance from the segment prev->p to the cylinder axis, sampled finely (sub-step is <= 4 cm)
    const along = axis === "z" ? b.p.z : b.p.y;
    if (along < lo - 0.11 || along > hi + 0.11) return;
    const dx = b.p.x - axisPoint.x;
    const d2 = axis === "z" ? b.p.y - axisPoint.y : b.p.z - axisPoint.z;
    const d = Math.hypot(dx, d2);
    if (d >= R) return;
    const nx = dx / (d || 1), n2 = d2 / (d || 1);
    const vn = b.v.x * nx + (axis === "z" ? b.v.y : b.v.z) * n2;
    if (vn >= 0) return;
    const e = 0.7;
    b.v.x -= (1 + e) * vn * nx;
    if (axis === "z") b.v.y -= (1 + e) * vn * n2; else b.v.z -= (1 + e) * vn * n2;
    b.p.x = axisPoint.x + nx * R;
    if (axis === "z") b.p.y = axisPoint.y + n2 * R; else b.p.z = axisPoint.z + n2 * R;
    events.push({ t: b.t + h, kind, at: { ...b.p }, speed: -vn });
  };
  tryCylinder("post", { x: goal.x, y: goal.y0, z: 0 }, "z", 0, goal.height);
  tryCylinder("post", { x: goal.x, y: goal.y1, z: 0 }, "z", 0, goal.height);
  tryCylinder("bar", { x: goal.x, y: 0, z: goal.height }, "y", goal.y0, goal.y1);
}

/** Simulate until rest or `maxT`, returning the sampled path (every `sample` seconds). */
export function simulate(b0: BallState, maxT: number, sample = 0.05, P = BALL_DEFAULTS, goals: Goal[] = [], stop?: (b: BallState) => boolean): { path: BallState[]; events: BallEvent[] } {
  const b: BallState = { p: { ...b0.p }, v: { ...b0.v }, w: { ...b0.w }, t: b0.t };
  const path: BallState[] = [clone(b)];
  const events: BallEvent[] = [];
  while (b.t < maxT) {
    events.push(...stepBall(b, sample, P, goals));
    path.push(clone(b));
    if (len(b.v) < 0.02 && b.p.z <= P.radius + 1e-3) break;
    if (stop?.(b)) break;
  }
  return { path, events };
}
export const clone = (b: BallState): BallState => ({ p: { ...b.p }, v: { ...b.v }, w: { ...b.w }, t: b.t });

/**
 * Launch velocity for a strike: speed, ground direction (rad), elevation (rad), and spin
 * (rad/s) as topspin (+ about the axis left of travel) and sidespin (+ curls to the left).
 */
export function strike(speed: number, heading: number, elevation: number, topspin = 0, sidespin = 0): { v: Vec3; w: Vec3 } {
  const c = Math.cos(elevation);
  const v = { x: speed * c * Math.cos(heading), y: speed * c * Math.sin(heading), z: speed * Math.sin(elevation) };
  // axis "left of travel" = (-sin h, cos h, 0); topspin rotates forward over the top
  // topspin = forward roll sense (same as rollLock): w = (-sin h, cos h, 0) * topspin
  const w = { x: -Math.sin(heading) * topspin, y: Math.cos(heading) * topspin, z: sidespin };
  return { v, w };
}

// ------------------------------------------------------------------ current engine (V6) model, for comparison
/** highlights.py ground ball: constant deceleration GROUND_DECEL (5 m/s^2) for passes, SHOT_DECEL (1.5) for shots. */
export function v6GroundDistance(v0: number, decel: number): { distance: number; time: number } {
  return { distance: (v0 * v0) / (2 * decel), time: v0 / decel };
}
export function v6Path(v0: number, decel: number, dt = 0.1): { t: number; x: number; v: number }[] {
  const out = [{ t: 0, x: 0, v: v0 }];
  let x = 0, v = v0, t = 0;
  while (v > 0 && t < 20) { const nv = Math.max(0, v - decel * dt); x += (v + nv) / 2 * dt; v = nv; t += dt; out.push({ t, x, v }); }
  return out;
}
