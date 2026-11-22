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
  ["MATCH", "Partida completa contra o bot"],
  ["BUILDUP", "Construção pelo meio"], ["COUNTER", "Contra-ataque / condução longa"], ["WING", "Ataque pela ponta"], ["THROUGH", "Passe em profundidade"],
  ["CROSS", "Cruzamento"], ["REBOUND", "Chute de fora / rebote"], ["ONE_ON_ONE", "Cara a cara / defesa do goleiro"], ["OVERLOAD", "Superioridade 3 × 2"],
  ["FREE_KICK", "Falta"], ["PENALTY", "Pênalti"],
];
/** Isolated training drills (V7 only): the same real athletes, fewer of them. */
const DRILLS: [string, string][] = [
  ["DRILL_1V_GK", "Atacante × goleiro"], ["DRILL_2V1", "2 × 1"], ["DRILL_3V2", "3 × 2"], ["DRILL_COUNTER", "Contra-ataque 3 × 3"], ["DRILL_CROSS", "Cruzamento e área"],
];
type Engine = "v6" | "v7" | "v8";
type Difficulty = "EASY" | "NORMAL" | "HARD";
function readEngine(): Engine { try { const v = localStorage.getItem("bm_lab_engine"); return v === "v6" || v === "v7" ? v : "v8"; } catch { return "v8"; } }

export function GameplayLab() {
  const clubs = useQuery({ queryKey: ["clubs"], queryFn: () => api.clubs().then((r) => r.data) });
  const [kind, setKind] = useState("BUILDUP");
  const [mode, setMode] = useState<"ELEVEN_A_SIDE" | "FIVE_A_SIDE">("ELEVEN_A_SIDE");
  const [seed, setSeed] = useState(7);
  const [home, setHome] = useState("");
  const [away, setAway] = useState("");
  const [secondHalf, setSecondHalf] = useState(false);
  const [engine, setEngineState] = useState<Engine>(readEngine);
  const [difficulty, setDifficulty] = useState<Difficulty>("NORMAL");
  const setEngine = (value: Engine) => { setEngineState(value); try { localStorage.setItem("bm_lab_engine", value); } catch { /* optional */ } };
  const [session, setSession] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const source = useMemo<MatchSource | undefined>(() => session ? {
    key: session,
    fetch: (revision) => api.labState(session, revision).then((r) => r.data),
    act: (payload) => api.labAction(session, payload).then((r) => r.data),
  } : undefined, [session]);
  const start = async () => {
    setError(null);
    try { setSession((await api.labCreate({ kind, mode, seed, home, away, second_half: secondHalf, engine, difficulty })).data.id); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível criar o cenário."); }
  };
  // "Repetir" replays the SAME seed (identical situation) — the fastest way to compare a change.
  const again = () => { setSession(null); window.setTimeout(() => void start(), 0); };
  if (session && source) return <>
    <InteractiveMatch roomId={`lab-${session}`} clubCode="" clubs={clubs.data ?? []} source={source} onExit={() => setSession(null)} />
    <button type="button" className="lab-again" onClick={again} title="Mesmo cenário, mesma semente">↺ Repetir</button>
  </>;
  return <main className="app-shell" style={{ maxWidth: 860, margin: "0 auto", padding: "1.5rem 1rem", display: "grid", gap: "1rem" }}>
    <header><p className="section-kicker">LABORATÓRIO DE JOGABILIDADE</p><h1>Cenários do Modo Jogável</h1><p>Mesmo motor oficial das partidas, isolado de qualquer liga ou carreira. Mesma semente, mesmo lance — compare 2D e 3D.</p></header>
    <ExperiencePicker compact />
    <section className="card" style={{ display: "grid", gap: ".8rem" }}>
      <div role="radiogroup" aria-label="Cenário" style={{ display: "flex", flexWrap: "wrap", gap: ".4rem" }}>
        {SCENARIOS.map(([key, label]) => <button key={key} type="button" role="radio" aria-checked={kind === key} className={kind === key ? "button-primary" : "button-secondary"} onClick={() => setKind(key)}>{label}</button>)}
      </div>
      <div role="radiogroup" aria-label="Treinos isolados" style={{ display: "flex", flexWrap: "wrap", gap: ".4rem", alignItems: "center" }}>
        <b style={{ fontSize: ".8rem", opacity: 0.8 }}>Treinos:</b>
        {DRILLS.map(([key, label]) => <button key={key} type="button" role="radio" aria-checked={kind === key} disabled={engine === "v6"} className={kind === key ? "button-primary" : "button-secondary"} onClick={() => setKind(key)}>{label}</button>)}
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "1rem", alignItems: "center" }}>
        <label>Formato <select value={mode} onChange={(e) => setMode(e.target.value as typeof mode)}><option value="ELEVEN_A_SIDE">11 × 11</option><option value="FIVE_A_SIDE">5 × 5</option></select></label>
        <label>Mandante <select value={home} onChange={(e) => setHome(e.target.value)}><option value="">Automático</option>{(clubs.data ?? []).map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}</select></label>
        <label>Visitante <select value={away} onChange={(e) => setAway(e.target.value)}><option value="">Automático</option>{(clubs.data ?? []).map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}</select></label>
        <label><input type="checkbox" checked={secondHalf} onChange={(e) => setSecondHalf(e.target.checked)} /> 2º tempo (mandante ataca para a esquerda)</label>
        <label>Dificuldade <select value={difficulty} onChange={(e) => setDifficulty(e.target.value as Difficulty)}><option value="EASY">Fácil</option><option value="NORMAL">Normal</option><option value="HARD">Difícil</option></select></label>
        <label title="Comparação de desenvolvimento: V8 é o motor integrado experimental; V7 é a reconstrução anterior; V6 é o que está nas partidas competitivas hoje">Motor <select value={engine} onChange={(e) => setEngine(e.target.value as Engine)}><option value="v8">V8 (integrado, experimental)</option><option value="v7">V7</option><option value="v6">V6 (atual nas competições)</option></select></label>
        <label>Semente <input type="number" min={0} max={999999} value={seed} onChange={(e) => setSeed(Number(e.target.value) || 0)} style={{ width: "7rem" }} /></label>
        <button type="button" className="button-primary" onClick={() => void start()}>Jogar cenário →</button>
        <label title="Só no Lab: FPS, CPU por quadro e deslize dos pés medido"><input type="checkbox" defaultChecked={(() => { try { return localStorage.getItem("bm_lab_diag") === "1"; } catch { return false; } })()} onChange={(e) => { try { localStorage.setItem("bm_lab_diag", e.target.checked ? "1" : "0"); } catch { /* optional */ } }} /> Diagnóstico</label>
        <a href="football-lab.html" target="_blank" rel="noreferrer">Laboratório de animação, goleiro, sprites, física e IA →</a>
        <a href="#" onClick={() => { window.location.hash = ""; }}>Voltar ao jogo</a>
      </div>
      {error && <p className="feedback feedback--error" role="alert">{error}</p>}
    </section>
  </main>;
}
