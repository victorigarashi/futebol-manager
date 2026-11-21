import { describe, expect, it } from "vitest";
import { BALL_DEFAULTS, newBall, simulate, strike, v6GroundDistance } from "../physics/ball";

describe("ball physics", () => {
  it("a ground pass struck without spin skids, then rolls at ~3/5 of its speed (hollow sphere)", () => {
    const b = newBall({ x: 0, y: 0, z: BALL_DEFAULTS.radius }, { x: 15, y: 0, z: 0 });
    const { path } = simulate(b, 10, 0.02);
    // find the moment slip ends: w.y * r ~ v.x
    const rolling = path.find((s) => Math.abs(s.v.x - s.w.y * BALL_DEFAULTS.radius) < 0.06)!;
    expect(rolling.v.x / 15).toBeGreaterThan(0.55);
    expect(rolling.v.x / 15).toBeLessThan(0.64);
    expect(rolling.p.x).toBeLessThan(15);   // a spinless strike skids for metres before it rolls
  });
  it("a 15 m/s pass travels farther than V6's constant 5 m/s² but stops on grass", () => {
    const { v } = strike(15, 0, 0, 15 / BALL_DEFAULTS.radius * 0.6);   // struck with some forward roll
    const { path } = simulate(newBall({ x: 0, y: 0, z: BALL_DEFAULTS.radius }, v, { x: 0, y: 15 / BALL_DEFAULTS.radius * 0.6, z: 0 }), 20, 0.02);
    const end = path[path.length - 1];
    expect(end.p.x).toBeGreaterThan(v6GroundDistance(15, 5).distance);
    expect(end.p.x).toBeLessThan(80);
    expect(Math.hypot(end.v.x, end.v.y)).toBeLessThan(0.05);
  });
  it("drag: a 30 m/s shot loses 15-30 % of its speed over 20 m", () => {
    const { v, w } = strike(30, 0, 0.12);
    const { path } = simulate(newBall({ x: 0, y: 0, z: 0.11 }, v, w), 3, 0.005);
    const at20 = path.find((s) => s.p.x >= 20)!;
    const sp = Math.hypot(at20.v.x, at20.v.y, at20.v.z);
    expect(sp / 30).toBeGreaterThan(0.7);
    expect(sp / 30).toBeLessThan(0.86);
  });
  it("topspin dips the ball; sidespin curls it (+z spin curls left = +y)", () => {
    const apex = (path: { p: { z: number } }[]) => Math.max(...path.map((s) => s.p.z));
    const base = apex(simulate(newBall({ x: 0, y: 0, z: 0.11 }, strike(25, 0, 0.3).v), 1.2, 0.01).path);
    const top = strike(25, 0, 0.3, 60);
    const dip = apex(simulate(newBall({ x: 0, y: 0, z: 0.11 }, top.v, top.w), 1.2, 0.01).path);
    expect(dip).toBeLessThan(base - 0.4);
    const side = strike(25, 0, 0.2, 0, 50);
    const curl = simulate(newBall({ x: 0, y: 0, z: 0.11 }, side.v, side.w), 1.0, 0.01).path.find((s) => s.p.x > 20)!;
    expect(curl.p.y).toBeGreaterThan(0.8);
  });
  it("bounces lose height (restitution) and the ball ends up rolling", () => {
    const { events, path } = simulate(newBall({ x: 0, y: 0, z: 2 }, { x: 5, y: 0, z: 0 }), 10, 0.01);
    const bounces = events.filter((e) => e.kind === "bounce");
    expect(bounces.length).toBeGreaterThanOrEqual(2);
    expect(bounces[1].speed).toBeLessThan(bounces[0].speed * 0.8);
    expect(path[path.length - 1].p.z).toBeCloseTo(BALL_DEFAULTS.radius, 2);
  });
});
