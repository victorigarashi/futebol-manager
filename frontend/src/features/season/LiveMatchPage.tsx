import { useState } from "react";
import type { LiveView } from "../../lib/api";
import { MatchReplayView } from "./MatchReplay";
import { StandingsTable } from "./StandingsTable";

type LiveTab = "flow" | "stats" | "table";
const TABS: { id: LiveTab; label: string }[] = [{ id: "flow", label: "Fluxo" }, { id: "stats", label: "Estatísticas" }, { id: "table", label: "Classificação" }];

export function LiveMatchPage({ data, clubCode }: { data: LiveView; clubCode: string }) {
  const [tab, setTab] = useState<LiveTab>("flow");
  if (!data.match) return <p role="status">Preparando a transmissão da sua partida…</p>;
  const navigation = <nav className="live-mobile-tabs" aria-label="Detalhes da transmissão">{TABS.map((item) => <button key={item.id} type="button" aria-pressed={tab === item.id} aria-controls={item.id === "table" ? "live-table" : item.id === "stats" ? "live-statistics" : "live-timeline"} onClick={() => setTab(item.id)}>{item.label}</button>)}</nav>;
  return <section className={`live-match-page live-match-page--${tab}`}>
    <nav className="live-match-nav" aria-label="Acompanhamento"><span>SEU CLUBE EM CAMPO</span><a href="#live-table" onClick={() => setTab("table")}>Classificação ao vivo ↓</a></nav>
    <MatchReplayView key={data.match.id} match={data.match} serverNow={data.server_now} roundNumber={data.live_round?.round_number} detailsNavigation={navigation} />
    <div className="live-round-bottom"><section id="live-table" className="live-table"><header><h2>Classificação ao vivo</h2><span>PROVISÓRIA</span></header><p>Os dez placares parciais atualizam a tabela. A rodada será oficializada por inteiro ao fim dos 60 segundos.</p><StandingsTable rows={data.table} baseline={data.official_table} ownClub={clubCode} live /></section><section className="live-other-scores"><h2>Placar da rodada</h2><p>Dez confrontos. A mesma rodada.</p>{data.scores.map((match) => <article key={match.id} className={match.id === data.match?.id ? "is-own-match" : ""}><strong>{match.home}</strong><b>{match.home_goals} <i>×</i> {match.away_goals}</b><strong>{match.away}</strong></article>)}<small>Você acompanha o campo 2D exclusivamente do seu clube.</small></section></div>
  </section>;
}
