import { describe, expect, it } from "vitest";

import { slotRole } from "./roles";

const back = (count: number) => Array.from({ length: count }, (_, i) => ({ id: `df-${i}`, position: "DF", x: Math.round(((i + 1) * 100) / (count + 1)), y: 70 }));

describe("slotRole", () => {
  it("treats the wide defenders of a back four or five as full-backs", () => {
    const four = back(4);
    expect(four.map((s) => slotRole(s, four))).toEqual(["FB", "CB", "CB", "FB"]);
    const five = back(5);
    expect(five.map((s) => slotRole(s, five))).toEqual(["FB", "CB", "CB", "CB", "FB"]);
  });
  it("keeps a back three and other lines as they are", () => {
    const three = back(3);
    expect(three.every((s) => slotRole(s, three) === "CB")).toBe(true);
    expect(slotRole({ id: "gk", position: "GK", x: 50, y: 89 }, [])).toBe("GK");
    expect(slotRole({ id: "st", position: "ST", x: 50, y: 18 }, [])).toBe("ST");
  });
});
