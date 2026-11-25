import { describe, expect, it } from "vitest";

import { previewOverall } from "./customPlayer";

// The same weights the server serves (backend/app/domain/custom_players.py WEIGHTS).
const RULES = {
  attribute_min: 30, attribute_max: 90, max_overall: 80, max_per_club: 3,
  outfield_keys: ["pace", "shooting", "passing", "dribbling", "defending", "physical"],
  keeper_keys: ["gk_diving", "gk_handling", "gk_reflexes", "gk_positioning"],
  weights: { ST: { shooting: 0.4, pace: 0.2, dribbling: 0.2, physical: 0.1, passing: 0.1 } },
};

describe("created player overall preview", () => {
  it("matches the server's formula (same case as backend test_custom_players)", () => {
    const striker = { pace: 88, shooting: 82, passing: 60, dribbling: 80, defending: 35, physical: 70 };
    expect(previewOverall(RULES, "ST", striker)).toBe(Math.round(82 * 0.4 + 88 * 0.2 + 80 * 0.2 + 70 * 0.1 + 60 * 0.1));
    expect(previewOverall(RULES, "ST", striker)).toBe(79);
  });
});
