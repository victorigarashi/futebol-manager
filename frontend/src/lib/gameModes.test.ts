import { describe, expect, it } from "vitest";

import { GAME_MODES, survivorPath, tournamentStages } from "./gameModes";

describe("game modes", () => {
  it("follows the server's survival path (even fields down to the final)", () => {
    // Same values as backend test_survivor_path_keeps_an_even_field_down_to_a_final.
    expect(survivorPath(8, 0)).toEqual([8, 6, 4, 2]);
    expect(survivorPath(20, 0)).toEqual([20, 16, 12, 8, 6, 4, 2]);
    expect(survivorPath(12, 4)).toEqual([12, 8, 4, 2]);
    for (const size of [8, 12, 16, 20]) for (const n of [0, 2, 4]) expect(survivorPath(size, n).every((v) => v % 2 === 0)).toBe(true);
  });

  it("knows the bracket of each tournament size and the sizes each mode accepts", () => {
    expect(tournamentStages(16)).toHaveLength(4);
    expect(tournamentStages(4)).toEqual(["Semifinal", "Final"]);
    expect(GAME_MODES.find((m) => m.id === "PACK")!.sizes).toEqual([4, 8, 16]);
    expect(GAME_MODES.find((m) => m.id === "SURVIVOR")!.sizes).toEqual([8, 12, 16, 20]);
  });
});
