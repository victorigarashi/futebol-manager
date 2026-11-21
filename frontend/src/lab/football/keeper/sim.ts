import { BALL_DEFAULTS, clone, newBall, stepBall, strike, type BallState, type Goal, type Vec3 } from "../physics/ball";

/**
 * Physical goalkeeper (research prototype, deterministic, no rendering).
 *
 * Frame: goal line on x = 0, mouth y in [-3.66, 3.66], bar at z = 2.44, pitch towards +x.
 * The keeper faces +x, so his left is +y.
 *
 * The keeper never knows the outcome in advance. After the strike he:
 *   1. perceives nothing for `reaction` seconds (perception-action latency);
 *   2. predicts where the ball will cross his plane from the ball he can see (the same
 *      physics, optionally with perception noise);
 *   3. chooses: stay and gather, shuffle (acceleration-limited) or dive;
 *   4. a dive needs `load` seconds to push off, then the centre of mass (CoM) flies
 *      ballistically with limited lateral/vertical take-off speeds — no teleport, no
 *      instant horizontal body;
 *   5. hands extend towards the ball over ~0.18 s; contact is a swept test of the ball
 *      against two hand spheres and a body capsule;
 *   6. catch vs parry depends on the relative speed and how stretched he is; a parry or
 *      block sends the ball off physically (it can still go in, hit the post or rebound).
 */
export type KeeperParams = {
  reaction: number; shuffleSpeed: number; shuffleAccel: number; load: number;
  diveSpeed: number; jumpSpeed: number; reach: number; comHeight: number;
  handRadius: number; bodyRadius: number; catchMaxSpeed: number; recovery: number;
  perceptionNoise: number; offLine: number;
};
/** Elite-ish keeper; see docs/research/football-lab/GOALKEEPER.md for sources and ranges. */
export const KEEPER_DEFAULTS: KeeperParams = {
  reaction: 0.22, shuffleSpeed: 3.0, shuffleAccel: 9.0, load: 0.12,
  diveSpeed: 4.4, jumpSpeed: 2.9, reach: 1.12, comHeight: 0.95,
  handRadius: 0.1, bodyRadius: 0.15, catchMaxSpeed: 24, recovery: 0.75,
  perceptionNoise: 0, offLine: 1.0,
};
/** Map a 0..100 keeping attribute onto the parameters (average 60 vs elite 90). */
export function keeperFromRating(keeping: number, base = KEEPER_DEFAULTS): KeeperParams {
  const k = Math.max(0, Math.min(100, keeping)) / 100;
  return { ...base, reaction: 0.34 - 0.14 * k, diveSpeed: 3.3 + 1.3 * k, jumpSpeed: 2.3 + 0.7 * k, shuffleSpeed: 2.4 + 0.8 * k, catchMaxSpeed: 17 + 9 * k, reach: 1.02 + 0.12 * k };
}

export const GOAL_11: Goal = { x: 0, y0: -3.66, y1: 3.66, height: 2.44, postRadius: 0.06, dir: -1 };

export type KPhase = "set" | "react" | "shuffle" | "gather" | "claimrun" | "load" | "flight" | "ground" | "recover" | "hold";
export type Plan = { kind: "gather" | "shuffle" | "dive" | "collapse" | "jump" | "leave" | "claim"; side: 1 | -1; crossT: number; at: Vec3; vLat?: number; vUp?: number; reason: string };
export type KFrame = {
  t: number; phase: KPhase; com: Vec3; vel: Vec3; tilt: number; diveU: number; side: 1 | -1;
  handL: Vec3; handR: Vec3; reach: number; ball: Vec3; ballSpin: Vec3;
};
export type Outcome = "CATCH" | "PARRY" | "BLOCK" | "GOAL" | "WIDE" | "OVER" | "POST" | "SAVE_POST";
export type KeeperResult = {
  outcome: Outcome; detail: string; frames: KFrame[]; plan: Plan | null;
  contact: { t: number; part: "hands" | "body"; relSpeed: number; extension: number; at: Vec3 } | null;
  takeoff: number | null; strikeToContact: number | null; ballAtLine: Vec3 | null; rebound: Vec3 | null;
  maxComSpeed: number;
};
export type Shot = { from: Vec3; speed: number; heading: number; elevation: number; topspin?: number; sidespin?: number };

const v3 = (x = 0, y = 0, z = 0): Vec3 => ({ x, y, z });
const sub = (a: Vec3, b: Vec3) => v3(a.x - b.x, a.y - b.y, a.z - b.z);
const add = (a: Vec3, b: Vec3, s = 1) => v3(a.x + b.x * s, a.y + b.y * s, a.z + b.z * s);
const len = (a: Vec3) => Math.hypot(a.x, a.y, a.z);
const norm = (a: Vec3) => { const l = len(a) || 1; return v3(a.x / l, a.y / l, a.z / l); };
const smooth = (x: number) => { const t = Math.max(0, Math.min(1, x)); return t * t * (3 - 2 * t); };

/** Aim a shot so that, with drag/spin, it crosses the goal line near `target` (y, z). */
export function aimShot(from: Vec3, target: { y: number; z: number }, speed: number, topspin = 0, sidespin = 0): Shot {
  let heading = Math.atan2(target.y - from.y, -from.x);
  let elevation = Math.atan2(target.z - from.z, Math.hypot(from.x, target.y - from.y)) + 0.02;
  for (let it = 0; it < 30; it += 1) {
    const at = lineCrossing({ from, speed, heading, elevation, topspin, sidespin });
    if (!at) { elevation += 0.05; continue; }
    const ey = target.y - at.y, ez = target.z - at.z;
    if (Math.abs(ey) < 0.01 && Math.abs(ez) < 0.01) break;
    const d = Math.hypot(from.x, target.y - from.y);
    heading -= ey / d * 0.9;        // shooting towards -x: more +y means a smaller heading
    elevation += ez / d * 0.9;
  }
  return { from, speed, heading, elevation, topspin, sidespin };
}

/** Where (and when) an untouched shot crosses x = 0 (null if it never gets there). */
export function lineCrossing(s: Shot): (Vec3 & { t: number }) | null {
  const { v, w } = strike(s.speed, s.heading, s.elevation, s.topspin ?? 0, s.sidespin ?? 0);
  const b = newBall(s.from, v, w);
  let prev = clone(b);
  while (b.t < 4) {
    stepBall(b, 1 / 240);
    if (b.p.x <= 0) {
      const k = prev.p.x / (prev.p.x - b.p.x);
      return { x: 0, y: prev.p.y + (b.p.y - prev.p.y) * k, z: prev.p.z + (b.p.z - prev.p.z) * k, t: prev.t + (b.t - prev.t) * k };
    }
    if (Math.hypot(b.v.x, b.v.y) < 0.05 && b.p.z < 0.12) return null;
    prev = clone(b);
  }
  return null;
}

/** Pre-shot position: on the angle bisector between the posts, `offLine` metres out (less for wide angles). */
export function setPosition(ball: Vec3, P: KeeperParams, goal = GOAL_11): Vec3 {
  const d1 = Math.hypot(ball.x - goal.x, ball.y - goal.y0), d2 = Math.hypot(ball.x - goal.x, ball.y - goal.y1);
  const yc = goal.y0 + (goal.y1 - goal.y0) * (d1 / (d1 + d2));       // angle-bisector theorem
  const dir = norm(v3(ball.x - goal.x, ball.y - yc, 0));
  const dist = Math.hypot(ball.x, ball.y - yc);
  const out = Math.min(P.offLine * (dir.x > 0.5 ? 1 : 0.6), Math.max(0.3, dist - 1.5));
  return v3(goal.x + dir.x * out, yc + dir.y * out, P.comHeight);
}

function predictCrossing(ball: BallState, planeX: number, horizon = 2.5): (Vec3 & { dt: number }) | null {
  const b = clone(ball);
  let prev = clone(b);
  const t0 = b.t;
  while (b.t - t0 < horizon) {
    stepBall(b, 1 / 240);
    if (b.p.x <= planeX) {
      const k = (prev.p.x - planeX) / ((prev.p.x - b.p.x) || 1e-9);
      return { x: planeX, y: prev.p.y + (b.p.y - prev.p.y) * k, z: prev.p.z + (b.p.z - prev.p.z) * k, dt: prev.t + (b.t - prev.t) * k - t0 };
    }
    if (Math.hypot(b.v.x, b.v.y) < 0.3 && b.p.z < 0.12) return null;
    prev = clone(b);
  }
  return null;
}

/** Simple seeded RNG (perception noise only; never decides an outcome by itself). */
function rng(seed: number) { let s = seed >>> 0 || 1; return () => { s ^= s << 13; s ^= s >>> 17; s ^= s << 5; return ((s >>> 0) % 1e6) / 1e6; }; }
function gauss(r: () => number) { const u = Math.max(1e-9, r()), v = r(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); }

export type SimOptions = { keeper?: Partial<KeeperParams>; keeperStart?: Vec3; seed?: number; dt?: number; maxT?: number; frameEvery?: number };

export function simulateShot(shot: Shot, opts: SimOptions = {}): KeeperResult {
  const P: KeeperParams = { ...KEEPER_DEFAULTS, ...opts.keeper };
  const dt = opts.dt ?? 1 / 240;
  const frameEvery = opts.frameEvery ?? 1 / 60;
  const maxT = opts.maxT ?? 3.5;
  const r = rng(opts.seed ?? 1);
  const goal = GOAL_11;
  const { v, w } = strike(shot.speed, shot.heading, shot.elevation, shot.topspin ?? 0, shot.sidespin ?? 0);
  const ball = newBall(shot.from, v, w);
  const R = BALL_DEFAULTS.radius;

  const com = opts.keeperStart ? { ...opts.keeperStart } : setPosition(shot.from, P);
  const vel = v3();
  let phase: KPhase = "react";
  let plan: Plan | null = null;
  let side: 1 | -1 = 1;
  let tLoad = 0, tTake: number | null = null, tLand = 0, tilt = 0, reachNow = 0.354, diveU = 0;
  let aim = norm(v3(0.35, 0, 0.05));
  let lastPlan = -1;
  let contact: KeeperResult["contact"] = null;
  let outcome: Outcome | null = null, detail = "";
  let ballAtLine: Vec3 | null = null, rebound: Vec3 | null = null;
  let maxComSpeed = 0;
  let touched = false;
  const frames: KFrame[] = [];
  let nextFrame = 0;
  const hands = () => {
    // two hands side by side, perpendicular to the reach direction within the body plane
    const c = add(com, aim, reachNow);
    const perp = norm(v3(0, -aim.z, aim.y));
    const spread = touched && outcome === "CATCH" ? 0.08 : 0.1;
    return { L: add(c, perp, spread), R: add(c, perp, -spread) };
  };
  const pushFrame = (t: number) => {
    const h = hands();
    frames.push({ t, phase, com: { ...com }, vel: { ...vel }, tilt, diveU, side, handL: h.L, handR: h.R, reach: reachNow, ball: { ...ball.p }, ballSpin: { ...ball.w } });
  };

  /** Cross/high ball: earliest point of the flight the keeper can reach and catch (z 1.5-2.7 m, inside the 6-yard area + a bit). */
  const claimPoint = (t: number): Plan | null => {
    const b = clone(ball);
    const t0 = b.t;
    while (b.t - t0 < 2.2) {
      stepBall(b, 1 / 120);
      const dt_ = b.t - t0;
      const p = b.p;
      if (p.z > 1.5 && p.z < 2.5 && p.x > 0.4 && p.x < 7 && Math.abs(p.y) < 5.5) {
        const run = Math.hypot(p.x - com.x, p.y - com.y);
        const need = run / (P.shuffleSpeed * 1.6) + 0.35 + P.load;     // run (faster than a shuffle) + jump
        if (need <= dt_) return { kind: "claim", side: p.y >= com.y ? 1 : -1, crossT: t + dt_, at: { ...p }, reason: `sai do gol e agarra no alto (${run.toFixed(1)} m em ${dt_.toFixed(2)} s)` };
      }
      if (p.z < 0.2 && b.v.z <= 0) break;
    }
    return null;
  };

  const plan_ = (t: number): Plan => {
    const cross = predictCrossing(ball, com.x, 3);
    const airborne = ball.p.z > 0.8 || ball.v.z > 2;
    if (airborne && (!cross || cross.z > 2.6 || Math.abs(cross.y - com.y) > 4)) { const c = claimPoint(t); if (c) return c; }
    if (!cross) return { kind: "leave", side: 1, crossT: 0, at: v3(), reason: "bola não chega ao goleiro" };
    // perception error grows with remaining time (estimates sharpen as the ball approaches)
    const noise = P.perceptionNoise * Math.min(1, cross.dt / 0.6);
    const at = v3(cross.x, cross.y + gauss(r) * noise, Math.max(R, cross.z + gauss(r) * noise * 0.6));
    const line = predictCrossing(ball, 0, 3);
    const willScore = line && Math.abs(line.y) < goal.y1 + 0.15 && line.z < goal.height + 0.15;
    const dy = at.y - com.y;
    const s: 1 | -1 = dy >= 0 ? 1 : -1;
    if (!willScore && Math.abs(dy) > 0.8) return { kind: "leave", side: s, crossT: t + cross.dt, at, reason: "fora do alvo: deixa passar" };
    const T = cross.dt;
    // standing reach: hands ~0.75 m sideways at waist height, up to ~2.35 m overhead
    const standLat = 0.72;
    if (Math.abs(dy) <= 0.38 && at.z <= 1.95) return { kind: "gather", side: s, crossT: t + T, at, reason: "no corpo: encaixe" };
    if (at.z > 1.95 && Math.abs(dy) < 1.0) {
      if (T - P.load > 0.36) return { kind: "shuffle", side: s, crossT: t + T, at, reason: "bola alta: posiciona e salta depois" };
      return { kind: "jump", side: s, crossT: t + T, at, reason: "bola alta: salto" };
    }
    // can a shuffle get the hands there in time?
    const need = Math.max(0, Math.abs(dy) - standLat);
    const tt = Math.max(0, T - 0.06);
    const vmax = P.shuffleSpeed, a = P.shuffleAccel;
    const tAcc = vmax / a;
    const reachable = tt <= tAcc ? 0.5 * a * tt * tt : 0.5 * a * tAcc * tAcc + vmax * (tt - tAcc);
    if (need <= reachable * 0.9 && at.z < 1.95) return { kind: "shuffle", side: s, crossT: t + T, at, reason: `passos laterais (${need.toFixed(2)} m em ${T.toFixed(2)} s)` };
    // a dive is timed: if there is more time than the flight needs, keep moving on the feet and commit later
    const tauNeed = Math.max(0.26, (Math.abs(dy) - 0.92 * P.reach) / (0.9 * P.diveSpeed));
    if (T - P.load > tauNeed + 0.1) return { kind: "shuffle", side: s, crossT: t + T, at, reason: `aproxima nos pés; mergulho quando faltarem ${(tauNeed + P.load).toFixed(2)} s` };
    if (at.z < 0.45 && Math.abs(dy) < 1.25) return { kind: "collapse", side: s, crossT: t + T, at, reason: "rasteira perto: colapso" };
    return { kind: "dive", side: s, crossT: t + T, at, reason: `mergulho: ${Math.abs(dy).toFixed(2)} m em ${T.toFixed(2)} s` };
  };

  const startDive = (t: number, p: Plan) => {
    const tau = Math.max(0.06, p.crossT - (t + P.load));       // flight time until the ball arrives
    // aim the CoM so that the stretched arm ends on the ball: C = B - reach * u
    let u = norm(v3(0, p.at.y - com.y, p.at.z - com.z));
    let vL = 0, vU = 0;
    for (let it = 0; it < 4; it += 1) {
      const target = add(p.at, u, -P.reach * 0.92);
      vL = p.kind === "claim" ? vel.y : (target.y - com.y) / tau;
      vU = (target.z - com.z + 0.5 * BALL_DEFAULTS.gravity * tau * tau) / tau;
      vL = Math.max(-P.diveSpeed, Math.min(P.diveSpeed, vL));
      vU = Math.max(p.kind === "collapse" ? -1.2 : -0.6, Math.min(P.jumpSpeed, vU));
      const comAt = v3(com.x, com.y + vL * tau, com.z + vU * tau - 0.5 * BALL_DEFAULTS.gravity * tau * tau);
      u = norm(sub(p.at, comAt));
    }
    p.vLat = vL; p.vUp = vU;
  };

  for (let t = 0; t <= maxT + 1e-9; t += dt) {
    // ---------------- keeper
    if (phase === "react" && t >= P.reaction) phase = "set";
    if (phase === "claimrun") {
      const pl = plan!;
      const dx = pl.at.x - com.x, dy = pl.at.y - com.y, dist = Math.hypot(dx, dy);
      const vmax = P.shuffleSpeed * 1.6;
      const want = dist > 0.05 ? Math.min(vmax, dist * 4) : 0;
      const wx = dist > 0 ? dx / dist * want : 0, wy = dist > 0 ? dy / dist * want : 0;
      const ax = Math.max(-P.shuffleAccel * dt, Math.min(P.shuffleAccel * dt, wx - vel.x)), ay = Math.max(-P.shuffleAccel * dt, Math.min(P.shuffleAccel * dt, wy - vel.y));
      vel.x += ax; vel.y += ay; com.x += vel.x * dt; com.y += vel.y * dt;
      aim = norm(v3(0.3, 0, 0.6)); reachNow = 0.6;
      if (pl.crossT - t <= P.load + 0.32) { phase = "load"; tLoad = t; startDive(t, pl); }
    }
    if ((phase === "set" || phase === "shuffle" || phase === "gather") && !touched && t - lastPlan >= 0.05) {
      lastPlan = t;
      const p = plan_(t);
      plan = p; side = p.side;
      if (p.kind === "dive" || p.kind === "collapse" || p.kind === "jump") { phase = "load"; tLoad = t; startDive(t, p); }
      else if (p.kind === "shuffle") phase = "shuffle";
      else if (p.kind === "claim") phase = "claimrun";
      else if (p.kind === "gather") phase = "gather";
    }
    if (phase === "shuffle" || phase === "gather") {
      const target = plan ? plan.at.y : com.y;
      const want = Math.max(-P.shuffleSpeed, Math.min(P.shuffleSpeed, (target - com.y) * 6));
      const dv = Math.max(-P.shuffleAccel * dt, Math.min(P.shuffleAccel * dt, want - vel.y));
      vel.y += dv;
      com.y += vel.y * dt;
      // arms come up towards the ball as it approaches
      if (plan) {
        // low ball: bend/kneel so the hands can scoop it (CoM down to ~0.45 m)
        const wantZ = plan.at.z < 0.6 ? Math.max(0.45, 0.95 - (0.6 - plan.at.z) * 1.4) : P.comHeight;
        com.z += Math.max(-2.2 * dt, Math.min(2.2 * dt, wantZ - com.z));
        // hands go to where the ball will be, inside the arm envelope (shoulders + 0.68 m), in front of the body
        const shoulder = v3(com.x + 0.05, com.y, com.z + 0.48);
        const goalPt = v3(com.x + 0.45, plan.at.y, plan.at.z);
        const d = sub(goalPt, shoulder);
        const dl = len(d);
        const target = dl > 0.7 ? add(shoulder, d, 0.7 / dl) : goalPt;
        const ready = add(com, v3(0.35, 0, 0.05));                         // hands in front of the waist
        const wantC = add(ready, sub(target, ready), smooth(1 - (plan.crossT - t) / 0.4));
        const cur = add(com, aim, reachNow);
        const step = sub(wantC, cur);
        const sl = len(step), maxStep = 7 * dt;                            // arm speed limit
        const next = sl > maxStep ? add(cur, step, maxStep / sl) : wantC;
        const rel = sub(next, com);
        reachNow = len(rel); aim = norm(rel);
      }
    } else if (phase === "load") {
      // sink and step: the CoM drops a little and drifts towards the side, no take-off yet
      const k = (t - tLoad) / P.load;
      com.z = P.comHeight - 0.12 * Math.sin(Math.min(1, k) * Math.PI / 2);
      vel.y += (side * 1.2 - vel.y) * Math.min(1, dt * 12);
      com.y += vel.y * dt;
      diveU = 0.24 * smooth(k);
      aim = norm(v3(0.1, side, 0.35));
      if (t - tLoad >= P.load) {
        phase = "flight"; tTake = t;
        if (plan!.kind === "claim") {
          // take-off velocity that lands the CoM under the catch point at the right time (no overshoot)
          const tau = Math.max(0.15, plan!.crossT - t);
          const hx = (plan!.at.x - 0.25 - com.x) / tau, hy = (plan!.at.y - com.y) / tau;
          const hs = Math.hypot(hx, hy), cap = P.shuffleSpeed * 1.6;
          vel.x = hs > cap ? hx * cap / hs : hx; vel.y = hs > cap ? hy * cap / hs : hy;
          vel.z = Math.min(P.jumpSpeed, plan!.vUp ?? 2.5);
        }
        else {
          vel.y = plan!.vLat ?? side * P.diveSpeed;
          vel.z = plan!.vUp ?? 1.5;
          vel.x = 0.4;   // keepers dive slightly forward to cut the angle
        }
      }
    } else if (phase === "flight") {
      vel.z -= BALL_DEFAULTS.gravity * dt;
      com.x += vel.x * dt; com.y += vel.y * dt; com.z += vel.z * dt;
      if (plan!.kind !== "claim") vel.x *= 1 - dt * 2;
      const ft = t - (tTake ?? t);
      const reachMax = plan!.kind === "claim" || plan!.kind === "jump" ? 0.95 : P.reach;   // arms up to the ball, not a full dive stretch
      reachNow = 0.55 + (reachMax - 0.55) * smooth(ft / 0.18);
      // the arms track the ball (within ~100° of the dive direction)
      const toBall = norm(sub(ball.p, com));
      const diveDir = norm(v3(0, side, 0.25));
      aim = toBall.y * side > -0.2 ? norm(add(toBall, diveDir, 0.15)) : diveDir;
      // body tilt follows the arms: 0 = upright, 90° = horizontal
      const want = plan!.kind === "claim" || plan!.kind === "jump" ? 0.1 : Math.atan2(Math.abs(aim.y), Math.max(0.05, aim.z)) * 0.9;
      tilt += (want - tilt) * Math.min(1, dt * 7);
      diveU = 0.24 + 0.38 * smooth(ft / Math.max(0.15, (plan!.crossT - tTake!)));
      const upright = plan!.kind === "claim" || plan!.kind === "jump";
      if (com.z <= (upright ? P.comHeight : 0.28) && vel.z < 0) { phase = upright ? "recover" : "ground"; tLand = t; com.z = upright ? P.comHeight : 0.28; vel.z = 0; vel.x = 0; vel.y *= 0.3; }
    } else if (phase === "ground") {
      vel.y *= Math.max(0, 1 - dt * 6); vel.x *= Math.max(0, 1 - dt * 6);
      com.y += vel.y * dt; com.x += vel.x * dt;
      tilt += (Math.PI / 2 - tilt) * Math.min(1, dt * 8);
      diveU = Math.min(1, 0.85 + (t - tLand) * 0.5);
      reachNow = Math.max(0.6, reachNow - dt * 1.5);
      if (t - tLand >= P.recovery) phase = "recover";
    }
    const sp = len(vel);
    if (sp > maxComSpeed) maxComSpeed = sp;

    // ---------------- ball
    const before = clone(ball);
    if (outcome === "CATCH") {
      const h = hands();
      ball.p = v3((h.L.x + h.R.x) / 2, (h.L.y + h.R.y) / 2, (h.L.z + h.R.z) / 2);
      ball.v = { ...vel }; ball.w = v3();
    } else {
      const ev = stepBall(ball, dt, BALL_DEFAULTS, [goal]);
      for (const e of ev) if ((e.kind === "post" || e.kind === "bar") && !outcome) { detail = e.kind === "post" ? "na trave" : "no travessão"; if (touched) outcome = "SAVE_POST"; }
    }
    // ---------------- contact (swept: test the sub-step end; sub-steps move the ball <= 4 cm)
    if (!touched && t >= P.reaction * 0.5) {
      const h = hands();
      const dHandL = len(sub(ball.p, h.L)), dHandR = len(sub(ball.p, h.R));
      const dHand = Math.min(dHandL, dHandR);
      // body capsule: from the feet/hips to the shoulders along the body axis
      const up = v3(0, Math.sin(tilt) * side, Math.cos(tilt));
      const a = add(com, up, -0.72), b = add(com, up, 0.5);
      const ab = sub(b, a);
      const k = Math.max(0, Math.min(1, ((ball.p.x - a.x) * ab.x + (ball.p.y - a.y) * ab.y + (ball.p.z - a.z) * ab.z) / (len(ab) ** 2)));
      const dBody = len(sub(ball.p, add(a, ab, k)));
      const handHit = dHand <= P.handRadius + R && phase !== "react";
      const bodyHit = dBody <= P.bodyRadius + R;
      if (handHit || bodyHit) {
        touched = true;
        const part = handHit ? "hands" as const : "body" as const;
        const centre = handHit ? (dHandL < dHandR ? h.L : h.R) : add(a, ab, k);
        const rel = len(sub(ball.v, vel));
        const extension = Math.max(0, Math.min(1, (reachNow - 0.55) / (P.reach - 0.55)));
        const bothHands = Math.abs(dHandL - dHandR) < 0.16;
        const canHold = part === "hands" && bothHands && rel < P.catchMaxSpeed * (1 - 0.45 * extension) && ball.p.z < 2.4;
        contact = { t, part, relSpeed: rel, extension, at: { ...ball.p } };
        if (canHold) { outcome = "CATCH"; detail = `encaixe (${rel.toFixed(1)} m/s, extensão ${(extension * 100).toFixed(0)}%)`; }
        else {
          const n = norm(sub(ball.p, centre));
          const vn = ball.v.x * n.x + ball.v.y * n.y + ball.v.z * n.z;
          const e = part === "hands" ? 0.3 : 0.45;
          if (vn < 0) ball.v = add(ball.v, n, -(1 + e) * vn);
          // gloves/body absorb tangential speed; the keeper's own motion is added
          ball.v = add(v3(ball.v.x * 0.75, ball.v.y * 0.75, ball.v.z * 0.75), vel, 0.3);
          // a parry is an active push with a firm wrist: outwards (towards the dive side) and away from goal
          if (part === "hands") {
            const push = 4.5 * (1 - 0.5 * extension);
            const outward = side * (Math.abs(ball.p.y) > 1 ? Math.sign(ball.p.y) * side : 1);
            ball.v = add(ball.v, norm(v3(0.7, outward * 0.7, 0.25)), push);
          }
          ball.w = v3(ball.w.x * 0.3, ball.w.y * 0.3, ball.w.z * 0.3);
          detail = part === "hands" ? `espalmada (${rel.toFixed(1)} m/s${bothHands ? "" : ", uma mão"})` : `bloqueio com o corpo (${rel.toFixed(1)} m/s)`;
        }
      }
    }
    // ---------------- goal line
    if (!outcome || outcome === "SAVE_POST") {
      if (before.p.x > 0 && ball.p.x <= 0) {
        const kk = before.p.x / (before.p.x - ball.p.x);
        const at = v3(0, before.p.y + (ball.p.y - before.p.y) * kk, before.p.z + (ball.p.z - before.p.z) * kk);
        ballAtLine = at;
        const inside = Math.abs(at.y) < goal.y1 - R * 0.0 && at.z < goal.height;
        if (inside) { outcome = "GOAL"; detail = touched ? `gol (tocou: ${detail})` : "gol"; }
        else { outcome = touched ? (contact?.part === "body" ? "BLOCK" : "PARRY") : (at.z >= goal.height ? "OVER" : "WIDE"); detail = touched ? `${detail} → escanteio` : (at.z >= goal.height ? "por cima" : "para fora"); }
      }
    }
    if (touched && !outcome && Math.hypot(ball.v.x, ball.v.y) < 6 && ball.p.x > 0.5) {
      outcome = contact?.part === "body" ? "BLOCK" : "PARRY"; rebound = { ...ball.p };
      detail += ` → rebote em (${ball.p.x.toFixed(1)}, ${ball.p.y.toFixed(1)})`;
    }
    if (touched && !outcome && ball.v.x > 0 && ball.p.x > 3) { outcome = contact?.part === "body" ? "BLOCK" : "PARRY"; rebound = { ...ball.p }; detail += " → rebote para a área"; }
    if (t >= nextFrame - 1e-9) { pushFrame(t); nextFrame += frameEvery; }
    // keep simulating a little after the outcome for the animation (landing, recovery)
    if (outcome && frames.length && t > (contact?.t ?? t) + 1.4 && phase !== "flight") break;
    if (!outcome && !touched && t > 2.5 && Math.hypot(ball.v.x, ball.v.y) < 0.5) { outcome = "WIDE"; detail = "bola parou"; }
    if (outcome && !touched && ball.p.x < -1.5) break;
  }
  if (!outcome) { outcome = touched ? "PARRY" : "WIDE"; detail ||= "tempo"; }
  return { outcome, detail, frames, plan, contact, takeoff: tTake, strikeToContact: contact?.t ?? null, ballAtLine, rebound, maxComSpeed };
}

// ------------------------------------------------------------------ V6 model (highlights.py) for comparison
/**
 * Deterministic part of the current `_keeper_vs_shot` with its constants (KEEPER_REACTION,
 * KEEPER_LATERAL, KEEPER_REACH), evaluated on the same ball path at 10 Hz. The V6 code
 * then rolls `rng < 0.15 + keeping*0.4` when the contact is not "clean": we report that
 * probability instead of rolling it.
 */
export function v6KeeperOutcome(shot: Shot, keeping: number): { result: "MISS" | "SAVE" | "MAYBE"; probability: number; reach: number; miss: number } {
  const reaction = 0.42 - keeping / 100 * 0.2;
  const lateral = 1.9 + keeping / 100 * 1.9;
  const { v, w } = strike(shot.speed, shot.heading, shot.elevation, shot.topspin ?? 0, shot.sidespin ?? 0);
  const b = newBall(shot.from, v, w);
  const start = setPosition(shot.from, KEEPER_DEFAULTS);
  let gy = start.y;
  const gx = 0.6;
  let t = 0;
  let prev = clone(b);
  while (t < 3) {
    prev = clone(b);
    stepBall(b, 0.1);
    t += 0.1;
    if (t >= reaction && b.v.x < 0) {
      const timeTo = Math.max(0, (gx - b.p.x) / b.v.x);
      const crossY = b.p.y + b.v.y * timeTo;
      gy += Math.max(-lateral * 0.1, Math.min(lateral * 0.1, crossY - gy));
    }
    if (b.p.x <= gx - 0.3) {
      const k = (prev.p.x - (gx - 0.3)) / (prev.p.x - b.p.x);
      const atY = prev.p.y + (b.p.y - prev.p.y) * k, atZ = prev.p.z + (b.p.z - prev.p.z) * k;
      const dived = t >= reaction + 0.2;
      const reach = 0.75 + (dived ? 1.0 * keeping / 100 : 0.2);
      const top = (dived ? 2.15 : 1.95) + keeping / 100 * 0.25;
      const miss = Math.hypot(Math.abs(atY - gy), Math.max(0, atZ - top) * 1.6);
      if (miss > reach) return { result: "MISS", probability: 0, reach, miss };
      if (miss < reach * 0.45) return { result: "SAVE", probability: 1, reach, miss };
      return { result: "MAYBE", probability: 0.15 + keeping / 100 * 0.4, reach, miss };
    }
  }
  return { result: "MISS", probability: 0, reach: 0, miss: 0 };
}

// ------------------------------------------------------------------ scenario catalogue
export type Scenario = { id: string; label: string; shot: Shot; note: string };
const S = (id: string, label: string, from: [number, number], target: [number, number], speed: number, note: string, spin: [number, number] = [0, 0]): Scenario =>
  ({ id, label, note, shot: aimShot(v3(from[0], from[1], BALL_DEFAULTS.radius), { y: target[0], z: target[1] }, speed, spin[0], spin[1]) });
export function scenarios(): Scenario[] {
  return [
    S("central", "Chute central", [16, 0], [0.2, 0.9], 22, "No corpo: deve encaixar."),
    S("left_low", "Canto esquerdo rasteiro", [16, -2], [3.2, 0.2], 22, "Rasteiro no canto: mergulho baixo."),
    S("right_low", "Canto direito rasteiro", [16, 2], [-3.2, 0.2], 22, "Espelho do anterior."),
    S("left_high", "Ângulo esquerdo (alto)", [18, 0], [3.3, 2.2], 26, "Bola no ângulo: no limite do alcance."),
    S("right_mid", "Meia altura à direita", [18, 3], [-2.4, 1.2], 24, "Mergulho a meia altura."),
    S("close", "Chute de perto (8 m)", [8, 1], [-1.8, 0.6], 24, "Pouco tempo de reação: depende do posicionamento."),
    S("far", "Chute de longe (28 m)", [28, -3], [2.6, 1.6], 25, "Tempo para reagir; defesa esperada."),
    S("strong", "Chute forte (32 m/s)", [18, 0], [2.5, 1.0], 32, "Muito rápido: espalmada ou gol."),
    S("weak", "Chute fraco (13 m/s)", [18, 0], [1.8, 0.4], 13, "Fraco: encaixe."),
    S("out_of_reach", "Fora do alcance", [11, 0], [3.45, 2.1], 28, "Canto superior de perto: deve ser gol mesmo com mergulho."),
    S("in_reach", "Dentro do alcance", [18, -1], [1.3, 1.0], 22, "Perto do goleiro: defesa sem mergulho longo."),
    S("rebound", "Rebote (espalmada forte)", [14, -4], [1.2, 0.5], 30, "Forte e perto do corpo: espalmada e rebote."),
    S("curl", "Chute colocado (efeito)", [20, -6], [2.9, 1.5], 24, "Efeito lateral: a bola curva para fora do goleiro.", [0, -9]),
    S("dip", "Chute com topspin", [25, 0], [0.8, 2.0], 27, "Topspin: cai mais que o previsto pela parábola.", [12, 0]),
    { id: "cross", label: "Cruzamento", note: "Bola alçada da ponta para a pequena área: o goleiro decide sair e agarrar no alto.", shot: { from: v3(6, -26, BALL_DEFAULTS.radius), speed: 21, heading: Math.atan2(26, -2.5), elevation: 0.5, topspin: 0, sidespin: 0 } },
  ];
}
