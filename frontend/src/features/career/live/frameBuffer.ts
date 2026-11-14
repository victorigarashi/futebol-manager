import type { FrameRow } from "../../../lib/api";

/**
 * Ordered buffer of authoritative engine frames (one per game second).
 *
 * The renderer plays slightly behind the newest frame and only interpolates
 * between two frames the server already produced: it never extrapolates or
 * invents movement. Pure module (no DOM) so it can be unit-tested.
 */
export type Sample = { tick: number; ball: { x: number; y: number; owner: number }; players: (readonly [number, number] | null)[] };

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

  /** Interpolated state at a fractional tick, clamped to the buffered range. */
  sample(tick: number): Sample | null {
    const frames = this.frames;
    if (!frames.length) return null;
    if (tick <= frames[0].t) return toSample(frames[0], frames[0], 0);
    const last = frames[frames.length - 1];
    if (tick >= last.t) return toSample(last, last, 0);
    // Binary search for the frame just before `tick`.
    let low = 0;
    let high = frames.length - 1;
    while (high - low > 1) {
      const middle = (low + high) >> 1;
      if (frames[middle].t <= tick) low = middle; else high = middle;
    }
    const a = frames[low];
    const b = frames[high];
    const span = b.t - a.t;
    return toSample(a, b, span > 0 ? (tick - a.t) / span : 0);
  }
}

function toSample(a: FrameRow, b: FrameRow, mix: number): Sample {
  const players: (readonly [number, number] | null)[] = [];
  for (let index = 0; index < a.p.length; index += 2) {
    const ax = a.p[index];
    const bx = b.p[index];
    if (ax < 0 && bx < 0) { players.push(null); continue; }
    // A player who just entered (or left) appears at his authoritative spot without sliding.
    if (ax < 0) { players.push([bx, b.p[index + 1]] as const); continue; }
    if (bx < 0) { players.push([ax, a.p[index + 1]] as const); continue; }
    players.push([ax + (bx - ax) * mix, a.p[index + 1] + (b.p[index + 1] - a.p[index + 1]) * mix] as const);
  }
  return {
    tick: a.t + (b.t - a.t) * mix,
    ball: { x: a.b[0] + (b.b[0] - a.b[0]) * mix, y: a.b[1] + (b.b[1] - a.b[1]) * mix, owner: mix < 0.5 ? a.b[2] : b.b[2] },
    players,
  };
}

/**
 * Playback clock: advances at the server's tick rate and stays `lead` ticks behind the
 * newest frame, nudging smoothly instead of jumping when the network stutters.
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
