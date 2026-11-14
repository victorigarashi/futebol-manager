import { useEffect, useRef, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";

import { api, type MatchReplay } from "../../lib/api";
import { ClubCrest } from "../../components/ClubCrest";
import { ballAt, playerPositionsAt, pressureBuckets, REPLAY_DURATION, serverReplayTime } from "./replay";

const LABELS: Record<string, string> = {
  MATCH_START: "Bola rolando", MATCH_END: "Fim de jogo", GOAL: "Gol!", SHOT: "Finalização",
  PASS: "Passe", RECEPTION: "Domínio", INTERCEPTION: "Interceptação", TACKLE: "Desarme",
  SAVE: "Defesa", CARD: "Cartão amarelo", FOUL: "Falta", CORNER: "Escanteio",
  CARRY: "Avanço", RESTART: "Bola em jogo", POSSESSION: "Construção da jogada", PENALTY: "Pênalti",
};

export function MatchReplayView({ match, serverNow, roundNumber, detailsNavigation }: {
  match: MatchReplay; serverNow?: number; roundNumber?: number; detailsNavigation?: ReactNode;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const timeRef = useRef(0);
  const playingRef = useRef(true);
  const speedRef = useRef(1);
  const [playing, setPlaying] = useState(true);
  const [speed, setSpeed] = useState(1);
  const [elapsed, setElapsed] = useState(0);
  const clubs = useQuery({ queryKey: ["clubs"], queryFn: () => api.clubs().then((result) => result.data) });
  const live = match.status === "LIVE";
  const duration = Math.max(REPLAY_DURATION, match.events.at(-1)?.animation_ms ?? 0);

  useEffect(() => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d");
    if (!canvas || !context) return;
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const styles = getComputedStyle(canvas);
    const color = (name: string) => styles.getPropertyValue(name).trim();
    const colors = [color("--match-home"), color("--match-away")];
    let lastPaint = 0;
    let frame = 0;
    let last = performance.now();
    const receivedAt = last;
    let lastReadout = 0;
    const draw = (now: number) => {
      const delta = Math.min(100, now - last);
      last = now;
      if (live && match.started_at !== undefined && serverNow !== undefined) {
        timeRef.current = serverReplayTime(match.started_at, serverNow, now - receivedAt);
      } else if (playingRef.current) {
        timeRef.current = Math.min(duration, timeRef.current + delta * speedRef.current);
      }
      if (now - lastReadout > 100) { setElapsed(timeRef.current); lastReadout = now; }
      if (reducedMotion && now - lastPaint < 250) { frame = requestAnimationFrame(draw); return; }
      lastPaint = now;
      const width = canvas.clientWidth;
      const height = canvas.clientHeight;
      const ratio = window.devicePixelRatio || 1;
      if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
        canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio);
      }
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      context.clearRect(0, 0, width, height);
      const inset = Math.max(10, Math.round(Math.min(width, height) * .035));
      const fieldWidth = width - inset * 2;
      const fieldHeight = height - inset * 2;
      const px = (x: number) => inset + x * fieldWidth;
      const py = (y: number) => inset + y * fieldHeight;
      context.fillStyle = color("--pitch"); context.fillRect(0, 0, width, height);
      for (let stripe = 0; stripe < 12; stripe += 2) {
        context.fillStyle = color("--pitch-stripe"); context.fillRect(inset + stripe * fieldWidth / 12, inset, fieldWidth / 12, fieldHeight);
      }
      context.strokeStyle = color("--pitch-line"); context.lineWidth = Math.max(1, width / 520);
      context.strokeRect(inset, inset, fieldWidth, fieldHeight);
      context.beginPath(); context.moveTo(px(.5), py(0)); context.lineTo(px(.5), py(1)); context.stroke();
      context.beginPath(); context.arc(px(.5), py(.5), Math.min(fieldWidth, fieldHeight) * .12, 0, Math.PI * 2); context.stroke();
      context.beginPath(); context.arc(px(.5), py(.5), 2, 0, Math.PI * 2); context.fillStyle = color("--pitch-line"); context.fill();
      const boxTop = .27; const boxHeight = .46; const goalBoxTop = .39; const goalBoxHeight = .22;
      context.strokeRect(px(0), py(boxTop), fieldWidth * .15, fieldHeight * boxHeight);
      context.strokeRect(px(.85), py(boxTop), fieldWidth * .15, fieldHeight * boxHeight);
      context.strokeRect(px(0), py(goalBoxTop), fieldWidth * .055, fieldHeight * goalBoxHeight);
      context.strokeRect(px(.945), py(goalBoxTop), fieldWidth * .055, fieldHeight * goalBoxHeight);
      context.beginPath(); context.arc(px(.105), py(.5), 2, 0, Math.PI * 2); context.fill();
      context.beginPath(); context.arc(px(.895), py(.5), 2, 0, Math.PI * 2); context.fill();
      context.strokeRect(px(-.018), py(.42), fieldWidth * .018, fieldHeight * .16);
      context.strokeRect(px(1), py(.42), fieldWidth * .018, fieldHeight * .16);
      // A short rendering delay interpolates only between already released events.
      const ball = ballAt(match.events, Math.max(0, timeRef.current - (live ? 180 : 0)));
      if (reducedMotion && ball.event) { ball.x = ball.event.x; ball.y = ball.event.y; }
      for (const [side, team, ids, formation] of [["home", match.home, match.home_players, match.home_formation], ["away", match.away, match.away_players, match.away_formation]] as const) {
        const players = playerPositionsAt(match.events, timeRef.current, team, ids, formation?.players, side);
        players.forEach((player) => {
          const radius = width < 430 ? 8 : 11;
          const centerX = px(player.x); const centerY = py(player.y);
          context.beginPath(); context.fillStyle = colors[side === "home" ? 0 : 1];
          context.arc(centerX, centerY, radius, 0, Math.PI * 2); context.fill();
          context.strokeStyle = player.hasBall ? color("--lime") : color("--field-bg"); context.lineWidth = player.hasBall ? 3 : 1.5; context.stroke();
          context.fillStyle = color("--field-bg"); context.font = `bold ${width < 430 ? 8 : 9}px sans-serif`;
          context.textAlign = "center"; context.textBaseline = "middle"; context.fillText(String(player.number), centerX, centerY);
          if (player.hasBall) { context.beginPath(); context.strokeStyle = color("--lime"); context.lineWidth = 1.5; context.arc(centerX, centerY, radius + 5, 0, Math.PI * 2); context.stroke(); }
        });
      }
      context.beginPath(); context.fillStyle = color("--paper"); context.strokeStyle = color("--field-bg"); context.lineWidth = 1;
      context.arc(px(ball.x), py(ball.y), width < 430 ? 4 : 5, 0, Math.PI * 2); context.fill(); context.stroke();
      if (!live && timeRef.current >= duration && playingRef.current) { playingRef.current = false; setPlaying(false); }
      frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }, [duration, live, match, serverNow]);

  const setPlayback = (value: boolean) => { playingRef.current = value; setPlaying(value); };
  const jumpTo = (value: number) => { timeRef.current = value; setElapsed(value); };
  const visibleEvents = match.events.filter((event) => event.animation_ms <= elapsed);
  const currentEvent = visibleEvents.at(-1);
  const pressure = pressureBuckets(visibleEvents, match.home);
  const maxPressure = Math.max(3, ...pressure.flatMap((bucket) => [bucket.home, bucket.away]));
  const byTeam = match.statistics;
  const possessions = (byTeam[match.home]?.possession ?? 0) + (byTeam[match.away]?.possession ?? 0);
  const homePossession = possessions ? Math.round((byTeam[match.home]?.possession ?? 0) / possessions * 100) : 50;
  const timeline = visibleEvents.filter((event) => ["GOAL", "SHOT", "SAVE", "FOUL", "CARD", "CORNER", "MATCH_START", "MATCH_END", "PENALTY"].includes(event.kind)).reverse();
  const team = (code: string) => clubs.data?.find((club) => club.code === code) ?? { code, name: code, sort_order: 0 };
  return <section className={`match-replay ${live ? "match-replay--live" : ""}`} aria-label={`${live ? "Ao vivo" : "Replay"}: ${team(match.home).name} contra ${team(match.away).name}`}>
    <header className="live-scoreboard">
      <div className="live-scoreboard__meta"><span>BRASILEIRÃO MANAGER {roundNumber ? ` / RODADA ${roundNumber}` : " / REPLAY OFICIAL"}</span><b className={live ? "live-badge" : ""}>{live ? "● AO VIVO" : "ENCERRADA"}</b></div>
      <div className="live-scoreboard__teams"><div className="live-team"><ClubCrest club={team(match.home)} /><strong>{team(match.home).name}</strong><small>MANDANTE</small></div><div className="live-scoreboard__result"><strong aria-label={`Placar ${match.home_goals} a ${match.away_goals}`}>{match.home_goals}<i>:</i>{match.away_goals}</strong><time>{Math.min(90, Math.floor(elapsed / 1000))}′</time></div><div className="live-team"><ClubCrest club={team(match.away)} /><strong>{team(match.away).name}</strong><small>VISITANTE</small></div></div>
    </header>
    <div className="match-watch-grid">
      <div className="match-watch-field"><div className="match-field-caption"><span>VISÃO DO TÉCNICO</span><span>{match.home_formation?.code ?? ""} <i>×</i> {match.away_formation?.code ?? ""}</span></div><canvas ref={canvasRef} className="match-replay__pitch" aria-label="Campo 2D da partida do seu clube. Os lances também estão disponíveis na linha do tempo.">Seu navegador não oferece canvas. Acompanhe os mesmos lances no fluxo da partida.</canvas><div className="match-current-event" role={currentEvent?.kind === "GOAL" ? "status" : undefined}><b>{currentEvent?.minute ?? 0}′</b><span>{LABELS[currentEvent?.kind ?? "MATCH_START"] ?? currentEvent?.kind}</span><small>{currentEvent?.player_name ?? currentEvent?.team}</small></div>
        {!live && <div className="match-replay__controls"><button type="button" onClick={() => setPlayback(!playing)}>{playing ? "Pausar" : "Reproduzir"}</button>{[1, 2, 4].map((value) => <button className={speed === value ? "is-active" : ""} type="button" key={value} onClick={() => { speedRef.current = value; setSpeed(value); }}>{value}×</button>)}<button type="button" onClick={() => { jumpTo(0); setPlayback(true); }}>Reiniciar</button>{match.events.filter((event) => event.kind === "GOAL").map((goal) => <button type="button" key={goal.event_id} onClick={() => { jumpTo(goal.animation_ms); setPlayback(false); }}>Gol · {goal.minute}′</button>)}</div>}
        {detailsNavigation}
        <section className="live-pressure"><h3>Pressão ofensiva <small>{match.home} <i>/</i> {match.away}</small></h3><svg viewBox="0 0 600 100" role="img" aria-label={`Pressão ofensiva por períodos de três minutos: ${match.home} acima, ${match.away} abaixo`}><line x1="0" y1="50" x2="600" y2="50" stroke="var(--line)" />{pressure.map((bucket, index) => <g key={index}><rect x={index * 20 + 2} y={50 - bucket.home / maxPressure * 43} width="14" height={bucket.home / maxPressure * 43} fill="var(--match-home)" /><rect x={index * 20 + 2} y="51" width="14" height={bucket.away / maxPressure * 43} fill="var(--match-away)" /></g>)}</svg><div><span>0′</span><span>30′</span><span>60′</span><span>90′</span></div></section>
      </div>
      <aside className="match-watch-flow"><section id="live-statistics" className="live-statistics"><h3>Estatísticas {live ? "ao vivo" : "da partida"}</h3>{([["Posse de bola", `${homePossession}%`, `${100 - homePossession}%`], ["Finalizações", byTeam[match.home]?.shots ?? 0, byTeam[match.away]?.shots ?? 0], ["No alvo", byTeam[match.home]?.shots_on_target ?? 0, byTeam[match.away]?.shots_on_target ?? 0], ["Passes", byTeam[match.home]?.passes ?? 0, byTeam[match.away]?.passes ?? 0], ["Escanteios", byTeam[match.home]?.corners ?? 0, byTeam[match.away]?.corners ?? 0], ["Cartões", byTeam[match.home]?.cards ?? 0, byTeam[match.away]?.cards ?? 0], ["Gols esperados", match.home_xg.toFixed(2), match.away_xg.toFixed(2)]] as const).map(([label, home, away]) => <div key={label}><b>{home}</b><span>{label}</span><b>{away}</b></div>)}</section><section id="live-timeline" className="live-timeline"><h3>Fluxo da partida <small>{timeline.length} lances</small></h3><ol>{timeline.map((event) => <li key={event.event_id} className={event.kind === "GOAL" ? "is-goal" : ""}><time>{event.minute}′</time><div><strong>{event.kind === "GOAL" ? "⚽ " : event.kind === "CARD" ? "▨ " : ""}{LABELS[event.kind] ?? event.kind}</strong><small>{event.player_name ?? event.team ?? "Árbitro"}</small></div><b>{event.team}</b></li>)}</ol></section></aside>
    </div>
  </section>;
}
