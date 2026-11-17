import { useQuery } from "@tanstack/react-query";

import { api, type Club, type RoomState, type SeasonView } from "../../lib/api";
import { ClubCrest } from "../../components/ClubCrest";
import { formatMoney } from "../../lib/format";
import { POSITION_LABEL } from "./labels";
import { PlayerPhoto } from "../../components/PlayerPhoto";

export type CareerTab = "hub" | "squad" | "tactics" | "market" | "season" | "table" | "stats" | "next" | "cup" | "news" | "trophies";
type Props = { roomId: string; room: RoomState; season: SeasonView; clubCode: string; clubs: Club[]; onGo: (tab: CareerTab) => void; onOpenMatch: (id: string) => void };

/** The career home: everything here comes from the real season state. */
export function ClubHub({ roomId, room, season, clubCode, clubs, onGo, onOpenMatch }: Props) {
  const squad = useQuery({ queryKey: ["squad", roomId], queryFn: () => api.squad(roomId).then((r) => r.data) });
  const club = (code: string): Club => clubs.find((c) => c.code === code) ?? { code, name: code, sort_order: 0 };
  const row = (code: string) => season.table.find((r) => r.club_code === code);
  const own = row(clubCode);
  const next = season.regular_season_complete ? undefined : season.fixtures.find((f) => f.home === clubCode || f.away === clubCode);
  const opponent = next ? (next.home === clubCode ? next.away : next.home) : undefined;
  const results = (season.schedule ?? []).filter((f) => f.result && (f.home === clubCode || f.away === clubCode));
  const form = (code: string) => (season.schedule ?? []).filter((f) => f.result && (f.home === code || f.away === code)).slice(-5).map((f) => {
    const mine = f.home === code ? f.result!.home_goals : f.result!.away_goals;
    const theirs = f.home === code ? f.result!.away_goals : f.result!.home_goals;
    return mine > theirs ? "V" : mine < theirs ? "D" : "E";
  });
  const last = results.at(-1);
  const lastMatch = last ? season.matches.find((m) => m.id === last.id) : undefined;
  const manager = (code: string) => room.participants.find((p) => p.selected_club_code === code)?.display_name;
  const players = squad.data?.players ?? [];
  const best = [...players].sort((a, b) => b.overall - a.overall).slice(0, 3);
  const average = players.length ? players.reduce((sum, p) => sum + p.overall, 0) / players.length : 0;
  const ownIndex = season.table.findIndex((r) => r.club_code === clubCode);
  const window = season.table.slice(Math.max(0, ownIndex - 2), Math.max(5, ownIndex + 3));

  const lastRound = (season.schedule ?? []).filter((f) => f.result && f.round_number === season.current_round - 1);
  const news: { tag: string; text: string }[] = [];
  const biggest = [...lastRound].sort((a, b) => Math.abs(b.result!.home_goals - b.result!.away_goals) - Math.abs(a.result!.home_goals - a.result!.away_goals))[0];
  if (biggest && biggest.result) news.push({ tag: `RODADA ${biggest.round_number}`, text: `Maior placar da rodada: ${club(biggest.home).name} ${biggest.result.home_goals} × ${biggest.result.away_goals} ${club(biggest.away).name}.` });
  if (season.table[0]?.played) news.push({ tag: "LIDERANÇA", text: `${club(season.table[0].club_code).name} lidera com ${season.table[0].points} pontos${manager(season.table[0].club_code) ? `, sob o comando de ${manager(season.table[0].club_code)}` : ""}.` });
  if (season.top_scorers[0]) news.push({ tag: "ARTILHARIA", text: `${season.top_scorers[0].player_name} (${season.top_scorers[0].club_code}) é o artilheiro, com ${season.top_scorers[0].goals} gols.` });
  if (season.transfer_window_open) news.push({ tag: "MERCADO", text: "A janela do meio do campeonato está aberta: hora de reforçar o elenco para o returno." });
  if (season.champion) news.push({ tag: "CAMPEÃO", text: `${club(season.champion).name} é campeão brasileiro da temporada ${season.season_number}!` });
  const rivals = room.participants.filter((p) => p.selected_club_code && p.selected_club_code !== clubCode);
  for (const rival of rivals.slice(0, 2)) {
    const r = row(rival.selected_club_code!);
    if (r && own && r.played) news.push({ tag: "RESENHA", text: `${rival.display_name} (${club(rival.selected_club_code!).name}) está em ${r.position}º, ${Math.abs(r.points - own.points)} pts ${r.points > own.points ? "à sua frente" : r.points < own.points ? "atrás de você" : "empatado com você"}.` });
  }
  if (!news.length) news.push({ tag: "PRÉ-TEMPORADA", text: "A bola ainda não rolou. Monte a escalação, defina o plano de jogo e confirme a equipe para a primeira rodada." });

  return <div className="hub">
    <section className="hub-next" aria-label="Próxima partida">
      {next && opponent ? <>
        <p className="kicker">PRÓXIMA PARTIDA · RODADA {next.round_number}</p>
        <div className="hub-next__teams">
          <div><ClubCrest club={club(next.home)} size="md" /><strong>{club(next.home).name}</strong><small>{next.home === clubCode ? "Você · mandante" : manager(next.home) ?? "Treinador virtual"}</small></div>
          <b>×</b>
          <div><ClubCrest club={club(next.away)} size="md" /><strong>{club(next.away).name}</strong><small>{next.away === clubCode ? "Você · visitante" : manager(next.away) ?? "Treinador virtual"}</small></div>
        </div>
        <dl className="hub-next__facts"><div><dt>Adversário</dt><dd>{row(opponent)?.position ?? "—"}º · {row(opponent)?.points ?? 0} pts</dd></div><div><dt>Forma dele</dt><dd><Form list={form(opponent)} /></dd></div><div><dt>Sua forma</dt><dd><Form list={form(clubCode)} /></dd></div></dl>
        <button type="button" className="btn btn--primary btn--xl" onClick={() => onGo("next")}>{season.ready_clubs.includes(clubCode) ? "✓ Equipe confirmada — ver pré-jogo" : "Preparar partida →"}</button>
      </> : season.transfer_window_open ? <><p className="kicker">JANELA ABERTA</p><h2>Reforce o elenco para o returno</h2><button type="button" className="btn btn--primary btn--xl" onClick={() => onGo("market")}>Ir ao mercado →</button></>
        : <><p className="kicker">{season.season_complete ? "TEMPORADA ENCERRADA" : "MATA-MATA"}</p><h2>{season.champion ? `${club(season.champion).name} campeão` : "Os oito melhores disputam a taça"}</h2><button type="button" className="btn btn--primary btn--xl" onClick={() => onGo("season")}>Ver chaveamento →</button></>}
    </section>

    <section className="hub-card hub-position"><h3>Classificação</h3><div className="big-number"><b>{own?.position ?? "—"}º</b><span>{own?.points ?? 0} pts · {own?.played ?? 0} jogos</span></div>
      <ol className="mini-table">{window.map((r) => <li key={r.club_code} className={r.club_code === clubCode ? "is-own" : r.position <= 8 ? "is-qualify" : ""}><span>{r.position}</span><ClubCrest club={club(r.club_code)} size="sm" /><b>{club(r.club_code).name}</b><em>{r.points}</em></li>)}</ol>
      <button type="button" className="link" onClick={() => onGo("table")}>Tabela completa →</button></section>

    <section className="hub-card hub-last"><h3>Último resultado</h3>{last && last.result ? <button type="button" className="last-result" onClick={() => onOpenMatch(last.id)}>
      <span><ClubCrest club={club(last.home)} size="sm" />{last.home}</span><b>{last.result.home_goals} – {last.result.away_goals}</b><span>{last.away}<ClubCrest club={club(last.away)} size="sm" /></span><small>Rodada {last.round_number} · ver súmula</small>
    </button> : lastMatch ? null : <p className="hint">Nenhum jogo disputado ainda.</p>}</section>

    <section className="hub-card hub-news"><h3>Resenha do campeonato</h3><ul>{news.map((item, index) => <li key={index}><em>{item.tag}</em><p>{item.text}</p></li>)}</ul></section>

    <section className="hub-card hub-squad"><h3>Elenco</h3><div className="big-number"><b>{average ? average.toFixed(1) : "—"}</b><span>OVR médio · {players.length} atletas</span></div>
      <ul className="top-players">{best.map((p) => <li key={p.id}><PlayerPhoto name={p.name} photoUrl={p.photo_url} size="xs" /><span className="pos">{POSITION_LABEL[p.position]}</span><b>{p.name}</b><span className="ovr">{p.overall}</span></li>)}</ul>
      <div className="hub-links"><button type="button" className="link" onClick={() => onGo("squad")}>Escalação →</button><button type="button" className="link" onClick={() => onGo("tactics")}>Táticas →</button></div></section>

    <section className="hub-card hub-market"><h3>Finanças e mercado</h3><div className="big-number"><b>{squad.data ? formatMoney(squad.data.budget_cents) : "—"}</b><span>em caixa</span></div><p className="hint">{season.transfer_window_open ? "Janela aberta: propostas e trocas liberadas." : "A janela de transferências abre após a rodada 19."}</p><button type="button" className="link" onClick={() => onGo("market")}>Mercado →</button></section>
  </div>;
}

function Form({ list }: { list: string[] }) {
  if (!list.length) return <span className="hint">—</span>;
  return <span className="form-guide">{list.map((r, i) => <i key={i} className={`form-${r}`} aria-label={r === "V" ? "Vitória" : r === "D" ? "Derrota" : "Empate"}>{r}</i>)}</span>;
}
