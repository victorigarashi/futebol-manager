import { useEffect, type CSSProperties } from "react";

import type { Club } from "../../../lib/api";
import { ClubCrest } from "../../../components/ClubCrest";
import { clubColors, inkOn } from "../clubColors";

export type GoalMoment = {
  eventId: string; club: Club; scorer: string; assist?: string | null; minute: number;
  score: { home: number; away: number }; homeCode: string; awayCode: string; header?: boolean; ownTeam: boolean;
};

/** Auto-dismissing goal banner. Sits over the pitch only, so match controls stay usable. */
export function GoalCelebrationOverlay({ goal, onDone }: { goal: GoalMoment; onDone: () => void }) {
  useEffect(() => {
    const timer = window.setTimeout(onDone, 3600);
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onDone(); };
    window.addEventListener("keydown", onKey);
    return () => { window.clearTimeout(timer); window.removeEventListener("keydown", onKey); };
  }, [goal.eventId, onDone]);
  const colors = clubColors(goal.club.code);
  const style = { "--goal-primary": colors.primary, "--goal-secondary": colors.secondary, "--goal-ink": inkOn(colors.primary) } as CSSProperties;
  return <div className={`goal-overlay ${goal.ownTeam ? "goal-overlay--ours" : ""}`} style={style} role="status" aria-live="assertive">
    <div className="goal-overlay__burst" aria-hidden="true" />
    <div className="goal-overlay__card">
      <ClubCrest club={goal.club} size="md" />
      <p className="goal-overlay__word" aria-hidden="true">GOOOOL!</p>
      <span className="sr-only">Gol do {goal.club.name}.</span>
      <strong className="goal-overlay__scorer">{goal.scorer}{goal.header ? " · de cabeça" : ""}</strong>
      <span className="goal-overlay__meta">{goal.minute}′{goal.assist ? ` · assistência de ${goal.assist}` : ""}</span>
      <span className="goal-overlay__score">{goal.homeCode} <b>{goal.score.home}</b> <i>×</i> <b>{goal.score.away}</b> {goal.awayCode}</span>
    </div>
    <button type="button" className="goal-overlay__close" onClick={onDone} aria-label="Fechar celebração">×</button>
  </div>;
}
