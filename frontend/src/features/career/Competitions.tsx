import { useEffect, useState } from "react";

import type { Club, DrawRecord, KnockoutView, TieView } from "../../lib/api";
import { STAGE_LABEL, competitionOf } from "./competition";
import { ClubCrest } from "../../components/ClubCrest";
import { readLocal, writeLocal } from "../../lib/storage";

type ClubOf = (code: string) => Club;
type Kind = "PLAYOFF" | "CUP" | "TOURNAMENT";

/** Pot draw ceremony: the stored server draw revealed one pair at a time (once per
 *  browser). The pairs are fixed by the server and never re-drawn on the client. */
export function DrawCeremony({ roomId, draw, legs, club, ownClub }: { roomId: string; draw: DrawRecord | undefined; legs: number; club: ClubOf; ownClub: string }) {
  const total = draw?.pairs.length ?? 0;
  const key = `bm_draw_${roomId}_${draw?.competition}_${draw?.seed ?? draw?.pairs.flat().join("")}`;
  const [shown, setShown] = useState(() => (readLocal(key) === "1" ? total : 0));
  useEffect(() => {
    if (!draw || !total) return;
    if (shown >= total) { writeLocal(key, "1"); return; }
    const timer = window.setTimeout(() => setShown((value) => value + 1), shown === 0 ? 900 : 1500);
    return () => window.clearTimeout(timer);
  }, [draw, key, shown, total]);
  if (!draw || draw.kind !== "POTS" || !draw.pot1 || !draw.pot2) return null;
  const drawnPot2 = new Set(draw.pairs.slice(0, shown).map((pair) => pair[1]));
  return <section className="draw-ceremony card" aria-label="Sorteio dos playoffs">
    <header className="card__head"><h2>Sorteio dos playoffs</h2>{shown < total ? <button type="button" className="btn btn--ghost" onClick={() => setShown(total)}>Pular</button> : <span className="badge badge--applied">Sorteio concluído</span>}</header>
    <div className="draw-ceremony__pots">
      {[draw.pot1, draw.pot2].map((pot, potIndex) => <div key={potIndex} className="draw-pot"><h3>Pote {potIndex + 1} <small>{potIndex === 0 ? "1º ao 4º" : "5º ao 8º"}</small></h3>
        <ul>{pot.map((code) => <li key={code} className={`${potIndex === 1 && drawnPot2.has(code) ? "is-drawn" : ""} ${code === ownClub ? "is-own" : ""}`}><ClubCrest club={club(code)} size="sm" />{club(code).name}</li>)}</ul></div>)}
    </div>
    <ol className="draw-ceremony__pairs" aria-live="polite">{draw.pairs.map((pair, index) => <li key={index} className={index < shown ? "is-revealed" : ""}>
      <span>QF{index + 1}</span>
      {index < shown ? <><b className={pair[0] === ownClub ? "is-own" : ""}><ClubCrest club={club(pair[0])} size="sm" />{club(pair[0]).name}</b><i>×</i><b className={pair[1] === ownClub ? "is-own" : ""}>{club(pair[1]).name}<ClubCrest club={club(pair[1])} size="sm" /></b></> : <em>{index === shown ? "sorteando…" : "?"}</em>}
    </li>)}</ol>
    <p className="hint">{legs === 2 ? "Ida e volta: o melhor colocado decide em casa. Vale o agregado, sem gol fora; empate leva aos pênaltis." : "Jogo único na casa do melhor colocado; empate leva aos pênaltis."}</p>
  </section>;
}

function TieCard({ tie, club, ownClub }: { tie: TieView; club: ClubOf; ownClub: string }) {
  const sides: [string, number][] = [[tie.high, tie.aggregate[0]], [tie.low, tie.aggregate[1]]];
  const played = tie.leg_scores.length > 0;
  return <article className={`tie ${tie.high === ownClub || tie.low === ownClub ? "is-own" : ""} ${tie.winner ? "is-decided" : ""}`}>
    {sides.map(([code, goals]) => <div key={code} className={`tie__club ${tie.winner === code ? "is-winner" : tie.winner ? "is-out" : ""}`}>
      <ClubCrest club={club(code)} size="sm" /><span>{club(code).name}</span><b>{played ? goals : "–"}</b>
    </div>)}
    {tie.legs > 1 && <small className="tie__legs">{tie.fixtures.map(([home, away], i) => {
      const score = tie.leg_scores[i];
      const [hg, ag] = score ? (home === tie.high ? score : [score[1], score[0]]) : [null, null];
      return <span key={i}>{i === 0 ? "Ida" : "Volta"}: {score ? `${home} ${hg}–${ag} ${away}` : `${home} × ${away}`}</span>;
    })}</small>}
    {tie.penalties && <small className="tie__pens">Pênaltis {tie.high} {tie.penalties[0]}–{tie.penalties[1]} {tie.low}</small>}
  </article>;
}

/** Bracket of a knockout competition: every stage, aggregates, penalties, champion. */
export function Bracket({ knockout, kind, champion, club, ownClub }: { knockout: KnockoutView; kind: Kind; champion: string | null; club: ClubOf; ownClub: string }) {
  const competition = competitionOf(knockout, kind);
  const runnerUp = kind === "CUP" ? knockout.cup_runner_up : knockout.playoff_runner_up;
  return <div className="bracket-view">
    {champion && <p className="champion">🏆 {club(champion).name} é campeão{kind === "CUP" ? " da Copa do Brasil" : ""}! {runnerUp && <small>Vice: {club(runnerUp).name}</small>}</p>}
    <div className="bracket-view__stages">{competition.stages.map((stage) => <div key={stage.stage} className={`bracket-stage ${competition.currentStage === stage.stage ? "is-current" : ""}`}>
      <h3>{stage.name}</h3>
      {stage.ties.length ? stage.ties.map((tie) => <TieCard key={tie.id} tie={tie} club={club} ownClub={ownClub} />) : <p className="hint">A definir</p>}
    </div>)}</div>
  </div>;
}

/** Copa do Brasil page: format, current stage and the full bracket. */
export function CupPage({ knockout, club, ownClub }: { knockout: KnockoutView; club: ClubOf; ownClub: string }) {
  const cup = competitionOf(knockout, "CUP");
  const done = Boolean(knockout.cup_champion);
  const seed = knockout.cup_seeds.indexOf(ownClub);
  const eliminated = cup.ties.some((t) => t.winner && t.winner !== ownClub && (t.high === ownClub || t.low === ownClub));
  const schedule = knockout.rounds.filter((r) => r.competition === "CUP").map((r) => `${r.stage_name} após a rodada ${r.after_round}`);
  return <section className="cup-page">
    <header className="card cup-page__head"><p className="kicker">COPA DO BRASIL</p><h2>{done ? "Copa encerrada" : cup.currentStage ? STAGE_LABEL[cup.currentStage] : "Copa do Brasil"}</h2>
      <p>Mata-mata em jogo único, intercalado com o Brasileirão. Empate vai para os pênaltis. Os 8 últimos cabeças de chave fazem a fase preliminar; os 12 primeiros entram nas oitavas.</p>
      {schedule.length > 0 && <p className="hint">Calendário: {schedule.join(" · ")}.</p>}
      <p className="badge">{done ? (knockout.cup_champion === ownClub ? "Seu clube é campeão!" : "Fim da Copa") : eliminated ? "Seu clube foi eliminado" : seed >= 0 && seed < 12 && !cup.stages[1].ties.length ? "Seu clube entra nas oitavas" : "Seu clube segue vivo"}</p>
    </header>
    <Bracket knockout={knockout} kind="CUP" champion={knockout.cup_champion} club={club} ownClub={ownClub} />
  </section>;
}
