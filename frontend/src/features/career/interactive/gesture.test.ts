import { describe, expect, it } from "vitest";

import type { InteractiveView } from "../../../lib/api";
import { aimFromDrag, attackDir, fromScreen, inferType, predictTarget, toScreen, type Geometry } from "./gesture";

function view(right: boolean): InteractiveView {
  return {
    match_id: "m", home: "AAA", away: "BBB", state: "DECISION", revision: 1, minute: 10, clock_rate: 0, score: { home: 0, away: 0 }, server_now: 0, deadline: null,
    decision_seconds: 10, state_until: null, grace_until: null, you: "AAA", your_turn: true, controller: "HUMAN", ai_control: [], humans: ["AAA"], connected: {}, ruleset: "ARCADE",
    opportunity: { id: "o", kind: "BUILDUP", label: "", attacking: "AAA", defending: "BBB", minute: 10, status: "LIVE", result: null, actions: 0, max_actions: 8, carrier: "p", roster: [], positions: [], ball: [0.5, 0.5], last: null, replay: null, opened_at: 0, right },
    pitch: { length: 105, width: 68, goal: 9.516, box: 16.5 }, physics: { pass: [7, 19], loft: [11, 15], loft_range: [12, 46], shot: [16, 18], carry: [4, 11], decel: 5, assist_angle: 0.24 },
    events: [], stats: {},
  };
}

describe("Modo Jogável gesture", () => {
  it("the same drag on the pitch gives the same intent whatever renderer picked the points", () => {
    // 2D: screen -> pitch by inverse projection; 3D: raycast. Both end as pitch points.
    const g: Geometry = { width: 1200, height: 800, portrait: false, pad: 6, ratio: 105 / 68, mx: 0.03, my: 0.05 };
    const start = fromScreen(g, ...toScreen(g, 0.4, 0.5));
    const end = fromScreen(g, ...toScreen(g, 0.6, 0.55));
    const a2d = aimFromDrag(view(true), [0.5, 0.5], start, end, "PASS")!;
    const a3d = aimFromDrag(view(true), [0.5, 0.5], [0.4, 0.5], [0.6, 0.55], "PASS")!;
    expect(a2d.power).toBeCloseTo(a3d.power, 6);
    expect(a2d.ux).toBeCloseTo(a3d.ux, 6);
    expect(a2d.uy).toBeCloseTo(a3d.uy, 6);
  });

  it("portrait rotation is undone exactly", () => {
    const g: Geometry = { width: 390, height: 844, portrait: true, pad: 6, ratio: 105 / 68, mx: 0.03, my: 0.05 };
    const [x, y] = fromScreen(g, ...toScreen(g, 0.73, 0.21));
    expect(x).toBeCloseTo(0.73, 6); expect(y).toBeCloseTo(0.21, 6);
  });

  it("power is the drag length over 40% of the pitch, capped at 100%", () => {
    expect(aimFromDrag(view(true), [0.5, 0.5], [0.1, 0.5], [0.3, 0.5], "PASS")!.power).toBeCloseTo(0.5, 6);
    expect(aimFromDrag(view(true), [0.5, 0.5], [0, 0.5], [0.9, 0.5], "PASS")!.power).toBe(1);
    expect(aimFromDrag(view(true), [0.5, 0.5], [0.5, 0.5], [0.505, 0.5], "PASS")).toBeNull();
  });

  it("shots and the automatic type follow the attack direction of the half", () => {
    const right = view(true), left = view(false);
    expect(attackDir(right)).toBe(1); expect(attackDir(left)).toBe(-1);
    expect(inferType(right, [0.85, 0.5], 1, 0)).toBe("SHOT");
    expect(inferType(left, [0.15, 0.5], -1, 0)).toBe("SHOT");
    expect(inferType(left, [0.85, 0.5], 1, 0)).not.toBe("SHOT");   // towards the own goal: never an automatic shot
    expect(predictTarget(left, [0.2, 0.5], { ux: -1, uy: 0, power: 0.8, type: "SHOT" })[0]).toBeCloseTo(0, 3);
    expect(predictTarget(right, [0.8, 0.5], { ux: 1, uy: 0, power: 0.8, type: "SHOT" })[0]).toBeCloseTo(1, 3);
  });
});
