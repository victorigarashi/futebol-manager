import type { MatchEvent } from "../../lib/api";

export type ReplayPlayer = { id: string; x: number; y: number; number: number; involved: boolean; hasBall: boolean };

export const REPLAY_DURATION = 90_000;
export const REAL_DURATION = 60_000;

// Presentation only. Events and outcomes always come from the server.
export function serverReplayTime(startedAt: number, serverNow: number, sinceReceiptMs: number): number {
  return Math.max(0, Math.min(REPLAY_DURATION, ((serverNow - startedAt) * 1000 + sinceReceiptMs) * 1.5));
}

export function ballAt(events: MatchEvent[], elapsed: number) {
  if (!events.length) return { x: .5, y: .5, event: undefined };
  const index = events.findIndex((event) => event.animation_ms > elapsed);
  const previous = events[index < 0 ? events.length - 1 : Math.max(0, index - 1)];
  const next = index < 0 ? previous : events[index];
  const mix = next.animation_ms > previous.animation_ms
    ? Math.max(0, Math.min(1, (elapsed - previous.animation_ms) / (next.animation_ms - previous.animation_ms))) : 1;
  return { x: previous.x + (next.x - previous.x) * mix, y: previous.y + (next.y - previous.y) * mix, event: previous };
}

function clamp(value: number, min = 0.04, max = 0.96) {
  return Math.max(min, Math.min(max, value));
}

function formationSlot(players: { id: string; x: number; y: number; number: number }[] | undefined, id: string, index: number, total: number, side: "home" | "away") {
  const slot = players?.find((player) => player.id === id);
  const x = slot?.x ?? (total <= 1 ? 0.5 : 0.14 + (index / (total - 1)) * 0.72);
  const y = slot?.y ?? 0.18 + ((index * 0.618) % 0.64);
  return { x: side === "home" ? 0.04 + x * 0.48 : 0.96 - x * 0.48, y, number: slot?.number ?? index + 1 };
}

/** Derives deterministic tactical movement from released server events. */
export function playerPositionsAt(
  events: MatchEvent[], elapsed: number,
  team: string, playerIds: string[], formation: { id: string; x: number; y: number; number: number }[] | undefined,
  side: "home" | "away",
): ReplayPlayer[] {
  const ball = ballAt(events, elapsed);
  const previous = events.filter((event) => event.animation_ms <= elapsed);
  const active = previous.at(-1);
  const attacking = active?.team === team;
  return playerIds.map((id, index) => {
    const base = formationSlot(formation, id, index, playerIds.length, side);
    const involvedEvents = previous.filter((event) => event.player_id === id || event.participant_ids.includes(id)).slice(-3);
    const involved = involvedEvents.length > 0;
    const latest = involvedEvents.at(-1);
    const roleShift = attacking ? (side === "home" ? 0.025 : -0.025) : (side === "home" ? -0.018 : 0.018);
    const chase = latest?.player_id === id ? 0.48 : involved ? 0.20 : playerIds.length <= 5 ? 0.05 : 0.025;
    const x = clamp(base.x + roleShift + (ball.x - base.x) * chase);
    const y = clamp(base.y + (ball.y - base.y) * chase, 0.08, 0.92);
    return { id, x, y, number: base.number, involved, hasBall: latest?.player_id === id && active?.animation_ms === latest.animation_ms };
  });
}

export function pressureBuckets(events: MatchEvent[], home: string) {
  const buckets = Array.from({ length: 30 }, () => ({ home: 0, away: 0 }));
  for (const event of events) {
    if (!["SHOT", "GOAL", "CORNER", "CARRY"].includes(event.kind)) continue;
    const side = event.team === home ? "home" : "away";
    buckets[Math.min(29, Math.floor(event.minute / 3))][side] += event.kind === "SHOT" || event.kind === "GOAL" ? 3 : 1;
  }
  return buckets;
}
