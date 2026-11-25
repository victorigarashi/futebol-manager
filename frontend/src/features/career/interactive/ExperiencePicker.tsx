import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "../../../lib/api";

import { readExperience, readQuality, writeExperience, writeQuality, type Experience, type QualityChoice } from "./render/preference";
import "./experience.css";

/**
 * "Experiência de partida": each participant picks how HIS matches are drawn — 2D Arcade
 * or 3D Imersivo. A personal presentation choice (this browser), never imposed by the host
 * and never able to change a result: both renderers draw the same official match.
 */
export function ExperiencePicker({ compact = false }: { compact?: boolean }) {
  const [value, setValue] = useState<Experience>(readExperience);
  const [quality, setQuality] = useState<QualityChoice>(readQuality);
  useEffect(() => {
    const sync = (event: Event) => setValue((event as CustomEvent<Experience>).detail);
    window.addEventListener("bm-experience", sync);
    return () => window.removeEventListener("bm-experience", sync);
  }, []);
  const choose = (next: Experience) => { setValue(next); writeExperience(next); };
  return <section className={`xp ${compact ? "xp--compact" : ""}`} aria-labelledby="xp-title">
    <header><h2 id="xp-title">Experiência de partida</h2><p>Escolha como você quer ver e jogar os seus lances. Cada técnico escolhe a sua; o resultado é o mesmo para todos.</p></header>
    <div className="xp-cards" role="radiogroup" aria-label="Visualização das partidas">
      <button type="button" role="radio" aria-checked={value === "2D"} className={`xp-card ${value === "2D" ? "is-on" : ""}`} onClick={() => choose("2D")}>
        <img src="/experience-2d.webp" alt="Prévia do modo 2D Arcade: campo visto de cima com jogadores estilizados" loading="lazy" />
        <b>2D Arcade</b><span>Visão de cima, jogadores estilizados, leve e tático.</span>
        {value === "2D" && <i aria-hidden="true">✓</i>}
      </button>
      <button type="button" role="radio" aria-checked={value === "3D"} className={`xp-card ${value === "3D" ? "is-on" : ""}`} onClick={() => choose("3D")}>
        <img src="/experience-3d.webp" alt="Prévia do modo 3D Imersivo: estádio e atletas low poly" loading="lazy" />
        <b>3D Imersivo</b><span>Atletas 3D, estádio, câmera contextual e animações.</span>
        {value === "3D" && <i aria-hidden="true">✓</i>}
      </button>
    </div>
    <ExternalEngines />
    <footer>
      <label>Qualidade gráfica <select value={quality} onChange={(e) => { const q = e.target.value as QualityChoice; setQuality(q); writeQuality(q); }}><option value="auto">Automática</option><option value="low">Baixa</option><option value="medium">Média</option><option value="high">Alta</option></select></label>
      <small>Se o 3D ficar lento ou não for compatível, a partida continua automaticamente em 2D.</small>
    </footer>
  </section>;
}

/** External engines under study (e.g. PES 2013 Web). Listed only when the server enables the
 * experimental flag, and then always as unavailable until their capabilities are validated:
 * matches keep being played with the current engine. Nothing shows in normal operation. */
function ExternalEngines() {
  const engines = useQuery({ queryKey: ["match-engines"], queryFn: () => api.matchEngines().then((r) => r.data.engines), staleTime: 300_000, retry: false });
  const experimental = (engines.data ?? []).filter((e) => e.status === "EXPERIMENTAL_UNAVAILABLE");
  if (!experimental.length) return null;
  return <div className="xp-ext" role="note" aria-label="Engines experimentais">
    {experimental.map((e) => <div key={e.name} className="xp-ext__row">
      <b>{e.name === "PES2013_WEB" ? "PES 2013 Web" : e.name}</b>
      <span className="xp-ext__tag">Experimental · indisponível</span>
      <small>Integração em estudo, ainda não validada. As partidas continuam na engine atual.</small>
    </div>)}
  </div>;
}
