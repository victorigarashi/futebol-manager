import type { FrameRow } from "../../../lib/api";

/**
 * Ordered buffer of authoritative engine frames (one per game second).
 *
 * The renderer only interpolates between frames the server already produced: it never
 * extrapolates or invents movement. Players follow a Catmull-Rom curve through the
 * frames (smooth acceleration, no corners every second); the ball travels in straight
 * lines (passes) or sticks to the player who has it. Pure module (no DOM).
 */
export type Sample = {
  tick: number;
  ball: { x: number; y: number; owner: number; alpha: number; state: number };
  players: (readonly [number, number] | null)[];
  /** 1 = drawn normally; < 1 while a player is repositioned off-camera (no sliding). */
  alpha: number[];
};

/** A player covering more than this (normalised pitch length) in one tick is a reposition. */
export const JUMP = 0.14;
/** A dead ball moving more than this in one tick is being placed (fade, not a flight). */
const BALL_PLACE_JUMP = 0.12;

export class FrameBuffer {
  private frames: FrameRow[] = [];
  constructor(private readonly capacity = 1800) {}

  get latestTick(): number { return this.frames.length ? this.frames[this.frames.length - 1].t : -1; }
  get earliestTick(): number { return this.frames.length ? this.frames[0].t : -1; }
  get size(): number { return this.frames.length; }

  /** Adds frames, ignoring duplicates and anything older than what we hold (reconnects, retries). */
  push(rows: FrameRow[]): number {
    let added = 0;
    for (const row of rows) {
      if (row.t <= this.latestTick) continue;
      this.frames.push(row);
      added += 1;
    }
    if (this.frames.length > this.capacity) this.frames.splice(0, this.frames.length - this.capacity);
    return added;
  }

  reset(): void { this.frames = []; }

  has(tick: number): boolean { return this.index(tick) !== null; }

  private index(tick: number): number | null {
    const frames = this.frames;
    let low = 0;
    let high = frames.length - 1;
    while (low <= high) {
      const middle = (low + high) >> 1;
      if (frames[middle].t === tick) return middle;
      if (frames[middle].t < tick) low = middle + 1; else high = middle - 1;
    }
    return null;
  }

  /** Interpolated state at a fractional tick, clamped to the buffered range. */
  sample(tick: number): Sample | null {
    const frames = this.frames;
    if (!frames.length) return null;
    if (tick <= frames[0].t) return toSample(undefined, frames[0], frames[0], undefined, 0);
    const last = frames[frames.length - 1];
    if (tick >= last.t) return toSample(undefined, last, last, undefined, 0);
    let low = 0;
    let high = frames.length - 1;
    while (high - low > 1) {
      const middle = (low + high) >> 1;
      if (frames[middle].t <= tick) low = middle; else high = middle;
    }
    const a = frames[low];
    const b = frames[high];
    const span = b.t - a.t;
    // Curve neighbours only when the frames are consecutive game seconds.
    const before = low > 0 && a.t - frames[low - 1].t === span ? frames[low - 1] : undefined;
    const after = high + 1 < frames.length && frames[high + 1].t - b.t === span ? frames[high + 1] : undefined;
    return toSample(before, a, b, after, span > 0 ? (tick - a.t) / span : 0);
  }
}

function catmull(p0: number, p1: number, p2: number, p3: number, t: number): number {
  const t2 = t * t;
  const t3 = t2 * t;
  return 0.5 * (2 * p1 + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t3);
}

function toSample(before: FrameRow | undefined, a: FrameRow, b: FrameRow, after: FrameRow | undefined, mix: number): Sample {
  const players: (readonly [number, number] | null)[] = [];
  const alpha: number[] = [];
  for (let index = 0; index < a.p.length; index += 2) {
    const ax = a.p[index];
    const ay = a.p[index + 1];
    const bx = b.p[index];
    const by = b.p[index + 1];
    if (ax < 0 && bx < 0) { players.push(null); alpha.push(0); continue; }
    // A player who just entered (or left) appears at his authoritative spot without sliding.
    if (ax < 0) { players.push([bx, by] as const); alpha.push(Math.min(1, mix * 2)); continue; }
    if (bx < 0) { players.push([ax, ay] as const); alpha.push(Math.max(0, 1 - mix * 2)); continue; }
    if (Math.hypot(bx - ax, by - ay) > JUMP) {
      // Repositioned by a restart (kick-off, half time): fade out and back in, never slide.
      players.push(mix < 0.5 ? [ax, ay] as const : [bx, by] as const);
      alpha.push(Math.abs(1 - mix * 2));
      continue;
    }
    const usable = (row: FrameRow | undefined) => row && row.p[index] >= 0 && Math.hypot(row.p[index] - ax, row.p[index + 1] - ay) < JUMP * 2 ? row : undefined;
    const p0 = usable(before);
    const p3 = usable(after);
    if (p0 || p3) {
      const x0 = p0 ? p0.p[index] : 2 * ax - bx;
      const y0 = p0 ? p0.p[index + 1] : 2 * ay - by;
      const x3 = p3 ? p3.p[index] : 2 * bx - ax;
      const y3 = p3 ? p3.p[index + 1] : 2 * by - ay;
      players.push([catmull(x0, ax, bx, x3, mix), catmull(y0, ay, by, y3, mix)] as const);
    } else {
      players.push([ax + (bx - ax) * mix, ay + (by - ay) * mix] as const);
    }
    alpha.push(1);
  }
  const [ballAx, ballAy, ownerA, stateA = 0] = a.b;
  const [ballBx, ballBy, ownerB, stateB = 0] = b.b;
  let ball = { x: ballAx + (ballBx - ballAx) * mix, y: ballAy + (ballBy - ballAy) * mix, owner: mix < 0.5 ? ownerA : ownerB, alpha: 1, state: mix < 0.5 ? stateA : stateB };
  if (ownerA >= 0 && ownerA === ownerB && players[ownerA]) {
    // At the feet of the player who has it: follow his (curved) run exactly.
    const [px, py] = players[ownerA]!;
    ball = { ...ball, x: px, y: py };
  }
  if ((stateA === 1 || stateB === 1) && Math.hypot(ballBx - ballAx, ballBy - ballAy) > BALL_PLACE_JUMP) {
    // A dead ball being placed for the restart: fade instead of flying across the pitch.
    ball = { ...ball, x: mix < 0.5 ? ballAx : ballBx, y: mix < 0.5 ? ballAy : ballBy, alpha: Math.abs(1 - mix * 2) };
  }
  return { tick: a.t + (b.t - a.t) * mix, ball, players, alpha };
}

/**
 * Playback clock for replays without a broadcast timeline: advances at a fixed tick
 * rate and stays `lead` ticks behind the newest frame, nudging instead of jumping.
 */
export class PlaybackClock {
  tick = -1;
  constructor(private ticksPerSecond: number, private readonly leadSeconds = 0.8) {}

  setRate(ticksPerSecond: number): void { this.ticksPerSecond = ticksPerSecond; }

  advance(deltaMs: number, latestTick: number, paused = false): number {
    if (latestTick < 0) return this.tick;
    const target = latestTick - this.ticksPerSecond * this.leadSeconds;
    if (this.tick < 0 || Math.abs(target - this.tick) > this.ticksPerSecond * 4) {
      this.tick = Math.max(0, target); // first frame or after a long disconnect: snap
      return this.tick;
    }
    if (!paused) {
      const drift = target - this.tick;
      // Up to ±25% speed correction keeps us in the buffer without visible jumps.
      const correction = Math.max(-0.25, Math.min(0.25, drift / (this.ticksPerSecond * 2)));
      this.tick += (deltaMs / 1000) * this.ticksPerSecond * (1 + correction);
    }
    this.tick = Math.min(this.tick, latestTick);
    return this.tick;
  }
}
