import type { InteractiveCue, InteractiveFrame, InteractiveStep, InteractiveView } from "../../../../lib/api";
import { VISUAL } from "./config";

/**
 * Shared match presentation: turns the OFFICIAL server state (frames recorded by the
 * authoritative physics, already on the real pitch) into a scene that both renderers
 * draw — the 2D canvas and the 3D view. Nothing here decides anything: positions come
 * from the frames, poses come from the timed physics cues (kick, save, tackle…), so an
 * animation can never contradict the result.
 *
 * Coordinates: x along the pitch length (0..1, metres = x·L), y across (0..1), z = ball
 * height in metres.
 */
export type Pose = "idle" | "run" | "kick" | "tackle" | "header" | "dive" | "save" | "hold" | "celebrate" | "ready";
export type ScenePlayer = {
  id: string; name: string; number: number; team: "A" | "D"; role: string; club: string;
  x: number; y: number; vx: number; vy: number; speed: number;
  /** Body orientation in pitch metres (radians, 0 = towards x = 1). */
  facing: number;
  /** Stride cycles run so far in this action (phase = stride · 2π). */
  stride: number;
  pose: Pose; poseK: number; poseDir: number;
  carrier: boolean; keeper: boolean;
};
export type Scene = {
  players: ScenePlayer[];
  ball: { x: number; y: number; z: number; roll: number; visible: boolean; held: boolean };
  step: InteractiveStep | null;
  /** Local time inside the step (s). */
  t: number;
  /** Net ripple: which goal end (0/1), where, how long ago. */
  ripple: { end: 0 | 1; y: number; age: number } | null;
  playing: boolean;
};

const firstSeen = new Map<string, number>();
const strideCache = new WeakMap<InteractiveFrame[], number[][]>();

function stepKey(step: InteractiveStep): string { return `${step.starts_at}:${step.carrier}:${step.type}`; }

/**
 * Local playback time of a step. Latency catch-up: the step starts when this client first
 * saw it, but never lags the official clock by more than VISUAL.maxPlaybackLag.
 */
function localTime(step: InteractiveStep, now: number): number {
  const key = stepKey(step);
  let seen = firstSeen.get(key);
  if (seen === undefined) { seen = now; firstSeen.set(key, seen); if (firstSeen.size > 200) firstSeen.delete(firstSeen.keys().next().value as string); }
  const official = now - step.starts_at;
  const local = now - Math.max(step.starts_at, seen - 0.05);
  return Math.max(0, Math.max(local, official - VISUAL.maxPlaybackLag));
}

/** Which official step is on screen (the executing action, or the bot replay sequence). */
export function currentStep(view: InteractiveView, now: number): { step: InteractiveStep; t: number } | null {
  const opp = view.opportunity;
  if (!opp) return null;
  if (opp.replay && opp.replay.length && (view.state === "REPLAY" || view.state === "OUTCOME")) {
    let start = opp.replay[0].starts_at;
    for (const step of opp.replay) {
      const end = start + step.duration;
      if (now < end + 0.6 || step === opp.replay[opp.replay.length - 1]) return { step, t: Math.max(0, now - start) };
      start = end + 0.6;
    }
  }
  if (opp.last && (view.state === "EXECUTING" || view.state === "OUTCOME" || view.state === "DECISION")) {
    const t = localTime(opp.last, now);
    // A new decision opened while this client is still showing the end of the action: finish it first.
    if (view.state === "DECISION" && t > opp.last.duration + 0.05) return null;
    return { step: opp.last, t };
  }
  return null;
}

export function sample(frames: InteractiveFrame[], t: number): InteractiveFrame {
  if (!frames.length) return [];
  if (t <= frames[0][0]) return frames[0];
  for (let i = 1; i < frames.length; i += 1) {
    if (frames[i][0] >= t) {
      const a = frames[i - 1], b = frames[i];
      const k = (t - a[0]) / Math.max(1e-6, b[0] - a[0]);
      return a.map((v, index) => v + (b[index] - v) * k);
    }
  }
  return frames[frames.length - 1];
}

function cumulative(frames: InteractiveFrame[], count: number, L: number, W: number): number[][] {
  let cached = strideCache.get(frames);
  if (cached) return cached;
  cached = [];
  const acc = new Array(count + 1).fill(0);
  for (let f = 0; f < frames.length; f += 1) {
    if (f > 0) {
      const a = frames[f - 1], b = frames[f];
      acc[count] += Math.hypot((b[1] - a[1]) * L, (b[2] - a[2]) * W);
      // Players: stride CYCLES (not metres). A step cycle lengthens with speed (walk ~1.4 m,
      // sprint ~2.4 m), so the legs move in step with the official displacement (no sliding).
      const dt = Math.max(0.05, b[0] - a[0]);
      for (let i = 0; i < count; i += 1) {
        const d = Math.hypot((b[4 + i * 2] - a[4 + i * 2]) * L, (b[5 + i * 2] - a[5 + i * 2]) * W);
        acc[i] += d / (1.3 + 0.13 * (d / dt));
      }
    }
    cached.push([...acc]);
  }
  strideCache.set(frames, cached);
  return cached;
}

function cueAt(cues: InteractiveCue[] | undefined, kinds: string[], id: string | null, t: number, before: number, after: number): InteractiveCue | null {
  if (!cues) return null;
  for (const cue of cues) {
    if (!kinds.includes(cue.kind) || (id !== null && cue.id !== id)) continue;
    if (t >= cue.t - before && t <= cue.t + after) return cue;
  }
  return null;
}

export function buildScene(view: InteractiveView, now: number): Scene | null {
  const opp = view.opportunity;
  if (!opp) return null;
  const { length: L, width: W } = view.pitch;
  const playing = currentStep(view, now);
  const attackClub = opp.attacking, defendClub = opp.defending;
  let positions = opp.positions;
  let ball: Scene["ball"] = { x: opp.ball[0], y: opp.ball[1], z: 0, roll: 0, visible: true, held: false };
  let prev: InteractiveFrame | null = null;
  let strides: number[] = new Array(opp.roster.length + 1).fill(0);
  const step = playing?.step ?? null;
  const t = playing?.t ?? 0;
  if (step && step.frames.length) {
    const frame = sample(step.frames, t);
    prev = sample(step.frames, Math.max(0, t - 0.12));
    positions = opp.roster.map((_, i) => [frame[4 + i * 2], frame[5 + i * 2]] as [number, number]);
    const cum = cumulative(step.frames, opp.roster.length, L, W);
    const index = Math.min(cum.length - 1, Math.max(0, Math.floor(t / 0.1)));
    strides = cum[index];
    ball = { x: frame[1], y: frame[2], z: frame[3], roll: strides[opp.roster.length] ?? 0, visible: true, held: false };
  }
  const ballM = [ball.x * L, ball.y * W];
  const goalCue = step?.cues?.find((c) => c.kind === "GOAL") ?? null;
  const scorer = goalCue && t >= goalCue.t ? (step?.shooter ?? goalCue.id) : null;
  const goalAge = goalCue && t >= goalCue.t ? t - goalCue.t : (view.state === "OUTCOME" && opp.status === "GOAL" ? 1 : -1);
  const players: ScenePlayer[] = opp.roster.map((p, i) => {
    const [x, y] = positions[i];
    let vx = 0, vy = 0;
    if (prev && step) {
      const dt = Math.max(0.04, Math.min(0.12, t));
      vx = ((x - prev[4 + i * 2]) * L) / dt; vy = ((y - prev[5 + i * 2]) * W) / dt;
    }
    const speed = Math.hypot(vx, vy);
    const keeper = p.role === "GK";
    const toBall = Math.atan2(ballM[1] - y * W, ballM[0] - x * L);
    let facing = speed > 0.6 ? Math.atan2(vy, vx) : toBall;
    let pose: Pose = speed > 0.6 ? "run" : keeper && step?.type === "SHOT" && p.team === "D" ? "ready" : "idle";
    let poseK = 0, poseDir = 0;
    if (step) {
      const kick = cueAt(step.cues, ["KICK"], p.id, t, 0.08, VISUAL.kickPoseSeconds);
      const tackle = cueAt(step.cues, ["TACKLE", "INTERCEPT", "BLOCK"], p.id, t, 0.15, VISUAL.tacklePoseSeconds);
      const header = cueAt(step.cues, ["HEADER"], p.id, t, 0.25, VISUAL.headerPoseSeconds);
      const save = cueAt(step.cues, ["SAVE", "DIVE"], p.id, t, 0.3, VISUAL.divePoseSeconds);
      const claim = cueAt(step.cues, ["CLAIM"], p.id, t, 0.1, 9);
      if (kick) { pose = "kick"; poseK = (t - kick.t + 0.08) / (VISUAL.kickPoseSeconds + 0.08); facing = toBallAtKick(step, i, kick.t, L, W) ?? facing; }
      else if (tackle) { pose = "tackle"; poseK = (t - tackle.t + 0.15) / (VISUAL.tacklePoseSeconds + 0.15); }
      else if (header) { pose = "header"; poseK = (t - header.t + 0.25) / (VISUAL.headerPoseSeconds + 0.25); }
      else if (save) {
        pose = save.kind === "SAVE" && save.hold ? "save" : "dive";
        poseK = Math.min(1, (t - save.t + 0.3) / 0.45);
        poseDir = Math.sign(save.dy ?? 0) || 1;
      } else if (claim && t >= claim.t) { pose = "hold"; }
      if (keeper && p.team === "D" && step.outcome === "SAVED_HELD" && t >= step.duration - 0.05) pose = "hold";
    }
    if (goalAge >= 0 && p.team === "A" && !keeper) {
      const near = Math.hypot((x - ball.x) * L, (y - ball.y) * W) < 30 || p.id === scorer;
      if (near) { pose = "celebrate"; poseK = goalAge; }
    }
    return {
      id: p.id, name: p.name, number: p.number, team: p.team, role: p.role, club: p.team === "A" ? attackClub : defendClub,
      x, y, vx, vy, speed, facing, stride: strides[i] ?? 0, pose, poseK: Math.max(0, Math.min(1, poseK)), poseDir,
      carrier: p.id === opp.carrier && (!step || view.state === "DECISION"), keeper,
    };
  });
  if (players.some((p) => p.pose === "hold")) ball.held = true;
  let ripple: Scene["ripple"] = null;
  if (goalCue && t >= goalCue.t) ripple = { end: ball.x > 0.5 ? 1 : 0, y: ball.y, age: t - goalCue.t };
  return { players, ball, step, t, ripple, playing: Boolean(step) };
}

function toBallAtKick(step: InteractiveStep, i: number, at: number, L: number, W: number): number | null {
  const a = sample(step.frames, at), b = sample(step.frames, at + 0.2);
  if (!a.length) return null;
  const dx = (b[1] - a[1]) * L, dy = (b[2] - a[2]) * W;
  if (Math.hypot(dx, dy) < 0.2) return null;
  void i;
  return Math.atan2(dy, dx);
}

/** Cues whose moment was crossed between two playback times (for sounds and one-shot effects). */
export function crossedCues(step: InteractiveStep | null, from: number, to: number): InteractiveCue[] {
  if (!step?.cues || to <= from) return [];
  return step.cues.filter((c) => c.t > from && c.t <= to);
}
