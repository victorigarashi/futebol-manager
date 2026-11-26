import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { api, ApiError, type CustomPlayerRules } from "../../lib/api";
import { previewOverall } from "./customPlayer";
import { POSITION_LABEL } from "./labels";
import "./custom-player.css";

const LABEL: Record<string, string> = {
  pace: "Ritmo", shooting: "Finalização", passing: "Passe", dribbling: "Drible", defending: "Defesa", physical: "Físico",
  gk_diving: "Elasticidade", gk_handling: "Manejo", gk_reflexes: "Reflexos", gk_positioning: "Posicionamento",
};
const POSITIONS = ["GK", "DF", "MF", "ST"] as const;

function defaults(rules: CustomPlayerRules, position: string): Record<string, number> {
  const keys = [...rules.outfield_keys, ...(position === "GK" ? rules.keeper_keys : [])];
  return Object.fromEntries(keys.map((k) => [k, 60]));
}

/**
 * Elenco · criar jogador: a coach creates an athlete for his club. The overall is never typed:
 * it follows the attributes (same formula as the server). The new player takes the place of an
 * athlete of the same position, so the squad keeps its size and balance.
 */
export function CustomPlayerForm({ roomId }: { roomId: string }) {
  const client = useQueryClient();
  const rules = useQuery({ queryKey: ["custom-player-rules"], queryFn: () => api.customPlayerRules().then((r) => r.data), staleTime: Infinity });
  const squad = useQuery({ queryKey: ["squad", roomId], queryFn: () => api.squad(roomId).then((r) => r.data) });
  const [name, setName] = useState("");
  const [position, setPosition] = useState<string>("ST");
  const [attributes, setAttributes] = useState<Record<string, number> | null>(null);
  const [replace, setReplace] = useState("");
  const [operation, setOperation] = useState(() => crypto.randomUUID());

  const attrs = useMemo(() => attributes ?? (rules.data ? defaults(rules.data, position) : {}), [attributes, rules.data, position]);
  const overall = rules.data ? previewOverall(rules.data, position, attrs) : 0;
  const candidates = (squad.data?.players ?? []).filter((p) => p.position === position).sort((a, b) => a.overall - b.overall);
  const customCount = (squad.data?.players ?? []).filter((p) => p.id.startsWith("CUS-")).length;

  const create = useMutation({
    mutationFn: () => api.createCustomPlayer(roomId, { name, position, attributes: attrs, replace_player_id: replace, operation_id: operation }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["squad", roomId] });
      setName(""); setReplace(""); setAttributes(null); setOperation(crypto.randomUUID());
    },
  });

  if (!rules.data || !squad.data) return <section className="rt-panel cpf" aria-busy="true"><p>Carregando…</p></section>;
  const r = rules.data;
  const tooStrong = overall > r.max_overall;
  const limitReached = customCount >= r.max_per_club;
  const canSubmit = name.trim().length >= 2 && !!replace && !tooStrong && !limitReached && !create.isPending;
  const changePosition = (next: string) => { setPosition(next); setAttributes(defaults(r, next)); setReplace(""); };

  return <section className="rt-panel cpf" aria-labelledby="cpf-title">
    <header className="cpf__head">
      <h2 id="cpf-title">Criar jogador</h2>
      <p>Crie um atleta para o seu clube. O overall segue os atributos (a mesma conta do servidor) e o jogador entra no lugar de um atleta da mesma posição. Disponível na pré-temporada e com a janela de transferências aberta. Máximo de {r.max_per_club} por clube ({customCount} criados).</p>
    </header>
    <div className="cpf__body">
    <form className="cpf__form" onSubmit={(e) => { e.preventDefault(); if (canSubmit) create.mutate(); }}>
      <label className="cpf__field">Nome <input value={name} maxLength={40} onChange={(e) => setName(e.target.value)} placeholder="Ex.: Zé da Resenha" required /></label>
      <fieldset className="cpf__positions"><legend>Posição</legend>
        {POSITIONS.map((p) => <label key={p} className={position === p ? "is-on" : ""}><input type="radio" name="cpf-pos" value={p} checked={position === p} onChange={() => changePosition(p)} />{POSITION_LABEL[p] ?? p}</label>)}
      </fieldset>
      <div className="cpf__attrs">
        {Object.keys(attrs).map((key) => <label key={key} className="cpf__attr">
          <span>{LABEL[key] ?? key}</span>
          <input type="range" min={r.attribute_min} max={r.attribute_max} value={attrs[key]} onChange={(e) => setAttributes({ ...attrs, [key]: Number(e.target.value) })} aria-valuetext={String(attrs[key])} />
          <b>{attrs[key]}</b>
        </label>)}
      </div>
      <p className={`cpf__overall ${tooStrong ? "is-bad" : ""}`} aria-live="polite">Overall calculado: <b>{overall}</b>{tooStrong && ` — acima do limite de ${r.max_overall}: reduza os atributos principais da posição.`}</p>
      <label className="cpf__field">Sai do elenco (mesma posição)
        <select value={replace} onChange={(e) => setReplace(e.target.value)} required>
          <option value="">Escolha o atleta</option>
          {candidates.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.overall}</option>)}
        </select>
      </label>
      {create.isError && <p className="cpf__error" role="alert">{create.error instanceof ApiError ? create.error.message : "Não foi possível criar o jogador."}</p>}
      {create.isSuccess && <p className="cpf__ok" role="status">Jogador criado e incluído no elenco.</p>}
      <button type="submit" className="rt-btn rt-btn--lime" disabled={!canSubmit}>{create.isPending ? "Criando…" : "Criar jogador"}</button>
    </form>
    <aside className="cpf__preview" aria-label="Prévia do jogador">
      <div className="cpf__preview-head"><span>Overall</span><b className={tooStrong ? "is-bad" : ""}>{overall}</b></div>
      <div className="cpf__preview-name"><strong>{name.trim() || "Novo atleta"}</strong><span>{POSITION_LABEL[position] ?? position}</span></div>
      <ul>{Object.keys(attrs).map((key) => <li key={key}><span>{LABEL[key] ?? key}</span><i aria-hidden="true"><em style={{ width: `${attrs[key]}%` }} /></i><b>{attrs[key]}</b></li>)}</ul>
    </aside>
    </div>
  </section>;
}
