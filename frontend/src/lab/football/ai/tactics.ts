import { modelFromPace, steer, type PlayerModel, type V2 } from "../physics/player";

/**
 * Football AI research prototype (deterministic, 2D, metres; attack towards +x, goal at x = L).
 *
 *  - Time-to-intercept (TTI): reaction + run time with the force-velocity model, using the
 *    player's current velocity (a player running the wrong way is slower to a point).
 *  - Pitch control: P(attack controls x) = logistic((tDef - tAtt) / 0.45 s).
 *  - Ball travel time on grass with the same rolling model as ball.ts (closed form).
 *  - Off-ball attackers: utility over candidate spots (control, threat, passability,
 *    spacing, role lane, offside, effort), with hysteresis. "Pass and move": after a pass,
 *    the passer values space ahead of him (give-and-go). Overlaps: the full-back values the
 *    outside lane when the winger has the ball.
 *  - Defenders: a block that shifts with the ball (no ball chasing): ONE presser chosen by
 *    TTI, approaching on the side of the most dangerous lane (cover shadow); ONE cover
 *    behind him; the rest hold zones and mark goal-side. A pass in flight is intercepted
 *    only by players that physically get to its path first.
 *  - Carrier: shoot / pass / carry by utility; passes use the same ball model.
 */
export type Team = "A" | "D";
export type Role = "GK" | "CB" | "FB" | "DM" | "CM" | "W" | "ST";
export type Agent = { id: string; team: Team; role: Role; num: number; p: V2; v: V2; anchor: V2; m: PlayerModel; target: V2; score: number; task: string; lastPass: number; side: number };
export type BallState2D = { p: V2; v: V2; owner: string | null; inFlight: { from: V2; to: V2; t0: number; receiver: string | null } | null; lastTouch: Team };
export type World = { L: number; W: number; t: number; agents: Agent[]; ball: BallState2D; events: string[]; params: AIParams; done: string | null; seed: number };
export type AIParams = { block: "low" | "mid" | "high"; pressers: number; reaction: number; temperature: number; hysteresis: number };
export const AI_DEFAULTS: AIParams = { block: "mid", pressers: 1, reaction: 0.25, temperature: 0.45, hysteresis: 0.06 };

const dist = (a: V2, b: V2) => Math.hypot(a.x - b.x, a.y - b.y);
const clamp = (x: number, a: number, b: number) => Math.max(a, Math.min(b, x));
const logistic = (x: number) => 1 / (1 + Math.exp(-x));

// ---------------------------------------------------------------- timing
/** Time for an agent to reach a point (s). */
export function tti(a: Agent, x: V2, reaction: number): number {
  const px = a.p.x + a.v.x * reaction, py = a.p.y + a.v.y * reaction;
  const d = Math.hypot(x.x - px, x.y - py);
  const sp = Math.hypot(a.v.x, a.v.y);
  const along = d > 1e-6 ? (a.v.x * (x.x - px) + a.v.y * (x.y - py)) / d : 0;   // velocity towards the point
  const tau = a.m.vMax / a.m.aMax;
  const turn = sp > 1 && along < 0.5 * sp ? (sp - Math.max(0, along)) / a.m.brake : 0;   // brake/turn first
  return reaction + turn + d / a.m.vMax + tau * (1 - Math.max(0, along) / a.m.vMax);
}
/** Ball rolling time to cover `d` metres from speed v0 (dv/dt = -(a0 + k v)); Infinity if it stops first. */
export function ballTime(v0: number, d: number): number {
  const a0 = 0.065 * 9.81, k = 0.22;
  // x(t) = (v0 + a0/k)(1 - e^{-kt})/k - a0 t / k ; solve numerically
  let t = 0, x = 0, v = v0;
  const h = 0.01;
  while (x < d) { if (v <= 0) return Infinity; v -= (a0 + k * v) * h; x += v * h; t += h; if (t > 10) return Infinity; }
  return t;
}
/** Initial speed so the ball arrives at distance d with speed vEnd. */
export function passSpeed(d: number, vEnd = 6): number {
  const a0 = 0.065 * 9.81, k = 0.22;
  // integrate backwards from vEnd
  let v = vEnd, x = 0;
  const h = 0.01;
  while (x < d) { v += (a0 + k * v) * h; x += v * h; }
  return Math.min(24, v);
}

// ---------------------------------------------------------------- evaluation
export function pitchControl(w: World, x: V2): number {
  let tA = Infinity, tD = Infinity;
  for (const a of w.agents) { const t = tti(a, x, w.params.reaction); if (a.team === "A") tA = Math.min(tA, t); else tD = Math.min(tD, t); }
  return logistic((tD - tA) / w.params.temperature);
}
/** Threat of having the ball at x (simple xT-like surface: distance and angle to goal). */
export function threat(w: World, x: V2): number {
  const g = { x: w.L, y: w.W / 2 };
  const d = dist(x, g);
  const ang = Math.abs(Math.atan2(x.y - g.y, g.x - x.x));
  return clamp(Math.exp(-d / 18) * (1 - ang / 1.8), 0, 1);
}
/** Probability a pass from a to b is completed: no defender reaches the path before the ball. */
export function passSafety(w: World, from: V2, to: V2, receiver?: Agent): number {
  const d = dist(from, to);
  if (d < 1) return 1;
  const v0 = passSpeed(d);
  let worst = Infinity;
  for (let i = 1; i <= 10; i += 1) {
    const k = i / 10;
    const pt = { x: from.x + (to.x - from.x) * k, y: from.y + (to.y - from.y) * k };
    const tb = ballTime(v0, d * k);
    for (const a of w.agents) if (a.team === "D") worst = Math.min(worst, tti(a, pt, w.params.reaction * 0.6) - tb);
  }
  let rec = 1;
  if (receiver) rec = logistic((Math.min(...w.agents.filter((a) => a.team === "D").map((a) => tti(a, to, w.params.reaction))) - tti(receiver, to, 0.1)) / 0.4);
  return logistic(worst / 0.25) * rec;
}

// ---------------------------------------------------------------- decisions
function carrier(w: World): Agent | null { return w.ball.owner ? w.agents.find((a) => a.id === w.ball.owner) ?? null : null; }
function lastDefX(w: World): number { const ds = w.agents.filter((a) => a.team === "D" && a.role !== "GK").map((a) => a.p.x); return ds.length ? Math.max(...ds) : w.L; }

const LANES: Record<Role, (W: number, side: number) => [number, number]> = {
  GK: (W) => [W / 2 - 3, W / 2 + 3], CB: (W) => [W * 0.3, W * 0.7], DM: (W) => [W * 0.3, W * 0.7], CM: (W) => [W * 0.2, W * 0.8],
  FB: (W, s) => (s < 0 ? [2, W * 0.35] : [W * 0.65, W - 2]), W: (W, s) => (s < 0 ? [1.5, W * 0.3] : [W * 0.7, W - 1.5]), ST: (W) => [W * 0.3, W * 0.7],
};

/** Utility of an off-ball attacker standing at x (exposed for the lab's heat view). */
export function spotScore(w: World, a: Agent, x: V2): number {
  const c = carrier(w);
  const pc = pitchControl(w, x);
  const th = threat(w, x);
  const from = c ? c.p : w.ball.p;
  const pass = c && c.id !== a.id ? passSafety(w, from, x) : 0.5;
  let spacing = 0;
  for (const m of w.agents) if (m.team === "A" && m.id !== a.id && m.role !== "GK") { const d = dist(m.target, x); if (d < 9) spacing -= (9 - d) / 9; }
  const [y0, y1] = LANES[a.role](w.W, a.side);
  const lane = x.y < y0 ? -(y0 - x.y) / 6 : x.y > y1 ? -(x.y - y1) / 6 : 0;
  const offside = x.x > lastDefX(w) + 0.3 && (!c || x.x > c.p.x) ? -1.2 : 0;
  const effort = -dist(a.p, x) / 40;
  const tooClose = c && dist(c.p, x) < 7 ? -0.5 : 0;
  // give-and-go: right after passing, space ahead of me is worth more
  const pm = w.t - a.lastPass < 2 ? Math.max(0, (x.x - a.p.x) / 15) * 0.8 : 0;
  // overlap: full-back on the winger's side runs outside him
  let overlap = 0;
  if (a.role === "FB" && c && c.role === "W" && Math.sign(c.side) === Math.sign(a.side)) {
    const outside = a.side < 0 ? x.y < c.p.y - 2 : x.y > c.p.y + 2;
    overlap = outside && x.x > c.p.x - 1 ? 0.6 : 0;
  }
  // through run: behind the line is valuable when the carrier can see it (not pressed, facing forward)
  let through = 0;
  if (a.role === "ST" || a.role === "W") {
    const behind = x.x > lastDefX(w) + 1 && x.x < lastDefX(w) + 14;
    if (behind && c && c.task !== "pressed") through = 0.7 * passSafety(w, c.p, x);
    if (behind) through += 1.0;   // compensates the offside term: the run is timed (the pass is played before he crosses)
  }
  return 1.1 * pc + 1.4 * th + 0.9 * pass + 0.5 * spacing + 1.0 * lane + offside + effort + tooClose + pm + overlap + through * 0.6;
}

function decideAttackers(w: World) {
  const c = carrier(w);
  for (const a of w.agents) {
    if (a.team !== "A" || a.role === "GK" || a.id === w.ball.owner) continue;
    if (w.ball.inFlight && w.ball.inFlight.receiver === a.id) { a.target = { ...w.ball.inFlight.to }; a.task = "recebe"; continue; }
    // candidate spots around the anchor (shifted with the ball) and around the player
    const base = { x: clamp(a.anchor.x + ((c?.p.x ?? w.ball.p.x) - w.L * 0.55) * 0.6, 3, w.L - 2), y: a.anchor.y };
    let best = a.target, bestScore = spotScore(w, a, a.target) + w.params.hysteresis;
    for (let dx = -12; dx <= 14; dx += 2.5) for (let dy = -10; dy <= 10; dy += 2.5) {
      for (const o of [base, a.p]) {
        const x = { x: clamp(o.x + dx, 2, w.L - 1), y: clamp(o.y + dy, 1, w.W - 1) };
        const s = spotScore(w, a, x);
        if (s > bestScore) { bestScore = s; best = x; }
      }
    }
    a.target = best; a.score = bestScore;
    a.task = best.x > lastDefX(w) ? "ruptura" : (a.role === "FB" && c?.role === "W" && Math.abs(best.y - (c?.p.y ?? 0)) > 2 && best.x > (c?.p.x ?? 0) - 1) ? "ultrapassagem" : w.t - a.lastPass < 2 ? "passa e se move" : "apoio";
  }
}

function decideCarrier(w: World, rngv: () => number) {
  const c = carrier(w);
  if (!c) return;
  const g = { x: w.L, y: w.W / 2 };
  const nearestD = Math.min(...w.agents.filter((a) => a.team === "D" && a.role !== "GK").map((a) => dist(a.p, c.p)));
  c.task = nearestD < 3 ? "pressed" : "conduz";
  // shoot?
  const dGoal = dist(c.p, g);
  const shotValue = dGoal < 24 ? threat(w, c.p) * (nearestD > 1.5 ? 1 : 0.6) : 0;
  // best pass
  let bestPass: { to: Agent; at: V2; value: number } | null = null;
  for (const m of w.agents) {
    if (m.team !== "A" || m.id === c.id || m.role === "GK") continue;
    // lead the receiver: pass into the space he is running to
    const lead = { x: m.p.x + m.v.x * 0.6, y: m.p.y + m.v.y * 0.6 };
    const at = { x: clamp(lead.x, 1, w.L - 1), y: clamp(lead.y, 1, w.W - 1) };
    if (at.x > lastDefX(w) + 0.3 && m.p.x > lastDefX(w) + 0.3) continue;   // receiver offside at the pass
    const safe = passSafety(w, c.p, at, m);
    const value = safe * (0.35 + threat(w, at) * 1.6 + pitchControl(w, at) * 0.3) - (at.x < c.p.x - 5 ? 0.15 : 0);
    if (!bestPass || value > bestPass.value) bestPass = { to: m, at, value };
  }
  // carry: open space ahead
  const carryDir = [0, 0.5, -0.5, 1, -1].map((a) => ({ a, x: { x: clamp(c.p.x + Math.cos(a) * 6, 1, w.L - 1), y: clamp(c.p.y + Math.sin(a) * 6, 1, w.W - 1) } }))
    .map((o) => ({ ...o, v: pitchControl(w, o.x) * (0.3 + threat(w, o.x) * 1.4) })).sort((a, b) => b.v - a.v)[0];
  const carryValue = carryDir.v * (nearestD < 2 ? 0.4 : 1);
  const holdTime = w.t - c.lastPass;
  if (shotValue > 0.42 && shotValue > (bestPass?.value ?? 0) * 0.9) { w.done = `Finalização (${(shotValue * 100).toFixed(0)}% de ameaça)`; w.events.push(`${w.t.toFixed(1)}s: #${c.num} chuta`); return; }
  if (bestPass && bestPass.value > carryValue * 1.05 && bestPass.value > 0.3 && holdTime > 0.6) {
    const d = dist(c.p, bestPass.at);
    const v0 = passSpeed(d);
    const dir = { x: (bestPass.at.x - c.p.x) / d, y: (bestPass.at.y - c.p.y) / d };
    // small execution error, seeded
    const err = (rngv() - 0.5) * 0.06;
    const ex = { x: dir.x * Math.cos(err) - dir.y * Math.sin(err), y: dir.x * Math.sin(err) + dir.y * Math.cos(err) };
    w.ball = { p: { ...c.p }, v: { x: ex.x * v0, y: ex.y * v0 }, owner: null, inFlight: { from: { ...c.p }, to: bestPass.at, t0: w.t, receiver: bestPass.to.id }, lastTouch: "A" };
    c.lastPass = w.t;
    w.events.push(`${w.t.toFixed(1)}s: #${c.num} passa para #${bestPass.to.num} (${(passSafety(w, c.p, bestPass.at, bestPass.to) * 100).toFixed(0)}% seguro)`);
    return;
  }
  c.target = carryDir.x;
}

function decideDefenders(w: World) {
  const c = carrier(w);
  const ball = c ? c.p : w.ball.p;
  const defs = w.agents.filter((a) => a.team === "D" && a.role !== "GK");
  const lineX = w.params.block === "low" ? w.L - 18 : w.params.block === "mid" ? w.L - 30 : w.L - 45;
  // block shift: towards the ball, compact (anchors are relative to the block centre)
  const shiftX = clamp((ball.x - (w.L - 25)) * 0.5, -12, 8) + (lineX - (w.L - 30));
  const shiftY = (ball.y - w.W / 2) * 0.45;
  // interception of a pass in flight: only those who physically get there first
  if (w.ball.inFlight) {
    const f = w.ball.inFlight;
    const d = dist(f.from, f.to), v0 = Math.hypot(w.ball.v.x, w.ball.v.y) || passSpeed(d);
    for (const a of defs) {
      let best: V2 | null = null;
      for (let i = 1; i <= 12; i += 1) {
        const k = i / 12, pt = { x: w.ball.p.x + (f.to.x - w.ball.p.x) * k, y: w.ball.p.y + (f.to.y - w.ball.p.y) * k };
        if (tti(a, pt, w.params.reaction) < ballTime(v0, dist(w.ball.p, pt))) { best = pt; break; }
      }
      if (best) { a.target = best; a.task = "intercepta"; }
      else { a.target = { x: clamp(a.anchor.x + shiftX, 2, w.L - 1), y: clamp(a.anchor.y + shiftY, 1, w.W - 1) }; a.task = "recompõe"; }
    }
    return;
  }
  // presser(s): by TTI to the ball, not by distance
  const byTime = [...defs].sort((a, b) => tti(a, ball, 0.1) - tti(b, ball, 0.1));
  const pressers = byTime.slice(0, w.params.pressers);
  const cover = byTime[w.params.pressers];
  // most dangerous lane from the carrier: the attacker with the highest threat-weighted safety
  let lane: Agent | null = null, laneV = -1;
  if (c) for (const m of w.agents) if (m.team === "A" && m.id !== c.id && m.role !== "GK") { const v = threat(w, m.p) + 0.3; if (v > laneV) { laneV = v; lane = m; } }
  const goal = { x: w.L, y: w.W / 2 };
  for (const a of defs) {
    if (pressers.includes(a)) {
      // approach on the line between the ball and the dangerous lane (curved run: cover shadow)
      const toLane = lane ? { x: lane.p.x - ball.x, y: lane.p.y - ball.y } : { x: goal.x - ball.x, y: goal.y - ball.y };
      const l = Math.hypot(toLane.x, toLane.y) || 1;
      a.target = { x: ball.x + toLane.x / l * 1.3, y: ball.y + toLane.y / l * 1.3 };
      a.task = "pressiona";
    } else if (a === cover) {
      const toG = { x: goal.x - ball.x, y: goal.y - ball.y }, l = Math.hypot(toG.x, toG.y) || 1;
      a.target = { x: ball.x + toG.x / l * 7, y: ball.y + toG.y / l * 7 };
      a.task = "cobertura";
    } else {
      const zone = { x: clamp(a.anchor.x + shiftX, 2, w.L - 1), y: clamp(a.anchor.y + shiftY, 1, w.W - 1) };
      // mark the most dangerous attacker inside my zone, goal-side
      let mark: Agent | null = null, md = 9;
      for (const m of w.agents) if (m.team === "A" && m.id !== w.ball.owner && m.role !== "GK") { const d = dist(m.p, zone); if (d < md) { md = d; mark = m; } }
      if (mark) {
        const toG = { x: goal.x - mark.p.x, y: goal.y - mark.p.y }, l = Math.hypot(toG.x, toG.y) || 1;
        a.target = { x: mark.p.x + toG.x / l * 1.6, y: mark.p.y + toG.y / l * 1.6 };
        // never leave the line too far: hold depth near the zone
        a.target.x = Math.max(a.target.x, zone.x - 4);
        a.task = "marca";
      } else { a.target = zone; a.task = "zona"; }
    }
  }
}

// ---------------------------------------------------------------- step
export function step(w: World, dt: number, rngv: () => number) {
  if (w.done) return;
  w.t += dt;
  const thinkEvery = 0.2;
  if (Math.floor(w.t / thinkEvery) !== Math.floor((w.t - dt) / thinkEvery)) {
    decideAttackers(w);
    decideDefenders(w);
    if (w.ball.owner) decideCarrier(w, rngv);
  }
  // move
  for (const a of w.agents) {
    if (a.role === "GK") { a.target = { x: a.team === "D" ? w.L - 1.5 : 1.5, y: clamp(w.W / 2 + (w.ball.p.y - w.W / 2) * 0.15, w.W / 2 - 3, w.W / 2 + 3) }; }
    const intensity = a.task === "pressiona" || a.task === "intercepta" || a.task === "ruptura" || a.task === "ultrapassagem" || a.task === "recebe" ? 1 : a.task === "conduz" || a.task === "pressed" ? 0.8 : 0.72;
    steer(a, a.target, a.m, dt, intensity);
    a.p.x = clamp(a.p.x, 0.5, w.L - 0.5); a.p.y = clamp(a.p.y, 0.5, w.W - 0.5);
  }
  // ball
  const c = carrier(w);
  if (c) {
    const sp = Math.hypot(c.v.x, c.v.y);
    const hx = sp > 0.3 ? c.v.x / sp : 1, hy = sp > 0.3 ? c.v.y / sp : 0;
    w.ball.p = { x: c.p.x + hx * 0.6, y: c.p.y + hy * 0.6 }; w.ball.v = { ...c.v };
    // tackle: a presser within reach for long enough wins it (deterministic contact)
    for (const a of w.agents) if (a.team === "D" && a.role !== "GK" && dist(a.p, w.ball.p) < 0.8) {
      a.score += dt;
      if (a.score > 0.5) { w.done = `Desarme de #${a.num}`; w.events.push(`${w.t.toFixed(1)}s: #${a.num} desarma`); return; }
    }
  } else {
    const sp = Math.hypot(w.ball.v.x, w.ball.v.y);
    if (sp > 0) { const ns = Math.max(0, sp - (0.065 * 9.81 + 0.22 * sp) * dt); w.ball.v.x *= ns / sp; w.ball.v.y *= ns / sp; }
    w.ball.p.x += w.ball.v.x * dt; w.ball.p.y += w.ball.v.y * dt;
    // whoever reaches the ball first controls it (control radius 0.9 m, like CONTROL_RADIUS)
    let best: Agent | null = null, bd = 0.9;
    for (const a of w.agents) { const d = dist(a.p, w.ball.p); if (d < bd) { bd = d; best = a; } }
    if (best && (w.t - (w.ball.inFlight?.t0 ?? -9) > 0.15)) {
      if (best.team === "D") { w.done = `Interceptação de #${best.num}`; w.events.push(`${w.t.toFixed(1)}s: #${best.num} intercepta`); return; }
      w.ball.owner = best.id; w.ball.inFlight = null; w.ball.lastTouch = "A";
      best.lastPass = w.t; best.task = "conduz";
      w.events.push(`${w.t.toFixed(1)}s: #${best.num} domina`);
    }
    if (w.ball.p.x > w.L || w.ball.p.y < 0 || w.ball.p.y > w.W || w.ball.p.x < 0) { w.done = "Bola fora"; return; }
    if (sp < 0.2 && !w.ball.owner) { /* loose ball: nearest attacker by TTI goes */ const near = [...w.agents].filter((a) => a.team === "A").sort((a, b) => tti(a, w.ball.p, 0.1) - tti(b, w.ball.p, 0.1))[0]; if (near) near.target = { ...w.ball.p }; }
  }
  if (w.t > 25) w.done = "Tempo";
}

// ---------------------------------------------------------------- metrics
export function metrics(w: World) {
  const ball = w.ball.p;
  const defs = w.agents.filter((a) => a.team === "D" && a.role !== "GK");
  const atts = w.agents.filter((a) => a.team === "A" && a.role !== "GK");
  const chasers = w.agents.filter((a) => a.role !== "GK" && a.id !== w.ball.owner && dist(a.p, ball) < 6 && (a.v.x * (ball.x - a.p.x) + a.v.y * (ball.y - a.p.y)) > 0.5 && a.task !== "recebe").length;
  const box = (xs: number[]) => (xs.length ? Math.max(...xs) - Math.min(...xs) : 0);
  const nn = atts.map((a) => Math.min(...atts.filter((b) => b !== a).map((b) => dist(a.p, b.p)), 99));
  const c = w.ball.owner ? w.agents.find((a) => a.id === w.ball.owner) : null;
  const options = c ? atts.filter((m) => m.id !== c.id && passSafety(w, c.p, m.p, m) > 0.6).length : 0;
  return {
    chasers, defLength: box(defs.map((a) => a.p.x)), defWidth: box(defs.map((a) => a.p.y)),
    minSpacing: nn.length ? Math.min(...nn) : 0, meanSpacing: nn.length ? nn.reduce((s, x) => s + x, 0) / nn.length : 0, options,
  };
}

// ---------------------------------------------------------------- scenarios
export type ScenarioDef = { id: string; label: string; note: string; L: number; W: number; params?: Partial<AIParams>; attackers: [Role, number, number, number?][]; defenders: [Role, number, number][]; carrier: number };
export const AI_SCENARIOS: ScenarioDef[] = [
  { id: "2v1", label: "2 contra 1", note: "O apoio abre o ângulo; o defensor escolhe entre pressionar e fechar o passe.", L: 50, W: 40, attackers: [["CM", 22, 18], ["ST", 24, 28]], defenders: [["CB", 36, 22], ["GK", 48.5, 20]], carrier: 0 },
  { id: "3v2", label: "3 contra 2", note: "Triângulo de passe: largura dos pontas e um defensor pressionando, outro cobrindo.", L: 55, W: 50, attackers: [["CM", 22, 25], ["W", 26, 8, -1], ["W", 26, 42, 1]], defenders: [["CB", 38, 20], ["CB", 38, 30], ["GK", 53.5, 25]], carrier: 0 },
  { id: "counter", label: "Contra-ataque", note: "4 contra 3 em transição: corridas em profundidade antes da linha recompor.", L: 70, W: 68, params: { block: "high" }, attackers: [["CM", 30, 34], ["W", 32, 12, -1], ["W", 32, 56, 1], ["ST", 36, 30]], defenders: [["CB", 44, 28], ["CB", 44, 40], ["FB", 42, 14], ["GK", 68.5, 34]], carrier: 0 },
  { id: "organised", label: "Ataque organizado", note: "7 contra 7 em meio campo: o bloco médio desliza com a bola; ninguém persegue sem função.", L: 60, W: 68, params: { block: "mid" }, attackers: [["CB", 16, 34], ["FB", 24, 8, -1], ["FB", 24, 60, 1], ["CM", 28, 28], ["CM", 30, 42], ["W", 38, 10, -1], ["ST", 42, 34]], defenders: [["CB", 50, 28], ["CB", 50, 40], ["FB", 48, 14], ["FB", 48, 54], ["DM", 42, 34], ["CM", 40, 24], ["GK", 58.5, 34]], carrier: 3 },
  { id: "through", label: "Passe em profundidade", note: "O centroavante ataca o espaço nas costas da linha alta no momento do passe.", L: 60, W: 68, params: { block: "high" }, attackers: [["CM", 28, 34], ["ST", 38, 32], ["W", 36, 12, -1], ["W", 36, 56, 1]], defenders: [["CB", 42, 28], ["CB", 42, 40], ["FB", 41, 16], ["FB", 41, 52], ["GK", 58.5, 34]], carrier: 0 },
  { id: "onetwo", label: "Tabela", note: "Passa e se move: o passador ataca o espaço às costas do seu marcador e recebe de volta.", L: 55, W: 50, attackers: [["CM", 28, 25], ["ST", 36, 30]], defenders: [["CM", 32, 24], ["CB", 42, 28], ["GK", 53.5, 25]], carrier: 0 },
  { id: "overlap", label: "Ultrapassagem", note: "Com a bola no ponta, o lateral passa por fora e recebe no corredor.", L: 60, W: 68, attackers: [["W", 38, 8, -1], ["FB", 30, 14, -1], ["CM", 32, 30], ["ST", 44, 34]], defenders: [["FB", 44, 10], ["CB", 48, 28], ["CB", 48, 38], ["CM", 40, 26], ["GK", 58.5, 34]], carrier: 0 },
  { id: "cross", label: "Cruzamento", note: "Ponta no último terço: atacantes atacam primeiro e segundo pau; defesa protege a área.", L: 60, W: 68, params: { block: "low" }, attackers: [["W", 50, 6, -1], ["ST", 46, 30], ["CM", 40, 38], ["W", 44, 56, 1]], defenders: [["FB", 52, 9], ["CB", 54, 30], ["CB", 54, 38], ["CM", 48, 34], ["GK", 58.5, 34]], carrier: 0 },
  { id: "lowblock", label: "Defesa compacta", note: "Bloco baixo: duas linhas compactas protegendo o centro; o ataque tem de circular.", L: 60, W: 68, params: { block: "low" }, attackers: [["CB", 22, 34], ["FB", 30, 8, -1], ["FB", 30, 60, 1], ["CM", 32, 26], ["CM", 32, 42], ["W", 40, 12, -1], ["ST", 42, 34]], defenders: [["CB", 52, 28], ["CB", 52, 40], ["FB", 51, 16], ["FB", 51, 52], ["DM", 45, 34], ["CM", 45, 24], ["CM", 45, 44], ["GK", 58.5, 34]], carrier: 3 },
  { id: "highpress", label: "Pressão alta", note: "Saída de bola contra pressão alta: dois pressionadores fecham linhas de passe.", L: 70, W: 68, params: { block: "high", pressers: 2 }, attackers: [["GK", 2, 34], ["CB", 8, 24], ["CB", 8, 44], ["FB", 14, 6, -1], ["FB", 14, 62, 1], ["DM", 18, 34]], defenders: [["ST", 18, 30], ["W", 18, 12], ["W", 18, 56], ["CM", 26, 34], ["CB", 40, 28], ["CB", 40, 40]], carrier: 1 },
];

export function makeWorld(def: ScenarioDef, seed = 1, params: Partial<AIParams> = {}): World {
  let s = seed >>> 0 || 1;
  const rng = () => { s ^= s << 13; s ^= s >>> 17; s ^= s << 5; return ((s >>> 0) % 10000) / 10000; };
  const mk = (team: Team, [role, x, y, side]: [Role, number, number, number?], i: number): Agent => {
    const p = { x: x + (rng() - 0.5) * 0.6, y: y + (rng() - 0.5) * 0.6 };
    return { id: `${team}${i}`, team, role, num: team === "A" ? [9, 10, 7, 11, 8, 6, 3, 2, 4, 5][i] ?? i : [5, 4, 3, 2, 6, 8, 7, 11, 10, 9][i] ?? i, p, v: { x: 0, y: 0 }, anchor: { ...p }, m: modelFromPace(70 + rng() * 20), target: { ...p }, score: 0, task: "", lastPass: -9, side: side ?? (y < def.W / 2 ? -1 : 1) };
  };
  const agents = [...def.attackers.map((a, i) => mk("A", a, i)), ...def.defenders.map((d, i) => mk("D", d, i))];
  const c = agents[def.carrier];
  return { L: def.L, W: def.W, t: 0, agents, ball: { p: { x: c.p.x + 0.6, y: c.p.y }, v: { x: 0, y: 0 }, owner: c.id, inFlight: null, lastTouch: "A" }, events: [], params: { ...AI_DEFAULTS, ...def.params, ...params }, done: null, seed };
}
export function seededRng(seed: number) { let s = (seed * 2654435761) >>> 0 || 1; return () => { s ^= s << 13; s ^= s >>> 17; s ^= s << 5; return ((s >>> 0) % 10000) / 10000; }; }
