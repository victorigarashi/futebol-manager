import { describe, expect, it } from "vitest";

import { rollStep } from "./ball";

describe("ball roll", () => {
  it("does not spin while the ball is still", () => {
    const step = rollStep({ x: 3, z: 4 }, { x: 3, z: 4 }, 0.15);
    expect(step.angle).toBe(0);
    expect(step.distance).toBe(0);
  });

  it("turns about -z when rolling along +x (top moves forward)", () => {
    const step = rollStep({ x: 0, z: 0 }, { x: 1, z: 0 }, 0.15);
    expect(step.axis[0]).toBeCloseTo(0);
    expect(step.axis[1]).toBe(0);
    expect(step.axis[2]).toBeCloseTo(-1);
    expect(step.angle).toBeGreaterThan(0);
  });

  it("turns about +x when rolling across towards +z", () => {
    const step = rollStep({ x: 0, z: 0 }, { x: 0, z: 1 }, 0.15);
    expect(step.axis[2]).toBeCloseTo(0);
    expect(step.axis[0]).toBeCloseTo(1);
  });

  it("spins proportionally to the distance and caps a snapshot jump", () => {
    const small = rollStep({ x: 0, z: 0 }, { x: 0.3, z: 0 }, 0.15);
    expect(small.angle).toBeCloseTo(0.3 / 0.15, 5);
    const jump = rollStep({ x: 0, z: 0 }, { x: 90, z: 0 }, 0.15);
    expect(jump.angle).toBeCloseTo(Math.PI, 5);
    expect(Number.isFinite(jump.axis[0]) && Number.isFinite(jump.axis[2])).toBe(true);
  });

  it("handles a degenerate radius", () => {
    const step = rollStep({ x: 0, z: 0 }, { x: 1, z: 0 }, 0);
    expect(Number.isFinite(step.angle)).toBe(true);
  });
});
