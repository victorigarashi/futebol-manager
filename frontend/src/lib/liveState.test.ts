import { describe, expect, it } from "vitest";

import type { EngineEvent, LiveMatch, LiveView } from "./api";
import { applyLiveState, applyLiveStats, visibleCount, type LiveStateMessage } from "./liveState";

const event = (n: number, tick: number, kind = "PASS"): EngineEvent => ({ event_id: `m:${n}`, kind, tick, minute: Math.ceil(tick / 60), team: "FLA" } as unknown as EngineEvent);
const view = (events: EngineEvent[]): LiveView => ({
  server_now: 0, live_round: null, scores: [], table: [], official_table: [], current_round: 1, ready_clubs: [],
  match: { id: "m", events, home_goals: 0, away_goals: 0, tick: 0, lineups: { home: [{ id: "a", name: "A", stamina: 1, attributes: { pace: 80 } }], away: [] } } as unknown as LiveMatch,
});
const message = (seqFrom: number, events: EngineEvent[], extra: Partial<LiveStateMessage> = {}): LiveStateMessage => ({
  type: "live.state", match_id: "m", seq_from: seqFrom, seq: seqFrom + events.length, tick: 100, server_now: 5, ends_at: 90,
  score: { home: 1, away: 0 }, events, scores: [], ...extra,
});

describe("live state merge", () => {
  it("appends exactly the new events and updates the score", () => {
    const result = applyLiveState(view([event(1, 10)]), message(1, [event(2, 20, "GOAL")]))!;
    expect(result.gap).toBe(false);
    expect(result.view.match!.events.map((e) => e.event_id)).toEqual(["m:1", "m:2"]);
    expect(result.view.match!.home_goals).toBe(1);
  });

  it("ignores events it already has (a duplicated message)", () => {
    const result = applyLiveState(view([event(1, 10), event(2, 20)]), message(1, [event(2, 20)]))!;
    expect(result.view.match!.events).toHaveLength(2);
  });

  it("never rolls back to an older message after an HTTP refresh", () => {
    const base = { ...view([event(1, 10), event(2, 20, "GOAL"), event(3, 30)]) };
    base.match!.home_goals = 1;
    const result = applyLiveState(base, { ...message(0, [event(1, 10)]), score: { home: 0, away: 0 } })!;
    expect(result.view.match!.home_goals).toBe(1);
    expect(result.view.match!.events).toHaveLength(3);
  });

  it("reports a gap when messages were lost, so the client reconciles over HTTP", () => {
    expect(applyLiveState(view([event(1, 10)]), message(3, [event(4, 40)]))!.gap).toBe(true);
  });

  it("ignores messages for another match", () => {
    expect(applyLiveState(view([]), { ...message(0, []), match_id: "other" })).toBeNull();
  });

  it("keeps the table unless the message carries a new one", () => {
    const base = { ...view([]), table: [{ club_code: "FLA" }] } as unknown as LiveView;
    expect(applyLiveState(base, message(0, []))!.view.table).toBe(base.table);
  });
});

describe("live stats merge", () => {
  it("updates line-ups without losing the attributes or the events it already has", () => {
    const base = view([event(1, 10)]);
    const merged = applyLiveStats(base, { type: "live.stats", match_id: "m", match: { lineups: { home: [{ id: "a", stamina: 0.7 }], away: [] } as unknown as LiveMatch["lineups"] } })!;
    expect(merged.match!.events).toHaveLength(1);
    expect(merged.match!.lineups.home[0].stamina).toBe(0.7);
    expect(merged.match!.lineups.home[0].attributes).toEqual({ pace: 80 });
  });
});

describe("visible events", () => {
  it("finds how many events are on screen with a binary search", () => {
    const events = [event(1, 10), event(2, 10), event(3, 30), event(4, 50)];
    expect(visibleCount(events, 5)).toBe(0);
    expect(visibleCount(events, 10)).toBe(2);
    expect(visibleCount(events, 49)).toBe(3);
    expect(visibleCount(events, 999)).toBe(4);
  });
});
