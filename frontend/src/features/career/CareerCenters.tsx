import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api, type Club, type PlayerSeasonStats, type SeasonView } from "../../lib/api";
import { ClubCrest } from "../../components/ClubCrest";

type ClubOf = (code: string) => Club;

const NEWS_KINDS: Record<string, string> = {
  LEADER: "Liderança", RACE: "Briga por vaga", CLASSIC: "Clássico", ROUT: "Goleada", STAR: "Destaque", KNOCKOUT: "Mata-mata",
  TITLE: "Título", TRANSFER: "Transferência", RUMOR: "Rumor", GROWTH: "Evolução",
};

/** News centre: items generated from real events only (filters by club, type, season). */
export function NewsCenter({ roomId, season, clubCode, club }: { roomId: string; season: SeasonView; clubCode: string; club: ClubOf }) {
  const [onlyMine, setOnlyMine] = useState(false);
  const [kind, setKind] = useState("");
  const news = useQuery({ queryKey: ["news", roomId, onlyMine, kind, season.season_number], queryFn: () => api.careerNews(roomId, { club: onlyMine ? clubCode : undefined, kind: kind || undefined }).then((r) => r.data.items), refetchInterval: 15000 });
  return <section className="news-center">
    <header className="card news-center__filters"><h2>Central de notícias</h2>
      <label className="toggle-row"><input type="checkbox" checked={onlyMine} onChange={(e) => setOnlyMine(e.target.checked)} /><span><b>Só meu clube</b></span></label>
      <label>Tipo<select value={kind} onChange={(e) => setKind(e.target.value)}><option value="">Todas</option>{Object.entries(NEWS_KINDS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
    </header>
    {news.error && <p className="feedback feedback--error" role="alert">{news.error.message}</p>}
    {!news.data ? <p className="muted" role="status">Carregando notícias…</p> : news.data.length === 0 ? <div className="empty-feature"><h2>Sem notícias ainda</h2><p>As notícias nascem dos jogos, da tabela e do mercado. Dispute a primeira rodada.</p></div> :
      <ol className="news-feed">{news.data.map((item) => <li key={item.id} className={`news-item news-item--${item.kind.toLowerCase()} ${item.clubs.includes(clubCode) ? "is-own" : ""}`}>
        <span className="news-item__tag">{NEWS_KINDS[item.kind] ?? item.kind}</span>
        <div><strong>{item.title}</strong><p>{item.body}</p></div>
        <span className="news-item__crests">{item.clubs.slice(0, 2).map((code) => <ClubCrest key={code} club={club(code)} size="sm" />)}</span>
      </li>)}</ol>}
    <p className="hint">Rumores apenas indicam interesse real registrado no mercado; valores de negociações nunca são divulgados.</p>
  </section>;
}

function Leaders({ title, rows, value, club, clubCode, unit }: { title: string; rows: PlayerSeasonStats[]; value: (r: PlayerSeasonStats) => string | number; club: ClubOf; clubCode: string; unit?: string }) {
  return <div className="card"><h2>{title}</h2>{rows.length ? <ol className="scorers">{rows.slice(0, 10).map((r, i) => <li key={r.player_id} className={r.club_code === clubCode ? "is-own" : ""}><span>{i + 1}</span><ClubCrest club={club(r.club_code)} size="sm" /><b>{r.name}</b><em>{value(r)}{unit ? ` ${unit}` : ""}</em></li>)}</ol> : <p className="hint">Sem dados ainda.</p>}</div>;
}

/** Stats centre: everything computed by the server from committed matches. */
export function StatsCenter({ roomId, season, clubCode, club }: { roomId: string; season: SeasonView; clubCode: string; club: ClubOf }) {
  const [competition, setCompetition] = useState("");
  const stats = useQuery({ queryKey: ["career-stats", roomId, competition, season.season_number], queryFn: () => api.careerStats(roomId, competition || undefined).then((r) => r.data), refetchInterval: 20000 });
  const own = season.table.find((r) => r.club_code === clubCode);
  const data = stats.data;
  return <section className="stats-tab">
    <header className="card stats-tab__filters"><h2>Estatísticas · Temporada {season.season_number}</h2>
      <div className="segmented" role="group" aria-label="Competição">{[["", "Tudo"], ["LEAGUE", "Brasileirão"], ["PLAYOFF", "Playoffs"], ...(season.knockout?.cup_enabled ? [["CUP", "Copa"]] : [])].map(([value, label]) => <button key={value} type="button" aria-pressed={competition === value} className={competition === value ? "is-active" : ""} onClick={() => setCompetition(value)}>{label}</button>)}</div>
    </header>
    {stats.error && <p className="feedback feedback--error" role="alert">{stats.error.message}</p>}
    {!data ? <p className="muted" role="status">Calculando estatísticas…</p> : <>
      <div className="stats-grid">
        <Leaders title="Artilharia" rows={data.scorers.filter((r) => r.goals > 0)} value={(r) => r.goals} unit="gols" club={club} clubCode={clubCode} />
        <Leaders title="Assistências" rows={data.assists.filter((r) => r.assists > 0)} value={(r) => r.assists} club={club} clubCode={clubCode} />
        <Leaders title="Melhores notas" rows={data.ratings} value={(r) => (r.rating ?? 0).toFixed(2)} club={club} clubCode={clubCode} />
        <Leaders title="Goleiros" rows={data.goalkeepers} value={(r) => `${r.clean_sheets} SG · ${r.saves} def.`} club={club} clubCode={clubCode} />
      </div>
      {data.team_of_season.length > 0 && <div className="card"><h2>Seleção da temporada</h2><ul className="team-of-season">{data.team_of_season.map((p) => <li key={p.player_id}><span className="pos">{p.position}</span><ClubCrest club={club(p.club_code)} size="sm" /><b>{p.name}</b><em>{p.rating?.toFixed(2)}</em></li>)}</ul></div>}
      <div className="stats-grid">
        <div className="card"><h2>Seu clube em números</h2>{own ? <dl className="mini-stats mini-stats--wide"><div><dt>Vitórias</dt><dd>{own.wins}</dd></div><div><dt>Empates</dt><dd>{own.draws}</dd></div><div><dt>Derrotas</dt><dd>{own.losses}</dd></div><div><dt>Gols pró</dt><dd>{own.goals_for}</dd></div><div><dt>Gols contra</dt><dd>{own.goals_against}</dd></div><div><dt>Pontos</dt><dd>{own.points}</dd></div></dl> : <p className="hint">—</p>}</div>
        <div className="card"><h2>Recordes</h2>{data.records.biggest_win ? <ul className="records"><li><span>Maior goleada</span><b>{data.records.biggest_win.home} {data.records.biggest_win.home_goals} × {data.records.biggest_win.away_goals} {data.records.biggest_win.away}</b><small>T{data.records.biggest_win.season}</small></li>{data.records.most_goals && <li><span>Jogo com mais gols</span><b>{data.records.most_goals.home} {data.records.most_goals.home_goals} × {data.records.most_goals.away_goals} {data.records.most_goals.away}</b><small>T{data.records.most_goals.season}</small></li>}</ul> : <p className="hint">Sem jogos ainda.</p>}</div>
        <div className="card"><h2>Técnicos</h2>{data.coaches.length ? <table className="mini-table"><thead><tr><th>Técnico</th><th>J</th><th>V</th><th>E</th><th>D</th><th>Aprov.</th></tr></thead><tbody>{data.coaches.map((c) => <tr key={c.club_code} className={c.club_code === clubCode ? "is-own" : ""}><td><ClubCrest club={club(c.club_code)} size="sm" /> {c.coach}</td><td>{c.played}</td><td>{c.wins}</td><td>{c.draws}</td><td>{c.losses}</td><td>{c.played ? Math.round(((c.wins * 3 + c.draws) / (c.played * 3)) * 100) : 0}%</td></tr>)}</tbody></table> : <p className="hint">—</p>}</div>
        {data.rivals.length > 0 && <div className="card"><h2>Confronto entre técnicos</h2><ul className="records">{data.rivals.map((r) => <li key={r.clubs.join("-")}><span>{club(r.clubs[0]).name} × {club(r.clubs[1]).name}</span><b>{r.wins[r.clubs[0]] ?? 0} V · {r.draws} E · {r.wins[r.clubs[1]] ?? 0} V</b><small>{r.meetings} jogos</small></li>)}</ul></div>}
      </div>
      <DevelopmentCard data={data.development} />
      {data.history.length > 0 && <div className="card"><h2>Comparativo de temporadas</h2><table className="mini-table"><thead><tr><th>Temp.</th><th>Campeão</th><th>Vice</th><th>Líder da fase</th><th>Copa</th><th>Craque</th></tr></thead><tbody>{data.history.map((h) => <tr key={h.season_number}><td>{h.season_number}</td><td>{h.champion ? club(h.champion).name : "—"}</td><td>{h.runner_up ? club(h.runner_up).name : "—"}</td><td>{h.league_leader ? club(h.league_leader).name : "—"}</td><td>{h.cup_champion ? club(h.cup_champion).name : "—"}</td><td>{h.best_player ? `${h.best_player.name} (${h.best_player.rating?.toFixed(2)})` : "—"}</td></tr>)}</tbody></table></div>}
    </>}
  </section>;
}

function DevelopmentCard({ data }: { data: { player_id: string; name?: string; season_number: number; overall_before: number; overall_after: number; delta: number }[] }) {
  const rows = data.filter((r) => r.delta !== 0).sort((a, b) => b.delta - a.delta);
  if (!rows.length) return null;
  return <div className="card"><h2>Evolução de overall</h2><ul className="records">{rows.slice(0, 8).map((r) => <li key={`${r.player_id}-${r.season_number}`}><span>{r.name ?? r.player_id}</span><b className={r.delta > 0 ? "up" : "down"}>{r.overall_before} → {r.overall_after} ({r.delta > 0 ? "+" : ""}{r.delta})</b><small>T{r.season_number}</small></li>)}</ul></div>;
}

/** Trophy room: every title and runner-up, with the club and the coach of the time. */
export function TrophyRoom({ roomId, clubCode, club, userId }: { roomId: string; clubCode: string; club: ClubOf; userId?: string }) {
  const trophies = useQuery({ queryKey: ["trophies", roomId], queryFn: () => api.careerTrophies(roomId).then((r) => r.data.trophies), refetchInterval: 30000 });
  const items = trophies.data ?? [];
  const titles = items.filter((t) => t.place === "CHAMPION");
  const mine = items.filter((t) => (userId && t.coach_user_id === userId) || (!t.coach_user_id && t.club_code === clubCode));
  return <section className="trophy-room">
    <header className="card trophy-room__head"><p className="kicker">SALA DE TROFÉUS</p><h2>{mine.filter((t) => t.place === "CHAMPION").length} título(s) na sua carreira</h2></header>
    {trophies.error && <p className="feedback feedback--error" role="alert">{trophies.error.message}</p>}
    {!trophies.data ? <p className="muted" role="status">Abrindo a sala de troféus…</p> : titles.length === 0 ? <div className="empty-feature"><h2>A estante está vazia</h2><p>Os troféus aparecem aqui quando um campeão é definido nos playoffs ou na Copa do Brasil.</p></div> :
      <ul className="trophy-shelf">{items.map((t, i) => <li key={i} className={`trophy trophy--${t.place.toLowerCase()} ${mine.includes(t) ? "is-own" : ""}`}>
        <span className="trophy__icon" aria-hidden="true">{t.place === "CHAMPION" ? "🏆" : "🥈"}</span>
        <strong>{t.competition === "BRASILEIRAO" ? "Brasileirão" : "Copa do Brasil"}</strong>
        <span>{t.place === "CHAMPION" ? "Campeão" : "Vice"} · Temporada {t.season_number}</span>
        <span><ClubCrest club={club(t.club_code)} size="sm" /> {club(t.club_code).name}</span>
        <small>{t.coach_name ? `Técnico ${t.coach_name}` : "Treinador virtual"}</small>
      </li>)}</ul>}
  </section>;
}
