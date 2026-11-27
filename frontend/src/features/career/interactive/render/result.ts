import type { InteractiveView, MatchEvent } from "../../../../lib/api";

/**
 * End of the match, independent of the parent screen.
 *
 * The official state of an interactive match ends in two steps: the session reaches
 * FINISHED (final whistle) and, a few seconds later, the round is committed — the session
 * leaves the round and the endpoint answers `state: "NONE"`. A screen that only understood
 * "FINISHED" could sit forever on a dead loading state if the parent did not refresh at the
 * exact moment of the commit, which is what "the match freezes at the end" looked like.
 *
 *   "inplay"   → the match is running
 *   "finished" → final whistle shown, waiting for the official record
 *   "settled"  → the record exists (session gone): show the result and a way out
 */
export type EndPhase = "inplay" | "finished" | "settled";

export function endPhase(view: InteractiveView | null, last: InteractiveView | null): EndPhase {
  if (!view) return "inplay";
  if (view.state === "NONE") return last?.match_id ? "settled" : "inplay";
  return view.state === "FINISHED" ? "finished" : "inplay";
}

/** The last official match state seen (a NONE answer carries no score of its own). */
export function lastMatchOf(view: InteractiveView | null, last: InteractiveView | null): InteractiveView | null {
  if (view && view.state !== "NONE" && view.match_id) return view;
  return last;
}

/** Final score of the match on screen, in every phase (never invents a number). */
export function endScore(view: InteractiveView | null, last: InteractiveView | null): { home: number; away: number } {
  const match = lastMatchOf(view, last);
  return match?.score ?? { home: 0, away: 0 };
}

export type Scorer = { id: string; name: string; minute: number; team: string };

/** Goals in official order (the server's event list), ready for the result screen. */
export function endScorers(view: InteractiveView | null, last: InteractiveView | null, limit = 8): Scorer[] {
  const match = lastMatchOf(view, last);
  if (!match) return [];
  return match.events
    .filter((event: MatchEvent) => event.kind === "GOAL")
    .slice(-limit)
    .map((event) => ({ id: event.event_id, name: event.player_name ?? "", minute: event.minute, team: event.team ?? "" }));
}

/** The coach's own result word, from the official score. */
export function endVerdict(score: { home: number; away: number }, you: string | null, home: string): "win" | "draw" | "loss" {
  if (score.home === score.away) return "draw";
  if (!you) return score.home > score.away ? "win" : "loss";
  const ours = you === home ? score.home : score.away;
  const theirs = you === home ? score.away : score.home;
  return ours > theirs ? "win" : "loss";
}
