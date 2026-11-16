import type { EngineEvent, LiveMatch, LiveView, SeasonTableRow } from "./api";

/** Reliable incremental state pushed over the socket (`live.state`). */
export type LiveStateMessage = {
  type: "live.state"; match_id: string; seq_from: number; seq: number; tick: number; server_now: number; ends_at: number;
  score: { home: number; away: number }; events: EngineEvent[]; scores: LiveView["scores"]; table?: SeasonTableRow[];
};
/** Compact side-panel detail (`live.stats`): the match without events and attributes. */
export type LiveStatsMessage = { type: "live.stats"; match_id: string; match: Partial<LiveMatch> };

export type ApplyResult = { view: LiveView; gap: boolean };

/**
 * Merges a `live.state` into the cached live view.
 *
 * `seq` counts the match events already on screen, so a message must start where the
 * cache ends. If it does not (a lost message, a reconnection), the cache cannot be
 * trusted: `gap` asks the caller to reconcile over HTTP instead of guessing.
 */
export function applyLiveState(view: LiveView | undefined, message: LiveStateMessage): ApplyResult | null {
  if (!view?.match || view.match.id !== message.match_id) return null;
  const known = view.match.events.length;
  if (message.seq_from > known) return { view, gap: true };
  // Older than what the cache already holds (an HTTP refresh overtook it): keep the newer state.
  if (message.seq < known) return { view, gap: false };
  const fresh = message.events.slice(Math.max(0, known - message.seq_from));
  const events = fresh.length ? [...view.match.events, ...fresh] : view.match.events;
  if (events.length !== message.seq && message.seq > known) return { view, gap: true };
  const match: LiveMatch = { ...view.match, events, home_goals: message.score.home, away_goals: message.score.away, tick: Math.max(view.match.tick, message.tick) };
  return {
    gap: false,
    view: { ...view, server_now: message.server_now, match, scores: message.scores ?? view.scores, table: message.table ?? view.table },
  };
}

/** Merges `live.stats` (statistics, line-ups, orders) keeping the events the cache has. */
export function applyLiveStats(view: LiveView | undefined, message: LiveStatsMessage): LiveView | null {
  if (!view?.match || view.match.id !== message.match_id) return null;
  const incoming = message.match;
  const lineups = incoming.lineups
    ? {
        home: incoming.lineups.home.map((player) => ({ ...view.match!.lineups.home.find((p) => p.id === player.id), ...player })),
        away: incoming.lineups.away.map((player) => ({ ...view.match!.lineups.away.find((p) => p.id === player.id), ...player })),
      } as LiveMatch["lineups"]
    : view.match.lineups;
  return { ...view, match: { ...view.match, ...incoming, events: view.match.events, lineups } };
}

/** Number of events with tick <= `tick` (events are in tick order): binary search. */
export function visibleCount(events: { tick: number }[], tick: number): number {
  let low = 0;
  let high = events.length;
  while (low < high) {
    const middle = (low + high) >> 1;
    if (events[middle].tick <= tick) low = middle + 1; else high = middle;
  }
  return low;
}
