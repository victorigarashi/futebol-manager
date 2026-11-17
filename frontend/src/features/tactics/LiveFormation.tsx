import type { LiveCommandPayload, LiveMatch } from "../../lib/api";

export const LIVE_FORMATIONS = {
  ELEVEN_A_SIDE: ["4-3-3", "4-4-2", "4-2-3-1", "4-1-4-1", "4-2-2-2", "4-3-1-2", "3-5-2", "3-4-3", "5-3-2", "5-4-1"],
  FIVE_A_SIDE: ["2-1-1", "1-2-1", "2-2", "3-1", "1-3"],
} as const;

/** Live change of shape: same command pipeline as tactics (validated and logged by the server). */
export function LiveFormation({ match, disabled, onCommand }: { match: LiveMatch; disabled: boolean; onCommand: (payload: LiveCommandPayload) => void }) {
  if (!match.you) return null;
  const mode = match.pitch.length > 60 ? "ELEVEN_A_SIDE" : "FIVE_A_SIDE";
  const current = match.formations[match.you];
  return <fieldset className="tactic-row"><legend>Formação</legend><div>
    <select aria-label="Mudar formação durante a partida" value={current} disabled={disabled} onChange={(event) => onCommand({ kind: "FORMATION", formation_code: event.target.value })}>
      {LIVE_FORMATIONS[mode].map((code) => <option key={code} value={code}>{code}</option>)}
    </select>
  </div></fieldset>;
}
