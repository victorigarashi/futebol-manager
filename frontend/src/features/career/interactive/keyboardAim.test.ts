import { describe, expect, it } from "vitest";

import type { InteractiveView } from "../../../lib/api";
import { predictTarget } from "./gesture";
import { adjustPower, aimAtMate, initialAim, mates, retype, rotateAim, ROTATE_STEP } from "./keyboardAim";

function view(right = true, kind = "BUILDUP"): InteractiveView {
  return {
    match_id: "m", home: "AAA", away: "BBB", state: "DECISION", revision: 1, minute: 10, clock_rate: 0, score: { home: 0, away: 0 }, server_now: 0, deadline: null,
    decision_seconds: 10, state_until: null, grace_until: null, you: "AAA", your_turn: true, controller: "HUMAN", ai_control: [], humans: ["AAA"], connected: {}, ruleset: "ARCADE",
    opportunity: {
      id: "o", kind, label: "", attacking: "AAA", defending: "BBB", minute: 10, status: "LIVE", result: null, actions: 0, max_actions: 8, carrier: "c",
      roster: [
        { id: "c", name: "Carrier", number: 8, team: "A", role: "MF" },
        { id: "m1", name: "Left", number: 7, team: "A", role: "MF" },
        { id: "m2", name: "Right", number: 11, team: "A", role: "ST" },
        { id: "gk", name: "Keeper", number: 1, team: "A", role: "GK" },
        { id: "d1", name: "Def", number: 4, team: "D", role: "DF" },
      ],
      positions: [[0.5, 0.5], [0.6, 0.2], [0.65, 0.8], [0.05, 0.5], [0.7, 0.5]], ball: [0.5, 0.5], last: null, replay: null, opened_at: 0, right,
    },
    pitch: { length: 105, width: 68, goal: 9.516, box: 16.5 }, physics: { pass: [7, 19], loft: [11, 15], loft_range: [12, 46], shot: [16, 18], carry: [4, 11], decel: 5, assist_angle: 0.24 },
    events: [], stats: {},
  };
}
const FROM: [number, number] = [0.5, 0.5];

describe("keyboard play", () => {
  it("starts aimed at the rival goal, in whichever direction the team attacks", () => {
    expect(initialAim(view(true), FROM, "PASS").ux).toBeCloseTo(1, 6);
    expect(initialAim(view(false), FROM, "PASS").ux).toBeCloseTo(-1, 6);
  });

  it("arrows rotate the aim and change the power within 5%..100%", () => {
    const a = initialAim(view(), FROM, "PASS");
    const r = rotateAim(view(), FROM, a, 2, "PASS");
    expect(Math.atan2(r.uy, r.ux)).toBeCloseTo(2 * ROTATE_STEP, 6);
    expect(Math.hypot(r.ux, r.uy)).toBeCloseTo(1, 6);
    expect(adjustPower(view(), FROM, a, 5, "PASS").power).toBe(1);
    expect(adjustPower(view(), FROM, a, -5, "PASS").power).toBe(0.05);
  });

  it("Tab cycles the outfield team-mates (never the carrier or the keeper)", () => {
    expect(mates(view(), FROM).map((m) => m.id).sort()).toEqual(["m1", "m2"]);
  });

  it("aiming at a team-mate picks the power whose physics forecast reaches him", () => {
    const v = view();
    const target = v.opportunity!.positions[1];
    const aim = aimAtMate(v, FROM, target, "PASS");
    const [tx, ty] = predictTarget(v, FROM, aim);
    expect(Math.hypot((tx - target[0]) * 105, (ty - target[1]) * 68)).toBeLessThan(0.3);   // metres
    expect(aim.type).toBe("PASS");
  });

  it("number keys change the action type; a penalty is always a shot", () => {
    const a = initialAim(view(), FROM, "PASS");
    expect(retype(view(), FROM, a, "CARRY").type).toBe("CARRY");
    expect(initialAim(view(true, "PENALTY"), FROM, "PASS").type).toBe("SHOT");
  });
});
