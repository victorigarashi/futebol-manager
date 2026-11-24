import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type Club, type RoomState, type SeasonTableRow, type SeasonView, type SurvivorView } from "../../lib/api";
import { ClubCrest } from "../../components/ClubCrest";
import { CareerPanel } from "../../components/CareerPanel";
import { readLocal, writeLocal } from "../../lib/storage";
import { StandingsTable } from "../season/StandingsTable";
import { TransferHub } from "../season/TransferHub";
import type { CareerTab } from "./ClubHub";
import { CentralHub } from "./CentralHub";
import { Connection, RetroFooter, RetroFrame, RetroNav, RetroSubNav } from "../retro/primitives";
import { useTileNav } from "../retro/useTileNav";
import { formatMoney } from "../../lib/format";
import "./career-retro.css";
import "../retro/skin.css";
import { LineupBoard } from "./LineupBoard";
import { SquadHub } from "./SquadHub";
import { CareerSettings } from "./CareerSettings";
import { LiveMatchCenter } from "./live/LiveMatchCenter";
import { InteractiveMatch } from "./interactive/InteractiveMatch";
import { PostMatch } from "./PostMatch";
import { PreMatch } from "./PreMatch";
import { TacticsBoard } from "./TacticsBoard";
import { CohesionPanel } from "../tactics/CohesionPanel";
import { Bracket, CupPage, DrawCeremony } from "./Competitions";
import { competitionOf } from "./competition";
import { NewsCenter, StatsCenter, TrophyRoom } from "./CareerCenters";
import { isShortMode } from "../../lib/gameModes";
import "./career.css";
import { useLiveStream, useSocketOnline } from "./live/useLiveStream";

type CareerArea = "central" | "squad" | "market" | "competition" | "club" | "settings";
const AREAS: { id: CareerArea; label: string; icon: string }[] = [
  { id: "central", label: "Central", icon: "◆" }, { id: "squad", label: "Elenco", icon: "▦" }, { id: "market", label: "Mercado", icon: "⇄" }, { id: "competition", label: "Competições", icon: "▤" }, { id: "club", label: "Clube", icon: "★" }, { id: "settings", label: "Configurações", icon: "⚙" },
];
const AREA_DEFAULT: Record<CareerArea, CareerTab> = { central: "hub", squad: "roster", market: "market", competition: "season", club: "stats", settings: "settings" };
const AREA_FOR: Record<CareerTab, CareerArea> = { hub: "central", next: "central", roster: "squad", squad: "squad", tactics: "squad", market: "market", season: "competition", table: "competition", cup: "competition", stats: "club", news: "club", trophies: "club", settings: "settings" };
const STAGES: Record<string, string> = { QUARTERFINALS: "quartas de final", SEMIFINALS: "semifinais", FINAL: "final", COMPLETE: "temporada encerrada" };

/** What the lobby hands to the career: the legacy chrome (kept for live/post-match screens) and room-level actions. */
export type CareerChrome = { legacy: ReactNode; connection: "connecting" | "online" | "reconnecting" | "offline"; onHome: () => void; onEditProfile: () => void; error?: string | null };

export function CareerShell({ roomId, room, isHost, clubCode, chrome }: { roomId: string; room: RoomState; isHost: boolean; clubCode: string; chrome?: CareerChrome }) {
  const client = useQueryClient();
  const bodyRef = useRef<HTMLDivElement>(null);
  const squadQuery = useQuery({ queryKey: ["squad", roomId], queryFn: () => api.squad(roomId).then((r) => r.data) });
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
  const backToHub = useCallback(() => { if (tab !== "hub") setTab("hub"); }, [tab]);
  useTileNav(bodyRef, backToHub);
  const legacy = (node: ReactNode) => chrome ? <main className="app-shell app-shell--reference" id="top">{chrome.legacy}<div id="main-content" tabIndex={-1} />{chrome.error && <p className="feedback feedback--error" role="alert">{chrome.error}</p>}{node}</main> : <>{node}</>;
  // Retro Career: live (technical mode), post-match, loading and recovery screens get the console
  // frame; their components render untouched inside the skin. The interactive match keeps `legacy`
  // (it runs full-screen over everything, body.im-open).
  const framed = (node: ReactNode, label: string) => {
    const own = clubs.data?.find((c) => c.code === clubCode) ?? { code: clubCode, name: clubCode, sort_order: 0 };
    return <RetroFrame view="career" label={label}
      top={<header className="rt-top"><div className="rt-plate"><span className="rt-plate__crest"><ClubCrest club={own} size="md" /></span><div className="rt-plate__text"><strong>{own.name}</strong><span>{room.name} · {label}</span></div></div>
        {chrome && <div className="rt-plate rt-plate--right"><div className="rt-top__tools"><Connection state={chrome.connection} /><span className="rt-invite" title="Código de convite da sala">Convite <b>{room.code}</b></span><button type="button" className="rt-iconbtn" onClick={chrome.onHome}>Menu</button></div></div>}</header>}>
      <div className="rt-skin rt-page cr-framed">{chrome?.error && <p className="rt-toast rt-toast--error" role="alert">{chrome.error}</p>}{node}</div>
    </RetroFrame>;
  };
  if (live.data?.live_round && live.data.recovering) {
    return framed(<div className="career career--live"><div className="panel-loading panel-loading--recovering" role="status"><b>Recuperando a partida…</b><span>O servidor foi reiniciado e está reconstruindo a rodada exatamente como estava (mesmos lances, placar e ordens). A transmissão volta sozinha em instantes.</span></div></div>, "Recuperando a partida");
  }
  if (live.data?.live_round && live.data.interactive && clubList.length) {
    // Modo Jogável: the same round, the coach plays the decisive moments of his match.
    return legacy(<div className="career career--live"><InteractiveMatch roomId={roomId} clubCode={clubCode} clubs={clubList} /></div>);
  }
  if (live.data?.live_round && live.data.match && clubList.length) {
    return framed(<div className="career career--live"><LiveMatchCenter roomId={roomId} data={live.data} clubCode={clubCode} clubs={clubList} /></div>, "Ao vivo");
  }
  if (!data) return framed(<div className="career"><div className="panel-loading" role="status">{season.error ? season.error.message : "Entrando no centro de treinamento…"}</div></div>, "Carregando");
  if (openMatch) {
    const roundNumber = data.matches.find((m) => m.id === openMatch)?.round_number;
    return framed(<div className="career"><PostMatch roomId={roomId} matchId={openMatch} clubCode={clubCode} clubs={clubList} table={data.table} previousTable={baseline.current} roundLabel={roundNumber && roundNumber <= 38 ? `RODADA ${roundNumber}` : "MATA-MATA"} onContinue={() => { writeLocal(`bm_ack_${roomId}_${openMatch}`, "1"); setOpenMatch(null); setTab("hub"); }} /></div>, "Pós-jogo");
  }

  const own = data.table.find((r) => r.club_code === clubCode);
  const shortMode = isShortMode(data.game_mode ?? room.game_mode);
  const area = AREA_FOR[tab];
  const goTo = (target: CareerTab) => setTab(target);
  const areaTabs = (selectedArea: CareerArea): { id: CareerTab; label: string }[] => {
    if (selectedArea === "squad") return [{ id: "roster", label: "Visão geral" }, { id: "squad", label: "Escalação" }, { id: "tactics", label: "Táticas" }];
    if (selectedArea === "competition") return shortMode
      ? []
      : [{ id: "season", label: "Calendário" }, { id: "table", label: "Classificação" }, ...(data.knockout?.cup_enabled ? [{ id: "cup" as CareerTab, label: "Copa" }] : [])];
    if (selectedArea === "club") return [{ id: "stats", label: "Estatísticas" }, { id: "news", label: "Notícias" }, { id: "trophies", label: "Troféus" }];
    return [];
  };
  const manager = room.participants.find((p) => p.selected_club_code === clubCode)?.display_name;
  const actionError = advance.error ?? closeWindow.error ?? nextSeason.error;
  const locked = data.live_round ? "Há uma partida em andamento." : null;

  const shownAreas = AREAS.filter((item) => !shortMode || item.id !== "market");
  const subTabs = areaTabs(area);
  const humans = room.participants.filter((p) => p.selected_club_code && p.role !== "BOT");
  const ready = data.ready_clubs.includes(clubCode);
  const roundLabel = shortMode ? (data.next_round?.stage_name ?? "Torneio") : data.regular_season_complete ? (data.playoffs ? STAGES[data.playoffs.next_stage] ?? "Playoffs" : "Playoffs") : `Rodada ${data.current_round}`;
  const ownClub = club(clubCode);
  const legacyPanel = (node: ReactNode) => <div className="career rt-skin rt-legacy">{node}</div>;

  return <RetroFrame view={area === "squad" ? "squad" : "career"} fit={area === "central" || area === "squad" || area === "settings"} label={`Carreira: ${AREAS.find((a) => a.id === area)?.label}`}
    top={<header className="rt-top">
      <div className="rt-plate"><span className="rt-plate__crest"><ClubCrest club={ownClub} size="md" /></span><div className="rt-plate__text"><strong>{ownClub.name}</strong><span>{manager ? `Técnico ${manager}` : "Seu clube"} · {room.name}</span></div></div>
      <div className="rt-plate rt-plate--right">
        <div className="rt-stat"><small>Temporada {data.season_number}</small><b>{roundLabel}</b></div>
        {!shortMode && <div className="rt-stat"><small>Posição</small><b>{own?.position ?? "—"}º <em>{own?.points ?? 0} pts</em></b></div>}
        {shortMode && <div className="rt-stat"><small>Seu clube</small><b>{data.champion === clubCode ? "Campeão" : alive(data, clubCode) ? "Vivo" : "Eliminado"}</b></div>}
        {!shortMode && <div className="rt-stat"><small>Orçamento</small><b>{squadQuery.data ? formatMoney(squadQuery.data.budget_cents) : "—"}</b></div>}
        <div className="rt-stat"><small>Prontos</small><b>{data.ready_clubs.length}/{humans.length}</b></div>
        {chrome && <div className="rt-top__tools"><Connection state={chrome.connection} /><span className="rt-invite" title="Código de convite da sala">Convite <b>{room.code}</b></span><button type="button" className="rt-iconbtn" onClick={chrome.onHome}>Menu</button></div>}
      </div>
    </header>}
    nav={<div className="cr-navrow"><RetroNav label="Áreas da carreira" items={shownAreas.map((a) => ({ id: a.id, label: a.label }))} current={area} onSelect={(id) => goTo(AREA_DEFAULT[id])} />
      <button type="button" className={`rt-btn ${ready ? "rt-btn--ghost cr-ready" : "rt-btn--lime"} cr-cta`} onClick={() => goTo("next")}>{tab === "next" ? "Pré-jogo" : ready ? "✓ Equipe pronta" : "Próxima partida ▶"}</button></div>}
    footer={<RetroFooter hints={[{ key: "Enter", label: "Selecionar" }, ...(tab !== "hub" ? [{ key: "Esc", label: "Central" }] : []), ...(area === "central" ? [{ key: "↑↓←→", label: "Navegar" }] : [{ key: "← →", label: "Abas" }])]} right={<>{room.name} · {humans.length} técnicos</>} />}>
    <div ref={bodyRef} className={`cr-body cr-body--${area}`} key={tab}>
      {chrome?.error && <p className="rt-toast rt-toast--error" role="alert">{chrome.error}</p>}
      {actionError && <p className="rt-toast rt-toast--error" role="alert">{actionError.message}</p>}
      {tab === "next" ? legacyPanel(<PreMatch roomId={roomId} room={room} season={data} clubCode={clubCode} clubs={clubList} onGo={goTo} isHost={isHost} />) : <>
      {area === "central" && <CentralHub roomId={roomId} room={room} season={data} clubCode={clubCode} clubs={clubList} onGo={goTo} onOpenMatch={setOpenMatch} />}
      {area === "settings" && <CareerSettings room={room} isHost={isHost} onEditProfile={chrome?.onEditProfile} />}
      {area === "squad" && <section className="cr-squad"><RetroSubNav label="Seções do elenco" items={subTabs} current={tab} onSelect={goTo} />{tab === "roster" ? <SquadHub roomId={roomId} shortMode={shortMode} onGo={goTo} /> : tab === "squad" ? <LineupBoard roomId={roomId} locked={locked} /> : legacyPanel(<><TacticsBoard roomId={roomId} locked={locked} /><CohesionPanel roomId={roomId} locked={locked} /></>)}</section>}
      {area === "market" && !shortMode && legacyPanel(<section className="market-tab">{data.transfer_window_open ? <>
        {isHost && <div className="host-bar"><p>Você é o anfitrião: encerre a janela quando todos terminarem as negociações.</p><button type="button" className="btn btn--primary" disabled={closeWindow.isPending} onClick={() => closeWindow.mutate()}>{closeWindow.isPending ? "Encerrando…" : "Encerrar janela e seguir →"}</button></div>}
        {data.preseason_window && room.coach_moves_enabled && <CoachMarket roomId={roomId} room={room} clubCode={clubCode} club={club} clubs={clubList} onDone={refresh} />}
        <TransferHub roomId={roomId} />
      </> : <div className="empty-feature"><h2>Mercado fechado</h2><p>A janela de transferências abre na metade do campeonato e entre temporadas. Até lá, acompanhe as finanças e o histórico de negociações do clube.</p></div>}<CareerPanel roomId={roomId} /></section>)}
      {area === "competition" && <section className="cr-legacy-area">{!shortMode && <RetroSubNav label="Seções de competições" items={subTabs} current={tab} onSelect={goTo} />}{legacyPanel(shortMode ? <ShortCompetition roomId={roomId} data={data} club={club} ownClub={clubCode} /> : <>{tab === "season" && <SeasonCalendar roomId={roomId} data={data} clubCode={clubCode} club={club} isHost={isHost} onAdvance={() => advance.mutate()} advancing={advance.isPending} onNextSeason={() => nextSeason.mutate()} nextPending={nextSeason.isPending} onOpenMatch={setOpenMatch} />}{tab === "table" && <section className="card card--flush"><header className="card__head"><h2>Classificação</h2><span className="badge">Oficial</span></header><StandingsTable rows={data.table} ownClub={clubCode} /></section>}{tab === "cup" && data.knockout?.cup_enabled && <CupPage knockout={data.knockout} club={club} ownClub={clubCode} />}</>)}</section>}
      {area === "club" && <section className="cr-legacy-area"><RetroSubNav label="Seções do clube" items={subTabs} current={tab} onSelect={goTo} />{legacyPanel(<>{tab === "stats" && <StatsCenter roomId={roomId} season={data} clubCode={clubCode} club={club} />}{tab === "news" && <NewsCenter roomId={roomId} season={data} clubCode={clubCode} club={club} />}{tab === "trophies" && <TrophyRoom roomId={roomId} clubCode={clubCode} club={club} userId={room.participants.find((p) => p.selected_club_code === clubCode)?.user_id} />}</>)}</section>}
      </>}
    </div>
  </RetroFrame>;
}


function ShortCompetition({ roomId, data, club, ownClub }: { roomId: string; data: SeasonView; club: (code: string) => Club; ownClub: string }) {
  if (data.game_mode === "SURVIVOR" && data.survivor) return <SurvivorPanel roomId={roomId} survivor={data.survivor} club={club} ownClub={ownClub} />;
  if (data.knockout) return <section className="short-competition"><header className="card"><p className="kicker">TORNEIO EM JOGO ÚNICO</p><h2>{data.champion ? "Edição encerrada" : "Chave do torneio"}</h2><p>Empate no tempo normal é decidido nos pênaltis. Esta edição não tem mercado nem próxima temporada.</p></header><Bracket knockout={data.knockout} kind="TOURNAMENT" champion={data.champion} club={club} ownClub={ownClub} /></section>;
  return <section className="card"><h2>Competição</h2><p className="hint">A chave será mostrada assim que a rodada for preparada.</p></section>;
}

function SurvivorPanel({ roomId, survivor, club, ownClub }: { roomId: string; survivor: SurvivorView; club: (code: string) => Club; ownClub: string }) {
  const latest = survivor.rounds.at(-1);
  const revealKey = `bm_survivor_reveal_${roomId}_${latest?.number ?? 0}`;
  const [revealed, setRevealed] = useState(() => readLocal(revealKey) === "1");
  useEffect(() => { setRevealed(readLocal(revealKey) === "1"); }, [revealKey]);
  useEffect(() => {
    if (!latest?.eliminated.length || revealed) return;
    const timer = window.setTimeout(() => { setRevealed(true); writeLocal(revealKey, "1"); }, 1100);
    return () => window.clearTimeout(timer);
  }, [latest?.number, latest?.eliminated.length, revealKey, revealed]);
  const eliminated = new Set(latest?.eliminated ?? []);
  const ownOut = survivor.eliminated.some((entry) => entry.club === ownClub);
  return <section className="survivor-view"><header className="card"><p className="kicker">ÚLTIMO SOBREVIVENTE</p><h2>{survivor.champion ? `${club(survivor.champion).name} é campeão` : `${survivor.remaining} clubes continuam vivos`}</h2><ol className="survivor-path" aria-label="Caminho da sobrevivência">{survivor.path.map((count) => <li key={count} className={count === survivor.remaining ? "is-current" : count > survivor.remaining ? "is-done" : ""}>{count === 2 ? "Final" : count}</li>)}</ol>{ownOut && !survivor.champion && <p className="feedback">Seu clube foi eliminado; você pode acompanhar a tabela e a decisão final.</p>}</header>{latest && <section className={`card survivor-round ${revealed ? "is-revealed" : ""}`}><header className="card__head"><h2>Rodada {latest.number}</h2>{latest.eliminated.length > 0 && !revealed && <button type="button" className="btn btn--ghost" onClick={() => { setRevealed(true); writeLocal(revealKey, "1"); }}>Pular revelação</button>}</header><div className="survivor-table">{latest.table.map((row) => <div key={row.club_code} className={eliminated.has(row.club_code) && revealed ? "is-out" : "is-safe"}><b>{row.position}º</b><ClubCrest club={club(row.club_code)} size="sm" /><span>{club(row.club_code).name}</span><strong>{row.points} pts</strong><small>{row.gd >= 0 ? "+" : ""}{row.gd} SG</small>{eliminated.has(row.club_code) && revealed && <em>eliminado</em>}</div>)}</div>{latest.eliminated.length > 0 && !revealed && <p className="hint">Definindo quem permanece na disputa…</p>}</section>}<section className="card"><h2>Eliminados</h2>{survivor.eliminated.length ? <ol className="survivor-eliminated">{survivor.eliminated.map((entry) => <li key={`${entry.club}-${entry.round}`}><ClubCrest club={club(entry.club)} size="sm" /><span>{club(entry.club).name}</span><small>rodada {entry.round} · {entry.position}º</small></li>)}</ol> : <p className="hint">Ninguém foi eliminado ainda.</p>}</section></section>;
}

function SeasonCalendar({ roomId, data, clubCode, club, isHost, onAdvance, advancing, onNextSeason, nextPending, onOpenMatch }: {
  roomId: string; data: SeasonView; clubCode: string; club: (code: string) => Club; isHost: boolean;
  onAdvance: () => void; advancing: boolean; onNextSeason: () => void; nextPending: boolean; onOpenMatch: (id: string) => void;
}) {
  const mine = (data.schedule ?? []).filter((f) => f.home === clubCode || f.away === clubCode);
  const outcome = (f: { home: string; result: { home_goals: number; away_goals: number } | null }) => {
    if (!f.result) return "";
    const ours = f.home === clubCode ? f.result.home_goals : f.result.away_goals;
    const theirs = f.home === clubCode ? f.result.away_goals : f.result.home_goals;
    return ours > theirs ? "V" : ours < theirs ? "D" : "E";
  };
  return <section className="season-tab">
    {data.regular_season_complete && <PlayoffsCard roomId={roomId} data={data} club={club} clubCode={clubCode} isHost={isHost} onAdvance={onAdvance} advancing={advancing} onNextSeason={onNextSeason} nextPending={nextPending} />}
    <div className="card"><header className="card__head"><h2>Seu calendário</h2><span className="badge">{mine.filter((f) => f.result).length}/{mine.length} jogos</span></header>
      <ol className="calendar">{mine.map((f) => {
        const home = f.home === clubCode;
        const opp = home ? f.away : f.home;
        return <li key={f.id} className={`${f.round_number === data.current_round ? "is-next" : ""} ${f.result ? "is-played" : ""}`}><span className="round">R{f.round_number}</span><span className="venue">{home ? "Casa" : "Fora"}</span><ClubCrest club={club(opp)} size="sm" /><b>{club(opp).name}</b>{f.result ? <button type="button" className={`result result--${outcome(f)}`} onClick={() => onOpenMatch(f.id)}>{f.result.home_goals}–{f.result.away_goals}</button> : <span className="result result--pending">{f.round_number === data.current_round ? "próximo" : "—"}</span>}</li>;
      })}</ol></div>
    <div className="card"><h2>Rodada {Math.min(38, data.current_round)}</h2><ul className="round-scores">{data.fixtures.map((f) => <li key={f.id} className={f.home === clubCode || f.away === clubCode ? "is-own" : ""}><span>{club(f.home).name}</span><b>{f.result ? `${f.result.home_goals} × ${f.result.away_goals}` : "×"}</b><span>{club(f.away).name}</span></li>)}</ul></div>
  </section>;
}

/** Optional coach market (between seasons): take over a club without a human coach. */
function CoachMarket({ roomId, room, clubCode, club, clubs, onDone }: { roomId: string; room: RoomState; clubCode: string; club: (code: string) => Club; clubs: Club[]; onDone: () => void }) {
  const [target, setTarget] = useState("");
  const taken = new Set(room.participants.filter((p) => p.role !== "BOT" && p.selected_club_code).map((p) => p.selected_club_code));
  const free = clubs.filter((c) => !taken.has(c.code) && c.code !== clubCode);
  const change = useMutation({ mutationFn: () => api.changeCoachClub(roomId, target), onSuccess: () => { onDone(); window.location.reload(); } });
  return <section className="card coach-market"><h2>Mercado de técnicos</h2><p>Entre temporadas você pode assumir outro clube sem técnico humano. Elenco e dinheiro ficam com os clubes; seus títulos e estatísticas continuam com você. {club(clubCode).name} passa a ter treinador virtual.</p>
    <div className="settings-row"><label>Novo clube<select value={target} onChange={(e) => setTarget(e.target.value)}><option value="">Continuar no {club(clubCode).name}</option>{free.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}</select></label>
      <button type="button" className="btn btn--primary" disabled={!target || change.isPending} onClick={() => change.mutate()}>{change.isPending ? "Assinando…" : "Assumir clube"}</button></div>
    {change.error && <p className="feedback feedback--error" role="alert">{change.error.message}</p>}</section>;
}

/** Playoffs: pot draw ceremony, live rounds, bracket and the next-season button. */
function PlayoffsCard({ roomId, data, club, clubCode, isHost, onAdvance, advancing, onNextSeason, nextPending }: {
  roomId: string; data: SeasonView; club: (code: string) => Club; clubCode: string; isHost: boolean;
  onAdvance: () => void; advancing: boolean; onNextSeason: () => void; nextPending: boolean;
}) {
  const knockout = data.knockout;
  const playoffs = knockout ? competitionOf(knockout, "PLAYOFF") : null;
  const drawn = Boolean(playoffs?.ties.length);
  const next = data.next_round;
  const nextLabel = next && next.kind !== "LEAGUE" ? `${next.kind === "CUP" ? "Copa: " : ""}${next.stage_name ?? "rodada"}${playoffs && playoffs.legs === 2 && next.kind === "PLAYOFF" ? ` (${next.leg === 1 ? "ida" : "volta"})` : ""}` : "rodada";
  return <div className="card playoffs"><header className="card__head"><h2>Playoffs{playoffs?.currentStage && !data.champion ? ` · ${playoffs.pending?.stage_name}` : ""}</h2>
    {isHost && !data.season_complete && !data.live_round && <button type="button" className="btn btn--primary" disabled={advancing} onClick={onAdvance}>{advancing ? "Aguarde…" : !drawn && (!next || next.kind === "LEAGUE") ? "Realizar sorteio dos potes →" : `Iniciar ${nextLabel.toLowerCase()} →`}</button>}
    {isHost && data.season_complete && <button type="button" className="btn btn--primary" disabled={nextPending} onClick={onNextSeason}>{nextPending ? "Preparando…" : "Começar próxima temporada →"}</button>}</header>
    {knockout && drawn ? <><DrawCeremony roomId={roomId} draw={playoffs?.draws.find((d) => d.kind === "POTS")} legs={playoffs?.legs ?? 1} club={club} ownClub={clubCode} /><Bracket knockout={knockout} kind="PLAYOFF" champion={data.champion ?? null} club={club} ownClub={clubCode} /></>
      : data.champion ? <p className="champion">🏆 {club(data.champion).name} é o campeão!</p>
      : <p className="hint">Os 8 primeiros vão aos playoffs. Pote 1: 1º ao 4º; pote 2: 5º ao 8º. Premiação acumulativa: R$ 50 mi por chegar às quartas, +R$ 100 mi na semifinal, +R$ 150 mi ao vice e +R$ 200 mi ao campeão.</p>}
    {!isHost && !data.season_complete && <p className="hint">Cada confronto é jogado ao vivo. Confirme sua equipe na aba Próxima partida; o anfitrião também pode iniciar a rodada.</p>}
  </div>;
}

/** Still in a short competition: not knocked out of a decided tie, not eliminated in survival. */
function alive(data: SeasonView, club: string): boolean {
  if (data.game_mode === "SURVIVOR" && data.survivor) return data.survivor.active.includes(club);
  return !Object.values(data.knockout?.ties ?? {}).some((t) => t.winner && t.winner !== club && (t.high === club || t.low === club));
}
