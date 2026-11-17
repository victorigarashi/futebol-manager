import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiError, type PlayStyle } from "../../lib/api";
import { slotRole } from "./roles";
import "./tactics.css";

const STYLE_NAMES: Record<PlayStyle, string> = { POSSESSION: "Posse", COUNTER: "Contra-ataque", DIRECT: "Direto", SHORT_BUILDUP: "Construção curta", WIDE: "Pelas laterais" };
function Meter({ label, value, caption }: { label: string; value: number; caption: string }) {
  const tone = value >= 75 ? "high" : value >= 60 ? "good" : value >= 45 ? "mid" : "low";
  return <div className={`cohesion-meter cohesion-meter--${tone}`}>
    <div className="cohesion-meter__top"><span>{label}</span><strong>{Math.round(value)}</strong></div>
    <div className="cohesion-meter__bar" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(value)} aria-label={label}><i style={{ width: `${value}%` }} /></div>
    <small>{caption}</small>
  </div>;
}

/** Entrosamento tático (compatibilidade + familiaridade) and individual instructions. */
export function CohesionPanel({ roomId, locked }: { roomId: string; locked?: string | null }) {
  const client = useQueryClient();
  const squad = useQuery({ queryKey: ["squad", roomId], queryFn: () => api.squad(roomId).then((r) => r.data) });
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  useEffect(() => { setDraft(squad.data?.cohesion?.instructions ?? squad.data?.instructions ?? {}); }, [squad.data]);
  const save = useMutation({
    mutationFn: () => api.saveInstructions(roomId, draft),
    onSuccess: ({ data }) => { setMessage(data.ready_cancelled ? "Instruções salvas. Sua confirmação da rodada foi desfeita." : "Instruções salvas."); void client.invalidateQueries({ queryKey: ["squad", roomId] }); void client.invalidateQueries({ queryKey: ["preview", roomId] }); },
    onError: (error) => setMessage(error instanceof ApiError || error instanceof Error ? error.message : "Não foi possível salvar."),
  });
  const data = squad.data;
  const cohesion = data?.cohesion;
  if (!data || !cohesion) return <section className="cohesion-panel"><h2>Entrosamento tático</h2><p className="muted">O entrosamento aparece quando a temporada começa e a escalação está salva.</p></section>;
  const formation = data.formations.find((f) => f.code === (data.lineup?.formation_code ?? cohesion.formation_code));
  const slots = formation?.slots ?? [];
  const players = new Map(data.players.map((p) => [p.id, p]));
  const fits = new Map(cohesion.players.map((p) => [p.player_id, p]));
  const options = data.instruction_options;
  const factor = cohesion.factor;
  const changed = JSON.stringify(draft) !== JSON.stringify(cohesion.instructions);

  return <section className="cohesion-panel" aria-labelledby="cohesion-title">
    <header>
      <p className="section-kicker">ENTROSAMENTO TÁTICO · {STYLE_NAMES[cohesion.style].toUpperCase()}</p>
      <h2 id="cohesion-title">O elenco combina com o seu jogo?</h2>
      <p className="muted">Não é química de nacionalidade ou clube. É o quanto os atributos e as funções combinam com o estilo, mais o quanto o time já treinou esse estilo em jogos oficiais.</p>
    </header>
    <div className="cohesion-meters">
      <Meter label="Compatibilidade" value={cohesion.compatibility} caption={`${cohesion.compatibility_label} · atributos, posições, formação e instruções`} />
      <Meter label="Familiaridade" value={cohesion.familiarity} caption={`${cohesion.familiarity_label} · cresce a cada jogo com este estilo`} />
      <div className={`cohesion-factor ${factor >= 0 ? "is-up" : "is-down"}`}><span>Efeito em campo</span><strong>{factor >= 0 ? "+" : ""}{factor.toFixed(2)}</strong><small>Passes, leitura de jogo e posicionamento. Não mexe no overall nem garante vitória.</small></div>
    </div>
    {cohesion.estimated_share > 0 && <p className="cohesion-note">{Math.round(cohesion.estimated_share * 100)}% dos titulares não têm atributos detalhados no catálogo; para eles, o encaixe é estimado pelo perfil da posição.</p>}
    {cohesion.notes.map((note) => <p key={note} className="cohesion-note cohesion-note--warn">{note}</p>)}
    <details className="cohesion-styles"><summary>Familiaridade por estilo</summary><ul>{(Object.keys(STYLE_NAMES) as PlayStyle[]).map((style) => <li key={style}><span>{STYLE_NAMES[style]}</span><meter min={0} max={100} value={cohesion.familiarity_by_style[style] ?? 0} /><b>{Math.round(cohesion.familiarity_by_style[style] ?? 0)}</b></li>)}</ul></details>

    <h3>Instruções individuais</h3>
    {locked && <p className="muted">{locked}</p>}
    <div className="instruction-list">{slots.map((slot) => {
      const playerId = data.lineup?.assignments[slot.id];
      const player = playerId ? players.get(playerId) : undefined;
      if (!player || !options) return null;
      const role = slotRole(slot, slots);
      const fit = fits.get(player.id);
      const current = draft[player.id] ?? options[role][0].code;
      const chosen = options[role].find((o) => o.code === current);
      return <div className="instruction-row" key={slot.id}>
        <span className="instruction-row__player"><b>{player.name}</b><small>{role === "FB" ? "Lateral" : role === "CB" ? "Zagueiro" : role === "GK" ? "Goleiro" : role === "MF" ? "Meio" : "Atacante"} · encaixe {fit ? Math.round(fit.fit) : "–"}{fit?.estimated ? " (estimado)" : ""}</small></span>
        <select aria-label={`Instrução para ${player.name}`} disabled={Boolean(locked)} value={current} onChange={(event) => setDraft((d) => ({ ...d, [player.id]: event.target.value }))}>{options[role].map((option) => <option key={option.code} value={option.code}>{option.name}</option>)}</select>
        <small className="instruction-row__effect">{chosen?.effect}</small>
      </div>;
    })}</div>
    <div className="cohesion-actions"><button type="button" className="button-primary" disabled={!changed || save.isPending || Boolean(locked)} onClick={() => save.mutate()}>{save.isPending ? "Salvando…" : "Salvar instruções"}</button>{message && <span role="status">{message}</span>}</div>
  </section>;
}
