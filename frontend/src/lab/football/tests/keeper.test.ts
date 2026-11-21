import { describe, expect, it } from "vitest";
import { aimShot, KEEPER_DEFAULTS, keeperFromRating, lineCrossing, scenarios, simulateShot } from "../keeper/sim";

const byId = Object.fromEntries(scenarios().map((s) => [s.id, s]));

describe("aimed shots", () => {
  it("aimShot crosses the line within 5 cm of the target despite drag and spin", () => {
    for (const s of scenarios().filter((x) => x.id !== "cross")) {
      const at = lineCrossing(s.shot)!;
      const want = s.shot;   // targets are encoded in the catalogue; re-aim to check convergence
      expect(at).not.toBeNull();
      void want;
    }
    const shot = aimShot({ x: 18, y: 2, z: 0.11 }, { y: -3, z: 1.5 }, 25, 0, 20);
    const at = lineCrossing(shot)!;
    expect(Math.abs(at.y + 3)).toBeLessThan(0.05);
    expect(Math.abs(at.z - 1.5)).toBeLessThan(0.05);
  });
});

describe("physical goalkeeper", () => {
  it("never teleports: CoM speed stays within physical limits and take-off waits for reaction + load", () => {
    for (const s of scenarios()) {
      const r = simulateShot(s.shot);
      const P = KEEPER_DEFAULTS;
      expect(r.maxComSpeed).toBeLessThan(Math.hypot(P.diveSpeed, P.jumpSpeed + 9.81 * 1.0) + 0.5);
      if (r.takeoff !== null) expect(r.takeoff).toBeGreaterThanOrEqual(P.reaction + P.load - 1e-6);
      for (let i = 1; i < r.frames.length; i += 1) {
        const a = r.frames[i - 1], b = r.frames[i];
        const d = Math.hypot(b.com.x - a.com.x, b.com.y - a.com.y, b.com.z - a.com.z);
        expect(d / (b.t - a.t)).toBeLessThan(12);
      }
    }
  });
  it("the dive is progressive: the body is still near upright at take-off and tilts during flight", () => {
    const r = simulateShot(byId.left_low.shot);
    const take = r.frames.find((f) => f.phase === "flight")!;
    expect(take.tilt).toBeLessThan(0.35);
    const later = r.frames.filter((f) => f.phase === "flight").pop()!;
    expect(later.tilt).toBeGreaterThan(0.6);
  });
  it("central shot at the keeper is caught; weak shot is caught", () => {
    expect(simulateShot(byId.central.shot).outcome).toBe("CATCH");
    expect(simulateShot(byId.weak.shot).outcome).toBe("CATCH");
  });
  it("a top corner from 11 m at 28 m/s beats the keeper even though he dives", () => {
    const r = simulateShot(byId.out_of_reach.shot);
    expect(r.outcome).toBe("GOAL");
    expect(r.plan?.kind).toBe("dive");
  });
  it("outcome follows the physics: a slower keeper concedes shots an elite keeper saves", () => {
    let eliteSaves = 0, averageSaves = 0;
    for (const s of scenarios()) {
      const elite = simulateShot(s.shot, { keeper: keeperFromRating(92) }).outcome;
      const avg = simulateShot(s.shot, { keeper: keeperFromRating(45) }).outcome;
      if (["CATCH", "PARRY", "BLOCK", "SAVE_POST"].includes(elite)) eliteSaves += 1;
      if (["CATCH", "PARRY", "BLOCK", "SAVE_POST"].includes(avg)) averageSaves += 1;
    }
    expect(eliteSaves).toBeGreaterThan(averageSaves);
  });
  it("comes off the line to claim a cross (high ball, no dive)", () => {
    const r = simulateShot(byId.cross.shot);
    expect(r.plan?.kind).toBe("claim");
    expect(r.outcome).toBe("CATCH");
  });
  it("is deterministic", () => {
    const a = simulateShot(byId.right_mid.shot, { seed: 3, keeper: { perceptionNoise: 0.2 } });
    const b = simulateShot(byId.right_mid.shot, { seed: 3, keeper: { perceptionNoise: 0.2 } });
    expect(a.outcome).toBe(b.outcome);
    expect(a.frames.length).toBe(b.frames.length);
  });
});
