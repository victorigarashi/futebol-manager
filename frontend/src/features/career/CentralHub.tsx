import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api, type Club, type RoomState, type SeasonView } from "../../lib/api";
import { ClubCrest } from "../../components/ClubCrest";
import { PlayerPhoto } from "../../components/PlayerPhoto";
import { formatMoney } from "../../lib/format";
import { POSITION_LABEL } from "./labels";
import { FormGuide, TileArt } from "../retro/primitives";
import type { CareerTab } from "./ClubHub";

type Props = { roomId: string; room: RoomState; season: SeasonView; clubCode: string; clubs: Club[]; onGo: (tab: CareerTab) => void; onOpenMatch: (id: string) => void };
type Story = { tag: string; title: string; text: string; crest?: string; action?: () => void; actionLabel?: string };

/**
 * Career Central (console style). Every number, fixture and headline comes from the real
 * season state: rounds (the game has no calendar dates), the official table, the schedule,
 * the scorers and the participants. Nothing is invented to fill a tile.
 */
export function CentralHub({ roomId, room, season, clubCode, clubs, onGo, onOpenMatch }: Props) {
  const squad = useQuery({ queryKey: ["squad", roomId], queryFn: () => api.squad(roomId).then((r) => r.data) });
  const club = (code: string): Club => clubs.find((c) => c.code === code) ?? { code, name: code, sort_order: 0 };
  const row = (code: string) => season.table.find((r) => r.club_code === code);
  const own = row(clubCode);
  const schedule = season.schedule ?? [];
  const mine = schedule.filter((f) => f.home === clubCode || f.away === clubCode);
  const next = season.regular_season_complete ? undefined : season.fixtures.find((f) => f.home === clubCode || f.away === clubCode);
  const opponent = next ? (next.home === clubCode ? next.away : next.home) : undefined;
  const form = (code: string) => schedule.filter((f) => f.result && (f.home === code || f.away === code)).slice(-5).map((f) => {
    const a = f.home === code ? f.result!.home_goals : f.result!.away_goals, b = f.home === code ? f.result!.away_goals : f.result!.home_goals;
    return a > b ? "V" : a < b ? "D" : "E";
  });
  const manager = (code: string) => room.participants.find((p) => p.selected_club_code === code && p.role !== "BOT")?.display_name;
  const humans = room.participants.filter((p) => p.selected_club_code && p.role !== "BOT");
  const players = squad.data?.players ?? [];
  const best = [...players].sort((a, b) => b.overall - a.overall).slice(0, 3);
  const average = players.length ? players.reduce((sum, p) => sum + p.overall, 0) / players.length : 0;
  const ready = season.ready_clubs.includes(clubCode);

  // round strip: this round and the next ones of my club (rounds, not dates)
  const strip = mine.filter((f) => f.round_number >= Math.max(1, season.current_round - 1)).slice(0, 7);

  // headlines derived from real events only
  const stories: Story[] = [];
  const results = mine.filter((f) => f.result);
  const last = results.at(-1);
  if (last?.result) {
    const won = (last.home === clubCode ? last.result.home_goals - last.result.away_goals : last.result.away_goals - last.result.home_goals);
    stories.push({ tag: `Rodada ${last.round_number}`, title: `${club(last.home).name} ${last.result.home_goals} × ${last.result.away_goals} ${club(last.away).name}`, text: won > 0 ? "Vitória no último jogo. Veja a súmula completa." : won < 0 ? "Derrota no último jogo. Veja a súmula e ajuste a equipe." : "Empate no último jogo. Veja a súmula completa.", crest: last.home === clubCode ? last.away : last.home, action: () => onOpenMatch(last.id), actionLabel: "Ver súmula" });
  }
  const lastRound = schedule.filter((f) => f.result && f.round_number === season.current_round - 1);
  const biggest = [...lastRound].sort((a, b) => Math.abs(b.result!.home_goals - b.result!.away_goals) - Math.abs(a.result!.home_goals - a.result!.away_goals))[0];
  if (biggest?.result && biggest.id !== last?.id) stories.push({ tag: `Rodada ${biggest.round_number}`, title: `Maior placar: ${club(biggest.home).name} ${biggest.result.home_goals} × ${biggest.result.away_goals} ${club(biggest.away).name}`, text: "O resultado mais elástico da última rodada.", crest: biggest.home });
  if (season.table[0]?.played) stories.push({ tag: "Liderança", title: `${club(season.table[0].club_code).name} lidera com ${season.table[0].points} pontos`, text: manager(season.table[0].club_code) ? `Sob o comando de ${manager(season.table[0].club_code)}.` : "Comandado pelo treinador virtual.", crest: season.table[0].club_code, action: () => onGo("table"), actionLabel: "Classificação" });
  if (season.top_scorers[0]) stories.push({ tag: "Artilharia", title: `${season.top_scorers[0].player_name} é o artilheiro`, text: `${season.top_scorers[0].goals} gols pelo ${club(season.top_scorers[0].club_code).name}.`, crest: season.top_scorers[0].club_code });
  if (season.transfer_window_open) stories.push({ tag: "Mercado", title: "Janela de transferências aberta", text: "Propostas e trocas liberadas para reforçar o elenco.", action: () => onGo("market"), actionLabel: "Mercado" });
  if (season.champion) stories.push({ tag: "Campeão", title: `${club(season.champion).name} é campeão`, text: `Título da temporada ${season.season_number}.`, crest: season.champion });
  for (const rival of humans.filter((p) => p.selected_club_code !== clubCode).slice(0, 2)) {
    const r = row(rival.selected_club_code!);
    if (r && own && r.played) stories.push({ tag: "Resenha", title: `${rival.display_name} está em ${r.position}º`, text: `${club(rival.selected_club_code!).name}, ${Math.abs(r.points - own.points)} pts ${r.points > own.points ? "à sua frente" : r.points < own.points ? "atrás de você" : "empatado com você"}.`, crest: rival.selected_club_code! });
  }
  if (!stories.length) stories.push({ tag: `Temporada ${season.season_number}`, title: "A bola ainda não rolou", text: "Monte a escalação, defina o plano de jogo e confirme a equipe para a primeira rodada.", crest: clubCode, action: () => onGo("squad"), actionLabel: "Escalação" });
  const [page, setPage] = useState(0);
  useEffect(() => {
    if (stories.length < 2 || window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    const t = window.setInterval(() => setPage((p) => (p + 1) % stories.length), 7000);
    return () => window.clearInterval(t);
  }, [stories.length]);
  const story = stories[page % stories.length];

  const ownIndex = season.table.findIndex((r) => r.club_code === clubCode);
  const tableWindow = season.table.slice(Math.max(0, Math.min(ownIndex - 2, season.table.length - 6)), Math.max(6, Math.min(ownIndex - 2, season.table.length - 6) + 6));

  // main action according to the real state of the room
  const advance = next && opponent ? { title: "Avançar", sub: `${season.regular_season_complete ? "" : `Rodada ${next.round_number} · `}${ready ? "equipe confirmada" : "prepare a equipe"}`, cta: ready ? "Ver pré-jogo" : "Preparar partida", go: () => onGo("next") }
    : season.transfer_window_open ? { title: "Janela aberta", sub: "Reforce o elenco antes de seguir", cta: "Ir ao mercado", go: () => onGo("market") }
    : { title: season.season_complete ? "Temporada encerrada" : "Mata-mata", sub: season.champion ? `${club(season.champion).name} campeão` : "Os oito melhores disputam a taça", cta: "Ver chaveamento", go: () => onGo("season") };

  return <div className="ch">
    <button type="button" data-rt-tile className="rt-tile ch-advance" onClick={advance.go} autoFocus>
      <div className="ch-advance__head"><h2 className="rt-h rt-h--xl">{advance.title}</h2><p className="rt-sub">{advance.sub}</p></div>
      {strip.length > 0 && <ol className="ch-strip" aria-label="Próximas rodadas do seu clube">{strip.map((f) => {
        const home = f.home === clubCode, opp = home ? f.away : f.home;
        const current = f.round_number === season.current_round && !season.regular_season_complete;
        const res = f.result ? (home ? `${f.result.home_goals}–${f.result.away_goals}` : `${f.result.away_goals}–${f.result.home_goals}`) : null;
        return <li key={f.id} className={`${current ? "is-current" : ""} ${f.result ? "is-played" : ""}`}><small>R{f.round_number}</small><ClubCrest club={club(opp)} size="sm" /><span>{home ? "Casa" : "Fora"}</span>{res && <b>{res}</b>}</li>;
      })}</ol>}
      <div className="ch-advance__foot">
        <ul className="ch-ready" aria-label="Técnicos prontos">{humans.map((p) => <li key={p.user_id} className={season.ready_clubs.includes(p.selected_club_code!) ? "is-ready" : ""}><i aria-hidden="true" />{p.display_name}<small>{season.ready_clubs.includes(p.selected_club_code!) ? "pronto" : "aguardando"}</small></li>)}</ul>
        <span className="rt-btn rt-btn--lime">{advance.cta} ▶</span>
      </div>
    </button>

    <article className="rt-panel ch-story" aria-live="polite">
      <div className="ch-story__body" key={page}>
        <p className="rt-kicker">{story.tag}</p>
        <h2 className="rt-h">{story.title}</h2>
        <p className="rt-sub">{story.text}</p>
        {story.action && <button type="button" data-rt-tile className="rt-btn rt-btn--ghost ch-story__cta" onClick={story.action}>{story.actionLabel} →</button>}
      </div>
      {story.crest && <div className="ch-story__crest"><ClubCrest club={club(story.crest)} size="lg" /></div>}
      {stories.length > 1 && <div className="rt-pager ch-story__pager" role="tablist" aria-label="Notícias">{stories.map((s, i) => <button key={s.tag + i} type="button" role="tab" aria-selected={i === page % stories.length} aria-label={`Notícia ${i + 1}: ${s.title}`} className={i === page % stories.length ? "is-on" : ""} onClick={() => setPage(i)} />)}</div>}
    </article>

    <button type="button" data-rt-tile className="rt-tile ch-next" onClick={() => onGo(next ? "next" : "season")}>
      <p className="rt-kicker">Próximo jogo{next ? ` · Campeonato · Rodada ${next.round_number}` : ""}</p>
      {next && opponent ? <>
        <div className="ch-next__teams">
          <div><ClubCrest club={club(next.home)} size="lg" /><b>{club(next.home).name}</b><small>{next.home === clubCode ? "Você · mandante" : manager(next.home) ?? "Treinador virtual"}</small></div>
          <span className="ch-vs">×</span>
          <div><ClubCrest club={club(next.away)} size="lg" /><b>{club(next.away).name}</b><small>{next.away === clubCode ? "Você · visitante" : manager(next.away) ?? "Treinador virtual"}</small></div>
        </div>
        <dl className="ch-next__facts"><div><dt>Adversário</dt><dd>{row(opponent)?.position ?? "—"}º · {row(opponent)?.points ?? 0} pts</dd></div><div><dt>Forma dele</dt><dd><FormGuide list={form(opponent)} /></dd></div><div><dt>Sua forma</dt><dd><FormGuide list={form(clubCode)} /></dd></div></dl>
      </> : <p className="rt-sub">Sem jogo de liga nesta fase. Veja o chaveamento em Competições.</p>}
    </button>

    <button type="button" data-rt-tile className="rt-tile ch-table" onClick={() => onGo("table")}>
      <p className="rt-kicker">Classificação</p>
      <table><thead><tr><th>#</th><th>Clube</th><th>J</th><th>SG</th><th>PTS</th></tr></thead>
        <tbody>{tableWindow.map((r) => <tr key={r.club_code} className={r.club_code === clubCode ? "is-own" : r.position <= 8 ? "is-qualify" : ""}><td>{r.position}</td><td><span className="ch-table__club"><ClubCrest club={club(r.club_code)} size="sm" />{club(r.club_code).name}</span></td><td>{r.played}</td><td>{r.goal_difference > 0 ? "+" : ""}{r.goal_difference}</td><td><b>{r.points}</b></td></tr>)}</tbody></table>
    </button>

    <div className="ch-col">
      <button type="button" data-rt-tile className="rt-tile ch-squad" onClick={() => onGo("squad")}>
        <p className="rt-kicker">Elenco</p>
        <div className="ch-big"><b>{average ? average.toFixed(1) : "—"}</b><span>overall médio<br />{players.length} atletas</span></div>
        <ul className="ch-top">{best.map((p) => <li key={p.id}><PlayerPhoto name={p.name} photoUrl={p.photo_url} size="xs" /><span className={`rt-pos rt-pos--${p.position}`}>{POSITION_LABEL[p.position]}</span><span className="ch-top__name">{p.name}</span><b className="rt-ovr">{p.overall}</b></li>)}</ul>
        <TileArt kind="shirt" />
      </button>
      <button type="button" data-rt-tile className="rt-tile ch-money" onClick={() => onGo("market")}>
        <p className="rt-kicker">Finanças</p>
        <div className="ch-big"><b>{squad.data ? formatMoney(squad.data.budget_cents) : "—"}</b></div>
        <p className="rt-sub">{season.transfer_window_open ? "Janela aberta: propostas e trocas liberadas." : "Janela de transferências após a rodada 19."}</p>
        <TileArt kind="money" />
      </button>
    </div>
  </div>;
}
