/**
 * Which cached queries a room event makes stale.
 *
 * Previously every socket event invalidated every query of the room, so one coach
 * pressing READY made every connected browser refetch state, season, live, squad,
 * preview, career… at once - on a 0.1 CPU server, during the busiest moment.
 * Each event now refreshes only what it can change; unknown events fall back to
 * the whole room (safe default), and bursts are coalesced by the caller.
 */
export const ALL_ROOM_QUERIES = "*";

const BY_PREFIX: [string, string[]][] = [
  ["live.", []],                                       // 2D frames: handled by the canvas buffer, never React Query
  ["season.tick", ["live"]],
  ["season.sync", ["live"]],
  ["season.live_command", ["live"]],
  ["season.ready_changed", ["season", "preview"]],
  ["season.round_started", ["season", "live", "preview", "room-state"]],
  ["season.round_completed", ["season", "live", "preview", "squad", "career", "room-state"]],
  ["squad.", ["preview", "season"]],
  ["room.match_settings", ["room-state"]],
  ["room.", ["room-state", "rooms", "my-rooms"]],
  ["market.", ["market", "market-selection", "market-reassignment", "market-review", "market-players", "room-state"]],
  ["draft.", ["draft", "room-state"]],
  ["transfer.", ["squad", "career", "transfer-offers", "transfer-clubs", "transfer-available"]],
];

export function queriesForEvent(type: string | undefined): string[] {
  if (!type) return [];
  for (const [prefix, keys] of BY_PREFIX) if (type.startsWith(prefix)) return keys;
  return [ALL_ROOM_QUERIES];
}

/** Collects stale query names and flushes them once per burst window. */
export class InvalidationBatcher {
  private pending = new Set<string>();
  private timer: ReturnType<typeof setTimeout> | null = null;

  constructor(private readonly flush: (keys: Set<string>) => void, private readonly windowMs = 250) {}

  add(keys: string[]): void {
    if (!keys.length) return;
    for (const key of keys) this.pending.add(key);
    if (this.timer === null) {
      this.timer = setTimeout(() => {
        const keysNow = this.pending;
        this.pending = new Set();
        this.timer = null;
        this.flush(keysNow);
      }, this.windowMs);
    }
  }

  cancel(): void {
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
    this.pending.clear();
  }
}
