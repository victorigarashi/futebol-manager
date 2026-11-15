import { describe, expect, it } from "vitest";

import type { BroadcastSegment } from "../../../lib/api";
import { BroadcastTimeline, ServerClock } from "./broadcastClock";

const seg = (k: BroadcastSegment["k"], t0: number, t1: number, r0: number, r1: number, label = ""): BroadcastSegment => ({ k, t0, t1, r0, r1, label });

describe("BroadcastTimeline", () => {
  const timeline = new BroadcastTimeline();
  timeline.merge([seg("PLAY", 0, 6, 100, 102.5, "KICK_OFF"), seg("CUT", 6, 300, 102.5, 103.5)]);
  timeline.merge([seg("CUT", 6, 300, 102.5, 103.5), seg("PLAY", 300, 320, 103.5, 112.5, "BUILD_UP"), seg("BREAK", 2700, 2700, 140, 144, "HALF_TIME")]);

  it("maps server time to game time at the speed the server chose", () => {
    expect(timeline.size).toBe(4); // duplicates from a second source are merged
    expect(timeline.at(101.25).tick).toBeCloseTo(3);
    expect(timeline.at(108).tick).toBeCloseTo(310);
    // 20 ticks in 9 s: about 2.2× real time, far from the 30× of a raw linear clock.
    expect((320 - 300) / (112.5 - 103.5)).toBeLessThan(3);
  });

  it("describes a cut as a transition between its two edges", () => {
    const view = timeline.at(103);
    expect(view.kind).toBe("CUT");
    expect(view.cut).toEqual({ from: 6, to: 300, progress: 0.5 });
  });

  it("holds the last known moment when the stream is late instead of inventing play", () => {
    const view = timeline.at(150);
    expect(view.tick).toBe(2700);
    expect(view.cut).toBeNull();
  });

  it("waits before kick-off", () => {
    expect(timeline.at(50).kind).toBe("WAIT");
  });
});

describe("ServerClock", () => {
  it("keeps the least-delayed offset estimate", () => {
    const clock = new ServerClock();
    clock.observe(1000.0, 990.0);   // offset 10 s (fast message)
    clock.observe(1000.5, 990.9);   // 9.6 s: this one was delayed in the network
    expect(clock.now(991)).toBeGreaterThan(1000.9);
    expect(clock.known).toBe(true);
  });
});
