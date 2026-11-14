import { describe, expect, it } from "vitest";
import type { Formation, SquadPlayer } from "../../lib/api";
import { autoPick, carryOver, fit } from "./lineup";

const player = (id: string, position: string, overall: number): SquadPlayer => ({ id, name: id, club_code: "FLA", age: 25, position, overall, potential: overall, market_value_cents: 0 });
const formation: Formation = { code: "1-1-1", slots: [{ id: "gk", position: "GK", x: 50, y: 89 }, { id: "df", position: "DF", x: 50, y: 70 }, { id: "st", position: "ST", x: 50, y: 18 }] };

describe("lineup helpers", () => {
  it("always puts a real goalkeeper in goal even when an outfielder rates higher improvised", () => {
    const squad = [player("star", "MF", 90), player("keeper", "GK", 55), player("back", "DF", 70), player("nine", "ST", 72)];
    const picked = autoPick(formation, squad);
    expect(picked.gk).toBe("keeper");
    // Outfield slots maximise the effective rating: a 90 midfielder up front is worth 84 > 72.
    expect(picked.st).toBe("star");
  });

  it("applies the same out-of-position penalty as the server", () => {
    expect(fit(player("a", "DF", 70), "DF")).toEqual({ rating: 70, kind: "natural" });
    expect(fit(player("a", "DF", 70), "ST")).toEqual({ rating: 64, kind: "improvised" });
    expect(fit(player("a", "MF", 70), "GK").rating).toBe(58);
  });

  it("keeps chosen players when switching formation", () => {
    const squad = [player("k", "GK", 60), player("d", "DF", 70), player("s", "ST", 75), player("x", "ST", 50)];
    const next = carryOver(formation, { gk: "k", df: "d", st: "s" }, formation, squad);
    expect(new Set(Object.values(next))).toEqual(new Set(["k", "d", "s"]));
  });
});
