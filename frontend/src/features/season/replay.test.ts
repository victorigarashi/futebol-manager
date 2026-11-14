import { describe, expect, it } from "vitest";
import type { MatchEvent } from "../../lib/api";
import { ballAt, playerPositionsAt, pressureBuckets, serverReplayTime } from "./replay";

const event = (at: number, x: number, team = "FLA", kind = "PASS"): MatchEvent => ({
  event_id: `id-${at}`, match_id: "r1-1", kind, team, minute: Math.ceil(at / 1000),
  animation_ms: at, x, y: .5, outcome: "", player_id: null, participant_ids: [], xg: 0,
});

describe("server clock presentation", () => {
  it("maps sixty real seconds to ninety minutes and reconnects without restarting", () => {
    expect(serverReplayTime(1000, 1000, 0)).toBe(0);
    expect(serverReplayTime(1000, 1020, 0)).toBe(30_000);
    expect(serverReplayTime(1000, 1030, 1000)).toBe(46_500);
    expect(serverReplayTime(1000, 1060, 0)).toBe(90_000);
    expect(serverReplayTime(1000, 1065, 500)).toBe(90_000);
  });
});

describe("event driven field", () => {
  it("holds the last released position instead of jumping to kickoff", () => {
    expect(ballAt([event(0, .5), event(100, .9)], 500).x).toBe(.9);
  });
  it("interpolates released events and handles an empty stream", () => {
    expect(ballAt([event(0, .2), event(1000, .8)], 500).x).toBeCloseTo(.5);
    expect(ballAt([], 0).x).toBe(.5);
  });
  it("places pressure at the event minute instead of an unrelated event index", () => {
    const buckets = pressureBuckets([event(30_000, .9, "FLA", "SHOT"), event(90_000, .1, "PAL", "GOAL")], "FLA");
    expect(buckets[10].home).toBe(3);
    expect(buckets[29].away).toBe(3);
    expect(buckets[0].home).toBe(0);
  });
  it("keeps tactical players inside the field and limits the lineup to the supplied mode", () => {
    const players = playerPositionsAt(
      [event(0, .5, "FLA", "MATCH_START"), { ...event(1000, .8, "FLA", "PASS"), player_id: "p1", participant_ids: ["p1", "p2"] }],
      1500,
      "FLA",
      ["p1", "p2", "p3", "p4", "p5"],
      undefined,
      "home",
    );
    expect(players).toHaveLength(5);
    expect(players.every((player) => player.x >= .04 && player.x <= .96 && player.y >= .08 && player.y <= .92)).toBe(true);
    expect(players.filter((player) => player.involved).length).toBeGreaterThan(0);
  });
});
