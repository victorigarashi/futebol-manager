import { useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api, type Club, type EngineEvent, type LiveMatch, type MatchPlayer, type SeasonTableRow } from "../../lib/api";
import { ClubCrest } from "../../components/ClubCrest";
import { matchKits } from "./clubColors";
import { FrameBuffer } from "./live/frameBuffer";
import { PitchCanvas } from "./live/PitchCanvas";
import { KEY_EVENTS, POSITION_LABEL, eventText, tacticSummary } from "./labels";

type Props = { roomId: string; matchId: string; clubCode: string; clubs: Club[]; table: SeasonTableRow[]; previousTable?: SeasonTableRow[]; roundLabel: string; onContinue: () => void };

/** Full-time report: result, scorers, ratings, coach decisions and table impact. */
export function PostMatch({ roomId, matchId, clubCode, clubs, table, previousTable, roundLabel, onContinue }: Props) {
  const match = useQuery({ queryKey: ["finished-match", roomId, matchId], queryFn: () => api.finishedMatch(roomId, matchId).then((r) => r.data), staleTime: Infinity });
  const [replay, setReplay] = useState<EngineEvent | null>(null);
  const club = (code: string): Club => clubs.find((c) => c.code === code) ?? { code, name: code, sort_order: 0 };
  const data = match.data;
  if (!data) return <div className="panel-loading" role="status">{match.error ? match.error.message : "Buscando a súmula oficial…"}</div>;
  const you = data.home === clubCode ? "home" : "away";
  const ours = you === "home" ? data.home_goals : data.away_goals;
  const theirs = you === "home" ? data.away_goals : data.home_goals;
  const headline = ours > theirs ? "VITÓRIA" : ours < theirs ? "DERROTA" : "EMPATE";
  const goals = data.events.filter((e) => e.kind === "GOAL");
  const position = table.find((row) => row.club_code === clubCode);
  const before = previousTable?.find((row) => row.club_code === clubCode);
  const move = position && before ? before.position - position.position : 0;
  const all = [...data.lineups.home, ...data.lineups.away].filter((p) => p.entered_tick !== null);
  const stats = data.statistics;
  const keyEvents = data.events.filter((e) => KEY_EVENTS.has(e.kind) && !["TACTICS"].includes(e.kind) || (e.kind === "TACTICS" && e.team === clubCode));

  return <section className={`postmatch postmatch--${headline.toLowerCase()}`} aria-label="Pós-jogo">
    <header className="postmatch__hero">
      <p className="kicker">APITO FINAL · {roundLabel}</p>
      <h1>{headline}</h1>
      <div className="postmatch__score"><span><ClubCrest club={club(data.home)} size="md" /><b>{club(data.home).name}</b></span><strong>{data.home_goals}<i>–</i>{data.away_goals}</strong><span><ClubCrest club={club(data.away)} size="md" /><b>{club(data.away).name}</b></span></div>
      {data.home_penalties != null && <p className="postmatch__pens">Pênaltis: {data.home_penalties} × {data.away_penalties}</p>}
      <ul className="postmatch__scorers">{goals.map((g) => <li key={g.event_id} className={g.team === data.home ? "is-home" : "is-away"}><b>{g.minute}′</b> {g.player_name}{g.secondary_player_name ? <small> (assist. {g.secondary_player_name})</small> : null}<button type="button" className="link" onClick={() => setReplay(g)}>rever</button></li>)}</ul>
    </header>

    {replay && <GoalReplay roomId={roomId} match={data} goal={replay} onClose={() => setReplay(null)} clubName={(code) => club(code).name} />}

    <div className="postmatch__grid">
      <section className="card"><h3>Impacto na temporada</h3>
        <div className="impact"><b>{position ? `${position.position}º` : "—"}</b><span>{move > 0 ? `↑ subiu ${move}` : move < 0 ? `↓ caiu ${-move}` : "manteve a posição"}</span><small>{position ? `${position.points} pts em ${position.played} jogos` : ""}</small></div>
        {data.player_of_the_match && <p className="motm">Craque do jogo: <b>{data.player_of_the_match.name}</b> <span className="rating rating--great">{data.player_of_the_match.rating.toFixed(1)}</span></p>}
        <h4>Suas decisões</h4>
        {(data.commands ?? []).length ? <ol className="decisions">{(data.commands ?? []).map((c) => <li key={c.command_id}><small>{Math.floor((c.applied_tick ?? 0) / 60)}′</small> {c.kind === "TACTICS" && c.tactics ? `Nova orientação: ${tacticSummary(c.tactics)}` : `Entrou ${playerName(all, c.in_player_id)}, saiu ${playerName(all, c.out_player_id)}`}{c.kind === "TACTICS" ? <ImpactNote match={data} tick={c.applied_tick ?? 0} side={you} /> : null}</li>)}</ol> : <p className="hint">Nenhuma alteração durante o jogo.</p>}
      </section>

      <section className="card"><h3>Estatísticas</h3><div className="stat-bars">{([["Posse", "possession", "%"], ["xG", "xg", ""], ["Finalizações", "shots", ""], ["No alvo", "shots_on_target", ""], ["Passes", "passes", ""], ["Precisão", "pass_accuracy", "%"], ["Escanteios", "corners", ""], ["Desarmes", "tackles", ""], ["Faltas", "fouls", ""], ["Cartões", "cards", ""]] as const).map(([label, key, unit]) => {
        const h = Number(stats[data.home]?.[key] ?? 0); const a = Number(stats[data.away]?.[key] ?? 0);
        return <div className="stat-bar" key={key}><b>{key === "xg" ? h.toFixed(2) : Math.round(h)}{unit}</b><span>{label}</span><b>{key === "xg" ? a.toFixed(2) : Math.round(a)}{unit}</b><div className="stat-bar__track" aria-hidden="true"><i style={{ width: `${(h / (h + a || 1)) * 100}%` }} className="home" /><i style={{ width: `${(a / (h + a || 1)) * 100}%` }} className="away" /></div></div>;
      })}</div></section>

      <section className="card"><h3>Notas dos jogadores</h3>{(["home", "away"] as const).map((side) => <div key={side} className={`ratings-team ${side === you ? "is-you" : ""}`}><h4><ClubCrest club={club(data[side])} size="sm" />{club(data[side]).name}</h4><ul className="ratings">{data.lineups[side].filter((p) => p.entered_tick !== null).sort((a, b) => b.rating - a.rating).map((p) => <li key={p.id}><span className="pos">{POSITION_LABEL[p.role]}</span><span>{p.name}{p.stats.goals ? ` ⚽${p.stats.goals > 1 ? `×${p.stats.goals}` : ""}` : ""}{p.stats.assists ? " 🅰" : ""}{p.sent_off ? " 🟥" : p.yellow_cards ? " 🟨" : ""}{p.entered_tick ? <small> ({Math.floor(p.entered_tick / 60)}′)</small> : null}</span><b className={tone(p.rating)}>{p.rating.toFixed(1)}</b></li>)}</ul></div>)}</section>

      <section className="card"><h3>Linha do tempo</h3><ol className="timeline">{keyEvents.map((e) => { const t = eventText(e, (code) => club(code).name); return <li key={e.event_id} className={`timeline__item tone-${t.tone} ${e.team === clubCode ? "is-own" : ""}`}><time>{e.minute}′</time><div><strong>{t.title}</strong>{t.detail && <span>{t.detail}</span>}</div></li>; })}</ol></section>
    </div>
    <div className="postmatch__actions"><button type="button" className="btn btn--primary btn--xl" onClick={onContinue}>Continuar carreira →</button></div>
  </section>;
}

function playerName(players: MatchPlayer[], id?: string) { return players.find((p) => p.id === id)?.name ?? "—"; }
function tone(value: number) { return value >= 7.5 ? "rating rating--great" : value >= 6.5 ? "rating rating--good" : value >= 5.8 ? "rating" : "rating rating--poor"; }

/** What happened after a tactical change: shots for and against in the following 15 minutes, from real events. */
function ImpactNote({ match, tick, side }: { match: LiveMatch; tick: number; side: "home" | "away" }) {
  const own = match[side];
  const after = match.events.filter((e) => e.kind === "SHOT" && e.tick > tick && e.tick <= tick + 900);
  const before = match.events.filter((e) => e.kind === "SHOT" && e.tick <= tick && e.tick > tick - 900);
  const count = (list: EngineEvent[], mine: boolean) => list.filter((e) => (e.team === own) === mine).length;
  return <small className="impact-note"> · 15′ antes: {count(before, true)}×{count(before, false)} finalizações · 15′ depois: {count(after, true)}×{count(after, false)}</small>;
}

function GoalReplay({ roomId, match, goal, onClose, clubName }: { roomId: string; match: LiveMatch; goal: EngineEvent; onClose: () => void; clubName: (code: string) => string }) {
  const start = Math.max(0, goal.tick - 18);
  const end = Math.min(5400, goal.tick + 4);
  const frames = useQuery({ queryKey: ["replay", roomId, match.id, start, end], queryFn: () => api.matchFrames(roomId, match.id, start, end).then((r) => r.data), staleTime: Infinity });
  const buffer = useMemo(() => new FrameBuffer(), []);
  const loaded = useRef(false);
  if (frames.data && !loaded.current) { buffer.push(frames.data.frames); loaded.current = true; }
  const tick = useRef(start);
  const driver = (delta: number) => { tick.current += (delta / 1000) * 6; if (tick.current > end + 2) tick.current = start; return tick.current; };
  const players = [...match.lineups.home.map((p) => ({ index: p.index, number: p.number, name: p.name, side: "home" as const, role: p.role })), ...match.lineups.away.map((p) => ({ index: p.index, number: p.number, name: p.name, side: "away" as const, role: p.role }))];
  return <section className="goal-replay" aria-label="Replay do gol"><header><b>{goal.minute}′ · {goal.player_name}</b><span>{clubName(goal.team ?? "")} · reconstruído pelo motor, em câmera lenta</span><button type="button" className="icon-btn" onClick={onClose} aria-label="Fechar replay">×</button></header>
    {frames.data ? <PitchCanvas buffer={buffer} driver={driver} players={players} kits={matchKits(match.home, match.away)} pitch={match.pitch} events={match.events.filter((e) => e.tick >= start && e.tick <= end)} homeCode={match.home} ownSide={match.you} label={`Replay do gol de ${goal.player_name}`} /> : <p className="panel-loading">{frames.error ? frames.error.message : "Reconstruindo o lance…"}</p>}
  </section>;
}
