import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "../../lib/api";
import { InteractiveMatch } from "../career/interactive/InteractiveMatch";
import type { MatchSource } from "../career/interactive/source";
import { ExperiencePicker } from "../career/interactive/ExperiencePicker";

/**
 * Gameplay Lab (#lab): reproducible scenarios on the real authoritative engine, isolated
 * from every league and career. The same seed gives the same snapshot, so the 2D and 3D
 * renderers can be compared on identical situations (switch with the 2D/3D button).
 */
const SCENARIOS: [string, string][] = [
  ["BUILDUP", "Construção pelo meio"], ["COUNTER", "Contra-ataque / condução longa"], ["WING", "Ataque pela ponta"], ["THROUGH", "Passe em profundidade"],
  ["CROSS", "Cruzamento"], ["REBOUND", "Chute de fora / rebote"], ["ONE_ON_ONE", "Cara a cara / defesa do goleiro"], ["FREE_KICK", "Falta"], ["PENALTY", "Pênalti"],
];

export function GameplayLab() {
  const clubs = useQuery({ queryKey: ["clubs"], queryFn: () => api.clubs().then((r) => r.data) });
  const [kind, setKind] = useState("BUILDUP");
  const [mode, setMode] = useState<"ELEVEN_A_SIDE" | "FIVE_A_SIDE">("ELEVEN_A_SIDE");
  const [seed, setSeed] = useState(7);
  const [home, setHome] = useState("");
  const [away, setAway] = useState("");
  const [secondHalf, setSecondHalf] = useState(false);
  const [session, setSession] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const source = useMemo<MatchSource | undefined>(() => session ? {
    key: session,
    fetch: (revision) => api.labState(session, revision).then((r) => r.data),
    act: (payload) => api.labAction(session, payload).then((r) => r.data),
  } : undefined, [session]);
  const start = async () => {
    setError(null);
    try { setSession((await api.labCreate({ kind, mode, seed, home, away, second_half: secondHalf })).data.id); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível criar o cenário."); }
  };
  if (session && source) return <InteractiveMatch roomId={`lab-${session}`} clubCode="" clubs={clubs.data ?? []} source={source} onExit={() => setSession(null)} />;
  return <main className="app-shell" style={{ maxWidth: 860, margin: "0 auto", padding: "1.5rem 1rem", display: "grid", gap: "1rem" }}>
    <header><p className="section-kicker">LABORATÓRIO DE JOGABILIDADE</p><h1>Cenários do Modo Jogável</h1><p>Mesmo motor oficial das partidas, isolado de qualquer liga ou carreira. Mesma semente, mesmo lance — compare 2D e 3D.</p></header>
    <ExperiencePicker compact />
    <section className="card" style={{ display: "grid", gap: ".8rem" }}>
      <div role="radiogroup" aria-label="Cenário" style={{ display: "flex", flexWrap: "wrap", gap: ".4rem" }}>
        {SCENARIOS.map(([key, label]) => <button key={key} type="button" role="radio" aria-checked={kind === key} className={kind === key ? "button-primary" : "button-secondary"} onClick={() => setKind(key)}>{label}</button>)}
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "1rem", alignItems: "center" }}>
        <label>Formato <select value={mode} onChange={(e) => setMode(e.target.value as typeof mode)}><option value="ELEVEN_A_SIDE">11 × 11</option><option value="FIVE_A_SIDE">5 × 5</option></select></label>
        <label>Mandante <select value={home} onChange={(e) => setHome(e.target.value)}><option value="">Automático</option>{(clubs.data ?? []).map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}</select></label>
        <label>Visitante <select value={away} onChange={(e) => setAway(e.target.value)}><option value="">Automático</option>{(clubs.data ?? []).map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}</select></label>
        <label><input type="checkbox" checked={secondHalf} onChange={(e) => setSecondHalf(e.target.checked)} /> 2º tempo (mandante ataca para a esquerda)</label>
        <label>Semente <input type="number" min={0} max={999999} value={seed} onChange={(e) => setSeed(Number(e.target.value) || 0)} style={{ width: "7rem" }} /></label>
        <button type="button" className="button-primary" onClick={() => void start()}>Jogar cenário →</button>
        <a href="#" onClick={() => { window.location.hash = ""; }}>Voltar ao jogo</a>
      </div>
      {error && <p className="feedback feedback--error" role="alert">{error}</p>}
    </section>
  </main>;
}
