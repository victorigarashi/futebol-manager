/**
 * Shared view of "can we reach the game server?", fed by every HTTP answer.
 *
 * One failed request is noise; several in a row with no success in between means the
 * server is restarting (Render answers 502 while it boots) or the network is down.
 * Components subscribe to show one clear banner instead of many scattered errors.
 */
export type ServerHealth = "ok" | "degraded" | "unavailable" | "offline";
type Outcome = "ok" | "network" | "unavailable";

const FAILURES_FOR_OUTAGE = 2;
let failures = 0;
let lastFailure: Outcome = "ok";
let state: ServerHealth = "ok";
const listeners = new Set<(health: ServerHealth) => void>();

function publish(next: ServerHealth): void {
  if (next === state) return;
  state = next;
  for (const listener of listeners) listener(state);
}

export function reportServerHealth(outcome: Outcome): void {
  if (outcome === "ok") {
    failures = 0;
    lastFailure = "ok";
    publish("ok");
    return;
  }
  failures += 1;
  lastFailure = outcome;
  if (failures < FAILURES_FOR_OUTAGE) publish("degraded");
  else publish(lastFailure === "network" ? "offline" : "unavailable");
}

export function serverHealth(): ServerHealth { return state; }

export function subscribeServerHealth(listener: (health: ServerHealth) => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

/** Test helper. */
export function resetServerHealth(): void { failures = 0; lastFailure = "ok"; state = "ok"; listeners.clear(); }

/**
 * Exponential backoff with full jitter: 0.5 s, 1 s, 2 s, 4 s… capped, each randomised so
 * many clients recovering from the same restart do not hit the server in lockstep.
 */
export function backoffDelay(attempt: number, baseMs = 500, capMs = 15_000, random: () => number = Math.random): number {
  const ceiling = Math.min(capMs, baseMs * 2 ** Math.max(0, attempt));
  return Math.round(ceiling / 2 + random() * (ceiling / 2));
}
