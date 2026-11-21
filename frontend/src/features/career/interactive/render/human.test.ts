import { describe, expect, it } from "vitest";

import { BONES, bodyGeometry, colouredGeometry, createHuman } from "./human";

const look = { skin: "#c68a5e", hair: "#1b120c", shirt: "#C8102E", trim: "#111111", shorts: "#111111", socks: "#C8102E", boots: "#111111", hands: "#c68a5e" };
const triangles = (detail: "low" | "medium" | "high") => (bodyGeometry(0, detail).index!.count / 3);

describe("semi-realistic athlete", () => {
  it("fits the geometry budget of each quality level", () => {
    const low = triangles("low"), medium = triangles("medium"), high = triangles("high");
    console.info(`triangles per athlete: low=${low} medium=${medium} high=${high}`);
    expect(low).toBeLessThanOrEqual(3000);
    expect(medium).toBeLessThanOrEqual(6000);
    expect(high).toBeLessThanOrEqual(12000);
    expect(low).toBeLessThan(medium);
    expect(medium).toBeLessThan(high);
  });

  it("has a humanoid skeleton and normalised skin weights", () => {
    const human = createHuman(look, 1, "medium", false);
    expect(human.mesh.skeleton.bones.map((b) => b.name)).toEqual([...BONES]);
    const w = human.mesh.geometry.getAttribute("skinWeight");
    for (let i = 0; i < w.count; i += 97) expect(w.getX(i) + w.getY(i) + w.getZ(i) + w.getW(i)).toBeCloseTo(1, 5);
  });

  it("shares the body between players and only owns its colours", () => {
    const shared = bodyGeometry(2, "low");
    const a = colouredGeometry(shared, look), b = colouredGeometry(shared, { ...look, shirt: "#0f4fa8" });
    expect(a.getAttribute("position")).toBe(b.getAttribute("position"));
    expect(a.index).toBe(shared.index);
    expect(a.getAttribute("color")).not.toBe(b.getAttribute("color"));
  });

  it("is about 1.8 m tall (real scale)", () => {
    const g = bodyGeometry(0, "medium");
    g.computeBoundingBox();
    const h = g.boundingBox!.max.y - g.boundingBox!.min.y;
    expect(h).toBeGreaterThan(1.72);
    expect(h).toBeLessThan(1.92);
  });
});

describe("cosmetic look from any player id", () => {
  it("never indexes outside the palettes (unsigned hash)", async () => {
    const { hashOf, VISUAL } = await import("./config");
    for (const id of ["p-1", "jogador-99", "x".repeat(40), "Ωmega", "123456789", "demo:FLA:ST:9"]) {
      const look = hashOf(id);
      expect(look).toBeGreaterThanOrEqual(0);
      expect(VISUAL.hair[(look >>> 4) % VISUAL.hair.length]).toBeDefined();
      expect([0, 1, 2, 3]).toContain((look >>> 12) % 4);
    }
  });
});
