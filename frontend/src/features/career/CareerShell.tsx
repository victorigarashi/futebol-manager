import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type Club, type RoomState, type SeasonTableRow, type SeasonView } from "../../lib/api";
import { ClubCrest } from "../../components/ClubCrest";
import { CareerPanel } from "../../components/CareerPanel";
import { readLocal, writeLocal } from "../../lib/storage";
import { StandingsTable } from "../season/StandingsTable";
import { TransferHub } from "../season/TransferHub";
import { ClubHub, type CareerTab } from "./ClubHub";
import { LineupBoard } from "./LineupBoard";
import { LiveMatchCenter } from "./live/LiveMatchCenter";
import { PostMatch } from "./PostMatch";
import { PreMatch } from "./PreMatch";
import { TacticsBoard } from "./TacticsBoard";
import "./career.css";
import { useLiveStream, useSocketOnline } from "./live/useLiveStream";

const TABS: { id: CareerTab; label: string; icon: string }[] = [
  { id: "hub", label: "Central", icon: "◆" }, { id: "next", label: "Próxima partida", icon: "▶" }, { id: "squad", label: "Elenco", icon: "▦" },
  { id: "tactics", label: "Táticas", icon: "⟁" }, { id: "market", label: "Mercado", icon: "⇄" }, { id: "season", label: "Temporada", icon: "▤" },
  { id: "table", label: "Classificação", icon: "≡" }, { id: "stats", label: "Estatísticas", icon: "▲" },
];
const STAGES: Record<string, string> = { QUARTERFINALS: "quartas de final", SEMIFINALS: "semifinais", FINAL: "final", COMPLETE: "temporada encerrada" };

export function CareerShell({ roomId, room, isHost, clubCode }: { roomId: string; room: RoomState; isHost: boolean; clubCode: string }) {
  const client = useQueryClient();
  const [tab, setTab] = useState<CareerTab>(() => (readLocal(`bm_tab_${roomId}`) as CareerTab | null) ?? "hub");
  const [openMatch, setOpenMatch] = useState<string | null>(null);
  const baseline = useRef<SeasonTableRow[] | undefined>(undefined);
  useEffect(() => { writeLocal(`bm_tab_${roomId}`, tab); }, [roomId, tab]);
  // The socket nudges refreshes when something changes; these intervals are only the
  // fallback. The (large) season view is barely needed while a match is on screen.
  // During a match the live view is kept current by the socket (`live.state`,
  // `live.stats`); HTTP only reconciles: on entry, reconnection, a sequence gap, the
  // end of the round, and a slow safety refresh. Without a socket it falls back to polling.
  const online = useSocketOnline();
  const live = useQuery({ queryKey: ["live", roomId], queryFn: () => api.live(roomId).then((r) => r.data), refetchInterval: (query) => query.state.data?.live_round ? (online ? 30_000 : 4000) : 6000 });
  useLiveStream(roomId);
  const season = useQuery({ queryKey: ["season", roomId], queryFn: () => api.season(roomId).then((r) => r.data), refetchInterval: live.data?.live_round ? 15000 : 5000 });
  const clubs = useQuery({ queryKey: ["clubs"], queryFn: () => api.clubs().then((r) => r.data), staleTime: Infinity });
  const refresh = () => void client.invalidateQueries({ predicate: (q) => q.queryKey.includes(roomId) });
  const advance = useMutation({ mutationFn: () => api.advanceRound(roomId), onSuccess: refresh });
  const closeWindow = useMutation({ mutationFn: () => api.closeTransferWindow(roomId), onSuccess: refresh });
  const nextSeason = useMutation({ mutationFn: () => api.startNextSeason(roomId), onSuccess: refresh });
  const clubList: Club[] = clubs.data ?? [];
  const club = (code: string): Club => clubList.find((c) => c.code === code) ?? { code, name: code, sort_order: 0 };

  // Keep the official table from before the live round to show movement afterwards.
  useEffect(() => { if (live.data?.live_round) baseline.current = live.data.official_table; }, [live.data]);
  // After a live round, show the report of the coach's own match until acknowledged.
  const wasLive = useRef(false);
  const liveMatchId = live.data?.match?.id;
  const lastLiveId = useRef<string | null>(null);
  useEffect(() => {
    if (live.data?.live_round && liveMatchId) { wasLive.current = true; lastLiveId.current = liveMatchId; }
    else if (wasLive.current && !live.data?.live_round && lastLiveId.current) {
      wasLive.current = false;
      if (readLocal(`bm_ack_${roomId}_${lastLiveId.current}`) !== "1") setOpenMatch(lastLiveId.current);
      refresh();
    }
  }, [live.data?.live_round, liveMatchId]); // eslint-disable-line react-hooks/exhaustive-deps

  const data = season.data;
  if (live.data?.live_round && live.data.recovering) {
    return <div className="career career--live"><div className="panel-loading panel-loading--recovering" role="status"><b>Recuperando a partida…</b><span>O servidor foi reiniciado e está reconstruindo a rodada exatamente como estava (mesmos lances, placar e ordens). A transmissão volta sozinha em instantes.</span></div></div>;
  }
  if (live.data?.live_round && live.data.match && clubList.length) {
    return <div className="career career--live"><LiveMatchCenter roomId={roomId} data={live.data} clubCode={clubCode} clubs={clubList} /></div>;
  }
  if (!data) return <div className="career"><div className="panel-loading" role="status">{season.error ? season.error.message : "Entrando no centro de treinamento…"}</div></div>;
  if (openMatch) {
    const roundNumber = data.matches.find((m) => m.id === openMatch)?.round_number;
    return <div className="career"><PostMatch roomId={roomId} matchId={openMatch} clubCode={clubCode} clubs={clubList} table={data.table} previousTable={baseline.current} roundLabel={roundNumber && roundNumber <= 38 ? `RODADA ${roundNumber}` : "MATA-MATA"} onContinue={() => { writeLocal(`bm_ack_${roomId}_${openMatch}`, "1"); setOpenMatch(null); setTab("hub"); }} /></div>;
  }

  const own = data.table.find((r) => r.club_code === clubCode);
  const manager = room.participants.find((p) => p.selected_club_code === clubCode)?.display_name;
  const actionError = advance.error ?? closeWindow.error ?? nextSeason.error;
  const locked = data.live_round ? "Há uma partida em andamento." : null;

  return <div className="career">
    <header className="career-head">
      <div className="career-head__club"><ClubCrest club={club(clubCode)} size="md" /><div><p className="kicker">MODO CARREIRA · TEMPORADA {data.season_number}</p><h1>{club(clubCode).name}</h1><span>{manager ? `Técnico ${manager}` : "Seu clube"} · {room.name}</span></div></div>
      <dl className="career-head__facts"><div><dt>Rodada</dt><dd>{data.regular_season_complete ? (data.playoffs ? STAGES[data.playoffs.next_stage] ?? "playoffs" : "playoffs") : data.current_round}</dd></div><div><dt>Posição</dt><dd>{own?.position ?? "—"}º</dd></div><div><dt>Pontos</dt><dd>{own?.points ?? 0}</dd></div><div><dt>Prontos</dt><dd>{data.ready_clubs.length}/{room.participants.filter((p) => p.selected_club_code).length}</dd></div></dl>
    </header>
    <nav className="career-nav" aria-label="Modo carreira">{TABS.map((item) => <button key={item.id} type="button" aria-current={tab === item.id ? "page" : undefined} className={tab === item.id ? "is-active" : ""} onClick={() => setTab(item.id)}><i aria-hidden="true">{item.icon}</i>{item.label}{item.id === "next" && data.ready_clubs.includes(clubCode) && <em aria-label="confirmado">✓</em>}</button>)}</nav>
    {actionError && <p className="cm-toast cm-toast--error" role="alert">{actionError.message}</p>}

    <main className="career-body" key={tab}>
      {tab === "hub" && <ClubHub roomId={roomId} room={room} season={data} clubCode={clubCode} clubs={clubList} onGo={setTab} onOpenMatch={setOpenMatch} />}
      {tab === "next" && <PreMatch roomId={roomId} room={room} season={data} clubCode={clubCode} clubs={clubList} onGo={setTab} isHost={isHost} />}
      {tab === "squad" && <LineupBoard roomId={roomId} locked={locked} />}
      {tab === "tactics" && <TacticsBoard roomId={roomId} locked={locked} />}
      {tab === "market" && <section className="market-tab">{data.transfer_window_open ? <>
        {isHost && <div className="host-bar"><p>Você é o anfitrião: encerre a janela quando todos terminarem as negociações.</p><button type="button" className="btn btn--primary" disabled={closeWindow.isPending} onClick={() => closeWindow.mutate()}>{closeWindow.isPending ? "Encerrando…" : "Encerrar janela e seguir →"}</button></div>}
        <TransferHub roomId={roomId} />
      </> : <div className="empty-feature"><h2>Mercado fechado</h2><p>A janela de transferências abre entre as rodadas 19 e 20. Até lá, acompanhe as finanças e o histórico de negociações do clube.</p></div>}<CareerPanel roomId={roomId} /></section>}
      {tab === "season" && <SeasonCalendar data={data} clubCode={clubCode} club={club} isHost={isHost} onAdvance={() => advance.mutate()} advancing={advance.isPending} onNextSeason={() => nextSeason.mutate()} nextPending={nextSeason.isPending} onOpenMatch={setOpenMatch} />}
      {tab === "table" && <section className="card card--flush"><header className="card__head"><h2>Classificação</h2><span className="badge">Oficial</span></header><StandingsTable rows={data.table} ownClub={clubCode} /></section>}
      {tab === "stats" && <section className="stats-tab">
        <div className="card"><h2>Artilharia</h2>{data.top_scorers.length ? <ol className="scorers">{data.top_scorers.map((s, i) => <li key={s.player_id} className={s.club_code === clubCode ? "is-own" : ""}><span>{i + 1}</span><ClubCrest club={club(s.club_code)} size="sm" /><b>{s.player_name}</b><em>{s.goals}</em></li>)}</ol> : <p className="hint">Os gols da temporada aparecem aqui.</p>}</div>
        <div className="card"><h2>Seu clube em números</h2>{own ? <dl className="mini-stats mini-stats--wide"><div><dt>Vitórias</dt><dd>{own.wins}</dd></div><div><dt>Empates</dt><dd>{own.draws}</dd></div><div><dt>Derrotas</dt><dd>{own.losses}</dd></div><div><dt>Gols pró</dt><dd>{own.goals_for}</dd></div><div><dt>Gols contra</dt><dd>{own.goals_against}</dd></div><div><dt>Aproveitamento</dt><dd>{own.played ? Math.round((own.points / (own.played * 3)) * 100) : 0}%</dd></div></dl> : null}</div>
        <div className="card"><h2>Evolução dos atletas</h2>{data.development_records.filter((r) => r.season_number === data.season_number).length ? <p>{data.development_records.filter((r) => r.season_number === data.season_number && r.delta > 0).length} atletas evoluíram nesta temporada.</p> : <p className="hint">A evolução (idade, potencial e minutos jogados) é calculada pelo servidor ao final da temporada.</p>}</div>
        {data.season_history.length > 0 && <div className="card"><h2>História da liga</h2><ul className="history">{data.season_history.map((h) => <li key={h.season_number}><b>Temporada {h.season_number}</b><span>🏆 {club(h.champion).name}</span>{h.top_scorers?.[0] && <small>Artilheiro: {h.top_scorers[0].player_name} ({h.top_scorers[0].goals})</small>}</li>)}</ul></div>}
      </section>}
    </main>
  </div>;
}

function SeasonCalendar({ data, clubCode, club, isHost, onAdvance, advancing, onNextSeason, nextPending, onOpenMatch }: {
  data: SeasonView; clubCode: string; club: (code: string) => Club; isHost: boolean;
  onAdvance: () => void; advancing: boolean; onNextSeason: () => void; nextPending: boolean; onOpenMatch: (id: string) => void;
}) {
  const mine = (data.schedule ?? []).filter((f) => f.home === clubCode || f.away === clubCode);
  const outcome = (f: { home: string; result: { home_goals: number; away_goals: number } | null }) => {
    if (!f.result) return "";
    const ours = f.home === clubCode ? f.result.home_goals : f.result.away_goals;
    const theirs = f.home === clubCode ? f.result.away_goals : f.result.home_goals;
    return ours > theirs ? "V" : ours < theirs ? "D" : "E";
  };
  const playoffs = data.playoffs;
  return <section className="season-tab">
    {data.regular_season_complete && <div className="card playoffs"><header className="card__head"><h2>Mata-mata</h2>{isHost && !data.season_complete && <button type="button" className="btn btn--primary" disabled={advancing} onClick={onAdvance}>{advancing ? "Disputando…" : `Disputar ${playoffs?.next_stage === "SEMIFINALS" ? "semifinais" : playoffs?.next_stage === "FINAL" ? "a final" : "quartas"} →`}</button>}{isHost && data.season_complete && <button type="button" className="btn btn--primary" disabled={nextPending} onClick={onNextSeason}>{nextPending ? "Preparando…" : "Começar próxima temporada →"}</button>}</header>
      {data.champion && <p className="champion">🏆 {club(data.champion).name} é o campeão!</p>}
      <div className="bracket">{([["Quartas", playoffs?.quarterfinals ?? []], ["Semifinais", playoffs?.semifinals ?? []], ["Final", playoffs?.final ? [playoffs.final] : []]] as const).map(([label, list]) => <div key={label}><h3>{label}</h3>{list.length ? list.map((m) => <button type="button" key={m.id} className="bracket-match" onClick={() => (m.home === clubCode || m.away === clubCode) && onOpenMatch(m.id)}>{[m.home, m.away].map((code) => <span key={code} className={m.winner === code ? "is-winner" : ""}><ClubCrest club={club(code)} size="sm" />{club(code).name}<b>{code === m.home ? m.home_goals : m.away_goals}</b></span>)}{m.home_penalties !== null && <small>Pên. {m.home_penalties}×{m.away_penalties}</small>}</button>) : <p className="hint">A definir</p>}</div>)}</div>
      {!isHost && !data.season_complete && <p className="hint">O anfitrião dispara cada fase. As partidas usam as escalações e táticas salvas.</p>}</div>}
    <div className="card"><header className="card__head"><h2>Seu calendário</h2><span className="badge">{mine.filter((f) => f.result).length}/{mine.length} jogos</span></header>
      <ol className="calendar">{mine.map((f) => {
        const home = f.home === clubCode;
        const opp = home ? f.away : f.home;
        return <li key={f.id} className={`${f.round_number === data.current_round ? "is-next" : ""} ${f.result ? "is-played" : ""}`}><span className="round">R{f.round_number}</span><span className="venue">{home ? "Casa" : "Fora"}</span><ClubCrest club={club(opp)} size="sm" /><b>{club(opp).name}</b>{f.result ? <button type="button" className={`result result--${outcome(f)}`} onClick={() => onOpenMatch(f.id)}>{f.result.home_goals}–{f.result.away_goals}</button> : <span className="result result--pending">{f.round_number === data.current_round ? "próximo" : "—"}</span>}</li>;
      })}</ol></div>
    <div className="card"><h2>Rodada {Math.min(38, data.current_round)}</h2><ul className="round-scores">{data.fixtures.map((f) => <li key={f.id} className={f.home === clubCode || f.away === clubCode ? "is-own" : ""}><span>{club(f.home).name}</span><b>{f.result ? `${f.result.home_goals} × ${f.result.away_goals}` : "×"}</b><span>{club(f.away).name}</span></li>)}</ul></div>
  </section>;
}
