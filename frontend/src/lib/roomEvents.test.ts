import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ALL_ROOM_QUERIES, InvalidationBatcher, queriesForEvent } from "./roomEvents";

describe("room events", () => {
  it("refreshes only what each event can change", () => {
    expect(queriesForEvent("season.ready_changed")).toEqual(["season", "preview"]);
    expect(queriesForEvent("season.tick")).toEqual(["live"]);
    expect(queriesForEvent("live.frames")).toEqual([]);
    expect(queriesForEvent("squad.lineup_changed")).toEqual(["preview", "season"]);
    expect(queriesForEvent("room.match_settings")).toEqual(["room-state"]);
  });

  it("falls back to the whole room for unknown events", () => {
    expect(queriesForEvent("something.new")).toEqual([ALL_ROOM_QUERIES]);
    expect(queriesForEvent(undefined)).toEqual([]);
  });
});

describe("invalidation batcher", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("coalesces a burst of events into one refresh with the union of keys", () => {
    const flushes: string[][] = [];
    const batcher = new InvalidationBatcher((keys) => flushes.push([...keys].sort()), 250);
    batcher.add(["season", "preview"]);
    batcher.add(["season"]);
    batcher.add(["live"]);
    expect(flushes).toEqual([]);
    vi.advanceTimersByTime(260);
    expect(flushes).toEqual([["live", "preview", "season"]]);
    batcher.add(["live"]);
    vi.advanceTimersByTime(260);
    expect(flushes).toHaveLength(2);
  });

  it("can be cancelled when the room is left", () => {
    const flushes: string[][] = [];
    const batcher = new InvalidationBatcher((keys) => flushes.push([...keys]), 250);
    batcher.add(["season"]);
    batcher.cancel();
    vi.advanceTimersByTime(500);
    expect(flushes).toEqual([]);
  });
});
