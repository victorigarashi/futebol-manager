import type { BroadcastSegment } from "../../../lib/api";

/**
 * Client side of the condensed broadcast.
 *
 * The server decides which game ticks are shown when (segments with server-clock
 * times). The client only estimates the server clock and plays the timeline a fixed
 * delay behind it, so every viewer of a match sees the same moment at the same time
 * and the match length never depends on the viewer's hardware. Pure module (no DOM).
 */
export const DISPLAY_DELAY_SECONDS = 1.0;

export type BroadcastView = {
  tick: number;
  kind: BroadcastSegment["k"] | "WAIT";
  label: string;
  /** Present during a cut: the edges being cross-faded and how far the transition is. */
  cut: { from: number; to: number; progress: number } | null;
};

export class BroadcastTimeline {
  private segments: BroadcastSegment[] = [];

  get size(): number { return this.segments.length; }
  get last(): BroadcastSegment | undefined { return this.segments[this.segments.length - 1]; }

  /** Adds segments from any source (live view, socket push, reconnect); duplicates ignored. */
  merge(rows: BroadcastSegment[] | null | undefined): void {
    if (!rows?.length) return;
    const byStart = new Map(this.segments.map((s) => [s.r0, s]));
    for (const row of rows) byStart.set(row.r0, row);
    this.segments = [...byStart.values()].sort((a, b) => a.r0 - b.r0).slice(-400);
  }

  reset(): void { this.segments = []; }

  /** What to show at server time `time`. Holds the last known moment instead of guessing. */
  at(time: number): BroadcastView {
    const list = this.segments;
    if (!list.length || time < list[0].r0) return { tick: list.length ? list[0].t0 : 0, kind: "WAIT", label: "", cut: null };
    let low = 0;
    let high = list.length - 1;
    while (low < high) {
      const middle = (low + high + 1) >> 1;
      if (list[middle].r0 <= time) low = middle; else high = middle - 1;
    }
    const segment = list[low];
    const span = segment.r1 - segment.r0;
    const progress = span > 0 ? Math.min(1, Math.max(0, (time - segment.r0) / span)) : 1;
    const tick = segment.t0 + (segment.t1 - segment.t0) * progress;
    if (time > segment.r1 && low === list.length - 1) {
      // Past the end of what the server has sent so far (network hiccup): hold.
      return { tick: segment.t1, kind: segment.k === "CUT" ? "WAIT" : segment.k, label: segment.label, cut: null };
    }
    return {
      tick, kind: segment.k, label: segment.label,
      cut: segment.k === "CUT" ? { from: segment.t0, to: segment.t1, progress } : null,
    };
  }
}

/**
 * Estimates `server time - local time` from timestamped messages. Network delay only
 * ever makes a message look older, so the largest observed offset is the best one;
 * it decays slowly so a changed system clock is eventually followed.
 */
export class ServerClock {
  private offset: number | null = null;

  observe(serverNow: number | undefined | null, localNow = Date.now() / 1000): void {
    if (typeof serverNow !== "number" || !Number.isFinite(serverNow)) return;
    const sample = serverNow - localNow;
    if (this.offset === null || sample > this.offset) this.offset = sample;
    else this.offset = this.offset * 0.98 + sample * 0.02;
  }

  now(localNow = Date.now() / 1000): number { return localNow + (this.offset ?? 0); }
  get known(): boolean { return this.offset !== null; }
}
