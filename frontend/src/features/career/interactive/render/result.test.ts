import { describe, expect, it } from "vitest";

import type { InteractiveView } from "../../../../lib/api";
import { endPhase, endScorers, endScore, endVerdict, lastMatchOf } from "./result";

function view(partial: Partial<InteractiveView>): InteractiveView {
  return {
    match_id: "m1", home: "COR", away: "SAO", state: "DECISION", revision: 3, minute: 42, clock_rate: 4,
    score: { home: 1, away: 0 }, server_now: 10, deadline: 12, decision_seconds: 10, state_until: null,
    grace_until: null, you: "COR", your_turn: true, controller: "HUMAN", ai_control: [], humans: ["COR"],
    connected: { COR: true }, opportunity: null, ruleset: "ARCADE",
    pitch: { length: 105, width: 68, goal: 7.32, box: 16.5 }, physics: { pass: [7, 26], loft_range: [12, 58], shot: [16, 34], carry: [4, 11], decel: 5 },
    events: [], stats: {}, ...partial,
  };
}

const goal = (event_id: string, name: string, minute: number, team = "COR"): InteractiveView["events"][number] => ({
  event_id, match_id: "m1", kind: "GOAL", team, minute, x: 1, y: 0.5, outcome: "GOAL",
  player_id: null, player_name: name, xg: 0.3, animation_ms: 0, participant_ids: [],
});

describe("end of the match", () => {
  it("is in play while the match runs", () => {
    expect(endPhase(view({ state: "EXECUTING" }), null)).toBe("inplay");
  });

  it("is finished at the final whistle, before the round is recorded", () => {
    const finished = view({ state: "FINISHED", score: { home: 2, away: 1 } });
    expect(endPhase(finished, finished)).toBe("finished");
    expect(endScore(finished, finished)).toEqual({ home: 2, away: 1 });
  });

  it("is settled when the round was recorded and the session left the round", () => {
    const finished = view({ state: "FINISHED", score: { home: 2, away: 1 } });
    const settled = view({ state: "NONE", match_id: null });
    expect(endPhase(settled, finished)).toBe("settled");
    // The settled answer has no score: the last official one is the result shown.
    expect(endScore(settled, finished)).toEqual({ home: 2, away: 1 });
    expect(lastMatchOf(settled, finished)?.match_id).toBe("m1");
  });

  it("never reports a match when one was never seen", () => {
    const none = view({ state: "NONE", match_id: null });
    expect(endPhase(none, null)).toBe("inplay");
    expect(endScore(none, null)).toEqual({ home: 0, away: 0 });
  });

  it("lists the official goals in order for the result screen", () => {
    const finished = view({ state: "FINISHED", events: [goal("e1", "Yuri Alberto", 12), goal("e2", "Calleri", 55, "SAO")] });
    expect(endScorers(finished, null)).toEqual([
      { id: "e1", name: "Yuri Alberto", minute: 12, team: "COR" },
      { id: "e2", name: "Calleri", minute: 55, team: "SAO" },
    ]);
  });

  it("reads the verdict from the official score, for both sides", () => {
    expect(endVerdict({ home: 2, away: 1 }, "COR", "COR")).toBe("win");
    expect(endVerdict({ home: 2, away: 1 }, "SAO", "COR")).toBe("loss");
    expect(endVerdict({ home: 2, away: 2 }, "COR", "COR")).toBe("draw");
  });
});
