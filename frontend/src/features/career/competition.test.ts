import { describe, expect, it } from "vitest";

import type { KnockoutView, TieView } from "../../lib/api";
import { competitionOf } from "./competition";

const tie = (id: string, competition: "PLAYOFF" | "CUP", stage: string, order: number, winner: string | null = null): TieView => ({
  id, competition, stage, stage_name: stage, high: `H${order}`, low: `L${order}`, legs: 1, order, leg_scores: winner ? [[1, 0]] : [], penalties: null,
  winner, aggregate: winner ? [1, 0] : [0, 0], match_ids: [id], fixtures: [[`H${order}`, `L${order}`]],
});

describe("competitionOf", () => {
  it("groups the server ties by stage, in draw order, and finds the pending stage", () => {
    const knockout: KnockoutView = {
      ties: { b: tie("b", "PLAYOFF", "QF", 2, "H2"), a: tie("a", "PLAYOFF", "QF", 1, "H1"), c: tie("c", "PLAYOFF", "SF", 1), x: tie("x", "CUP", "PRELIM", 1) },
      rounds: [
        { id: "qf", competition: "PLAYOFF", stage: "QF", leg: 1, after_round: 38, tie_ids: ["a", "b"], status: "DONE", stage_name: "Quartas", competition_name: "Playoffs" },
        { id: "sf", competition: "PLAYOFF", stage: "SF", leg: 1, after_round: 38, tie_ids: ["c"], status: "PENDING", stage_name: "Semifinal", competition_name: "Playoffs" },
      ],
      draws: [{ competition: "PLAYOFF", stage: "QF", stage_name: "Quartas", pairs: [["H1", "L1"]], kind: "POTS", pot1: ["H1"], pot2: ["L1"] }],
      cup_enabled: true, cup_seeds: [], cup_champion: null, cup_runner_up: null, playoff_runner_up: null,
    };
    const playoffs = competitionOf(knockout, "PLAYOFF");
    expect(playoffs.stages.map((s) => s.stage)).toEqual(["QF", "SF", "FINAL"]);
    expect(playoffs.stages[0].ties.map((t) => t.id)).toEqual(["a", "b"]);
    expect(playoffs.currentStage).toBe("SF");
    expect(playoffs.ties).toHaveLength(3);
    expect(playoffs.draws).toHaveLength(1);
    expect(competitionOf(knockout, "CUP").stages[0].ties.map((t) => t.id)).toEqual(["x"]);
  });
});
