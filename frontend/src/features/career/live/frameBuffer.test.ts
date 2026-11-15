import { describe, expect, it } from "vitest";
import { FrameBuffer, PlaybackClock } from "./frameBuffer";

const frame = (t: number, x: number, extra: number[] = []) => ({ t, b: [x, 0.5, 0] as [number, number, number], p: [x, 0.5, ...extra] });

describe("FrameBuffer", () => {
  it("interpolates only between server frames and clamps to the buffered range", () => {
    const buffer = new FrameBuffer();
    buffer.push([frame(10, 0.2), frame(11, 0.26)]);
    expect(buffer.sample(10.5)?.ball.x).toBeCloseTo(0.23);
    expect(buffer.sample(9)?.ball.x).toBe(0.2);
    expect(buffer.sample(99)?.ball.x).toBe(0.26); // never extrapolates
  });

  it("ignores duplicate and stale frames delivered again after a reconnect", () => {
    const buffer = new FrameBuffer();
    expect(buffer.push([frame(1, 0.1), frame(2, 0.2)])).toBe(2);
    expect(buffer.push([frame(2, 0.9), frame(1, 0.9), frame(3, 0.3)])).toBe(1);
    expect(buffer.sample(2)?.ball.x).toBe(0.2);
    expect(buffer.latestTick).toBe(3);
  });

  it("does not slide substitutes in from the corner", () => {
    const buffer = new FrameBuffer();
    buffer.push([frame(1, 0.5, [-1, -1]), frame(2, 0.5, [0.8, 0.1])]);
    expect(buffer.sample(1.5)?.players[1]).toEqual([0.8, 0.1]);
  });
});

describe("PlaybackClock", () => {
  it("stays behind the newest frame and catches up smoothly", () => {
    const clock = new PlaybackClock(30, 0.5);
    expect(clock.advance(16, 100)).toBe(85);
    const next = clock.advance(100, 103);
    expect(next).toBeGreaterThan(85);
    expect(next).toBeLessThanOrEqual(103);
  });
});

describe("smooth, honest motion", () => {
  const row = (t: number, px: number, ball: [number, number, number, number?], extra: number[] = []) => ({ t, b: ball as [number, number, number, number?], p: [px, 0.5, ...extra] });

  it("moves players along a smooth curve through the server frames (no corners every second)", () => {
    const buffer = new FrameBuffer();
    // Accelerating run: 0.10 → 0.12 → 0.16 → 0.22.
    buffer.push([row(1, 0.10, [0, 0, -1]), row(2, 0.12, [0, 0, -1]), row(3, 0.16, [0, 0, -1]), row(4, 0.22, [0, 0, -1])]);
    const xs = [2, 2.25, 2.5, 2.75, 3].map((t) => buffer.sample(t)!.players[0]![0]);
    expect(xs[0]).toBeCloseTo(0.12);
    expect(xs[4]).toBeCloseTo(0.16);
    // Monotonic and accelerating, passing exactly through the authoritative frames.
    for (let i = 1; i < xs.length; i += 1) expect(xs[i]).toBeGreaterThan(xs[i - 1]);
    expect(xs[4] - xs[3]).toBeGreaterThan(xs[1] - xs[0]);
  });

  it("never slides a repositioned player across the pitch", () => {
    const buffer = new FrameBuffer();
    buffer.push([row(10, 0.10, [0.5, 0.5, -1, 1]), row(11, 0.50, [0.5, 0.5, -1, 1])]);
    for (const t of [10.1, 10.3, 10.49, 10.51, 10.7, 10.9]) {
      const s = buffer.sample(t)!;
      const x = s.players[0]![0];
      expect(x === 0.10 || x === 0.50).toBe(true); // only the two real spots, never in between
      expect(s.alpha[0]).toBeLessThan(1);
    }
  });

  it("flies the ball in a straight line on a pass and keeps it at the feet of its owner", () => {
    const buffer = new FrameBuffer();
    buffer.push([
      row(1, 0.30, [0.30, 0.5, 0, 0]),     // player 0 has it
      row(2, 0.31, [0.45, 0.5, -1, 2]),    // in flight
      row(3, 0.32, [0.60, 0.5, -1, 0]),
    ]);
    expect(buffer.sample(1.5)!.ball.x).toBeCloseTo(0.375);
    expect(buffer.sample(2.5)!.ball.x).toBeCloseTo(0.525);
    const owned = new FrameBuffer();
    owned.push([row(1, 0.30, [0.30, 0.5, 0, 0]), row(2, 0.34, [0.34, 0.5, 0, 0]), row(3, 0.40, [0.40, 0.5, 0, 0])]);
    const s = owned.sample(2.5)!;
    expect(s.ball.x).toBeCloseTo(s.players[0]![0]);
  });

  it("fades a dead ball while it is placed for the restart instead of flying it", () => {
    const buffer = new FrameBuffer();
    buffer.push([row(1, 0.5, [1.01, 0.5, -1, 1]), row(2, 0.5, [0.5, 0.5, -1, 1])]); // from the net to the centre spot
    const mid = buffer.sample(1.25)!;
    expect(mid.ball.x).toBe(1.01);
    expect(mid.ball.alpha).toBeLessThan(1);
  });
});
