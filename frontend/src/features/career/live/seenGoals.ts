/** Goals already celebrated in this browser tab; prevents replays after reconnects. */
const STORE = "bm_seen_goals";

export function seenGoals(): Set<string> {
  try { return new Set(JSON.parse(sessionStorage.getItem(STORE) ?? "[]") as string[]); } catch { return new Set(); }
}

export function markGoalsSeen(ids: string[]): void {
  try {
    const seen = seenGoals();
    ids.forEach((id) => seen.add(id));
    sessionStorage.setItem(STORE, JSON.stringify([...seen].slice(-300)));
  } catch { /* storage may be unavailable; duplicates are still filtered in memory */ }
}
