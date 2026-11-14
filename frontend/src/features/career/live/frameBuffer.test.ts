import { describe, expect, it } from "vitest";
import { FrameBuffer, PlaybackClock } from "./frameBuffer";

const frame = (t: number, x: number, extra: number[] = []) => ({ t, b: [x, 0.5, 0] as [number, number, number], p: [x, 0.5, ...extra] });

describe("FrameBuffer", () => {
  it("interpolates only between server frames and clamps to the buffered range", () => {
    const buffer = new FrameBuffer();
    buffer.push([frame(10, 0.2), frame(11, 0.4)]);
    expect(buffer.sample(10.5)?.ball.x).toBeCloseTo(0.3);
    expect(buffer.sample(9)?.ball.x).toBe(0.2);
    expect(buffer.sample(99)?.ball.x).toBe(0.4); // never extrapolates
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
