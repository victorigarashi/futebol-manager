import { LiveFormation } from "../../tactics/LiveFormation";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api, type Club, type CommandStatus, type EngineEvent, type LiveCommandPayload, type LiveMatch, type LiveView, type MatchPlayer, type Mentality, type PlayStyle, type Pressure } from "../../../lib/api";
import { ClubCrest } from "../../../components/ClubCrest";
import { StandingsTable } from "../../season/StandingsTable";
import { matchKits } from "../clubColors";
import { ATTRIBUTE_LABEL, KEY_EVENTS, PHASE_LABEL, POSITION_LABEL, eventText, newKey, tacticSummary } from "../labels";
import { GoalCelebrationOverlay, type GoalMoment } from "./GoalCelebrationOverlay";
import { markGoalsSeen, seenGoals } from "./seenGoals";
import { PitchCanvas, type CameraMode, type PitchPlayer, type RenderQuality } from "./PitchCanvas";
import { readLocal, writeLocal } from "../../../lib/storage";
import { sendOverSocket } from "../../../lib/socketBus";
import { DISPLAY_DELAY_SECONDS, type BroadcastView } from "./broadcastClock";
import { useFrameStream } from "./useFrameStream";
import { visibleCount } from "../../../lib/liveState";

const MENTALITIES: [Mentality, string][] = [["VERY_DEFENSIVE", "Muito def."], ["DEFENSIVE", "Defensiva"], ["BALANCED", "Equilibrada"], ["ATTACKING", "Ofensiva"], ["VERY_ATTACKING", "Muito of."]];
const PRESSURES: [Pressure, string][] = [["LOW", "Baixa"], ["MEDIUM", "Média"], ["HIGH", "Alta"]];
const STYLES: [PlayStyle, string][] = [["POSSESSION", "Posse"], ["COUNTER", "Contra-ataque"], ["DIRECT", "Direto"], ["SHORT_BUILDUP", "Saída curta"], ["WIDE", "Laterais"]];
type SideTab = "coach" | "stats" | "events" | "round";

export function LiveMatchCenter({ roomId, data, clubCode, clubs }: { roomId: string; data: LiveView; clubCode: string; clubs: Club[] }) {
  const match = data.match as LiveMatch;
  const clock = data.clock;
  const queryClient = useQueryClient();
  const club = useCallback((code: string): Club => clubs.find((item) => item.code === code) ?? { code, name: code, sort_order: 0 }, [clubs]);
  const you = match.you ?? (match.home === clubCode ? "home" : "away");
  const kits = useMemo(() => matchKits(match.home, match.away), [match.home, match.away]);
  const initial = useMemo(() => ({ segments: data.broadcast, serverNow: data.server_now }), [data.broadcast, data.server_now]);
  const { buffer, driver, view: playback, server, status } = useFrameStream(roomId, match.id, true, initial);
  // Rendering quality chosen on this device; the canvas adapts below it on its own.
  const [camera, setCamera] = useState<CameraMode>(() => (readLocal("bm_camera") as CameraMode | null) ?? "auto");
  useEffect(() => { writeLocal("bm_camera", camera); }, [camera]);
  const [quality, setQuality] = useState<RenderQuality>(() => (readLocal("bm_render_quality") as RenderQuality | null) ?? "standard");
  useEffect(() => { writeLocal("bm_render_quality", quality); }, [quality]);
  const render = useRef({ fps: 0, renderMs: 0, cap: 30 });
  const onStats = useCallback((stats: { fps: number; renderMs: number; cap: number }) => { render.current = stats; }, []);
  useEffect(() => {
    // Anonymous rendering health, aggregated by the server (helps tune the free plan).
    const timer = window.setInterval(() => {
      sendOverSocket({ type: "client.stats", fps: render.current.fps, render_ms: render.current.renderMs, delay_ms: Math.round(status.current.delayMs) });
    }, 10_000);
    return () => window.clearInterval(timer);
  }, [status]);

  // Scoreboard, clock and timeline follow the broadcast on screen (never the engine's lookahead).
  const [shown, setShown] = useState<BroadcastView>({ tick: 0, kind: "WAIT", label: "", cut: null });
  const [holder, setHolder] = useState<"home" | "away" | null>(null);
  const [lagging, setLagging] = useState(false);
  const [offline, setOffline] = useState(false);
  useEffect(() => {
    const homeCount = match.lineups.home.length;
    const timer = window.setInterval(() => {
      const current = playback.current;
      // Text follows the picture ~4x per second, and only re-renders when what it shows changes.
      setShown((previous) => Math.floor(previous.tick) === Math.floor(current.tick) && previous.kind === current.kind && previous.label === current.label
        && Math.round((previous.cut?.progress ?? -1) * 10) === Math.round((current.cut?.progress ?? -1) * 10) ? previous : { ...current });
      const owner = current.cut ? -1 : buffer.sample(current.tick)?.ball.owner ?? -1;
      setHolder(owner < 0 ? null : owner < homeCount ? "home" : "away");
      // Behind only when the screen has really run out of broadcast (not during a
      // half-time break or a cut, when the server legitimately sends no new frames).
      setLagging(status.current.starvedSeconds > 1.5);
      setOffline(!status.current.online);
    }, 250);
    return () => window.clearInterval(timer);
  }, [playback, buffer, status, match.lineups.home.length]);
  const displayTick = Math.max(0, Math.floor(shown.tick));
  // Events arrive in tick order: a binary search finds what is on screen (no filtering per update).
  const shownCount = visibleCount(match.events, displayTick);
  const shownEvents = useMemo(() => match.events.slice(0, shownCount), [match.events, shownCount]);
  // Substitutions and the rival's change of posture get on-screen feedback when they happen.
  const announced = useRef<Set<string> | null>(null);
  const [banner, setBanner] = useState<{ id: string; text: string; tone: string } | null>(null);
  useEffect(() => {
    if (announced.current === null) { announced.current = new Set(match.events.filter((e) => e.tick <= displayTick).map((e) => e.event_id)); return; }
    const fresh = shownEvents.filter((e) => (e.kind === "SUBSTITUTION" || e.kind === "TACTICS") && !announced.current!.has(e.event_id));
    fresh.forEach((e) => announced.current!.add(e.event_id));
    const latest = fresh[fresh.length - 1];
    if (!latest) return;
    const team = club(latest.team ?? match.home).name;
    setBanner(latest.kind === "SUBSTITUTION"
      ? { id: latest.event_id, tone: "sub", text: `🔁 ${team}: entra ${latest.player_name}, sai ${latest.secondary_player_name}` }
      : { id: latest.event_id, tone: "tactic", text: latest.team === clubCode ? `📋 Sua nova orientação está em campo (${latest.minute}′)` : `📋 ${team} mudou a postura em campo` });
  }, [shownEvents, displayTick, match.events, match.home, club, clubCode]);
  useEffect(() => { if (!banner) return; const timer = window.setTimeout(() => setBanner(null), 3500); return () => window.clearTimeout(timer); }, [banner]);
  const score = useMemo(() => {
    const goals = shownEvents.filter((event) => event.kind === "GOAL");
    return { home: goals.filter((event) => event.team === match.home).length, away: goals.filter((event) => event.team === match.away).length };
  }, [shownEvents, match.home, match.away]);

  // Goal celebrations: only for authoritative goals that appear after this screen opened.
  const seen = useRef<Set<string> | null>(null);
  const [goal, setGoal] = useState<GoalMoment | null>(null);
  useEffect(() => {
    if (seen.current === null) {
      seen.current = seenGoals();
      const existing = match.events.filter((event) => event.kind === "GOAL" && event.tick <= (clock?.tick ?? 0) - 45).map((event) => event.event_id);
      existing.forEach((id) => seen.current?.add(id));
      markGoalsSeen(existing);
    }
    const fresh = shownEvents.find((event) => event.kind === "GOAL" && !seen.current?.has(event.event_id));
    if (!fresh || goal) return;
    seen.current.add(fresh.event_id);
    markGoalsSeen([fresh.event_id]);
    setGoal({
      eventId: fresh.event_id, club: club(fresh.team ?? match.home), scorer: fresh.player_name ?? "Gol", assist: fresh.secondary_player_name,
      minute: fresh.minute, score: fresh.score ?? score, homeCode: match.home, awayCode: match.away, header: fresh.header, ownTeam: fresh.team === clubCode,
    });
  }, [shownEvents, goal, club, clock?.tick, clubCode, match.away, match.events, match.home, score]);
  const closeGoal = useCallback(() => setGoal(null), []);

  const players: PitchPlayer[] = useMemo(() => [
    ...match.lineups.home.map((p) => ({ index: p.index, number: p.number, name: p.name, side: "home" as const, role: p.role, id: p.id })),
    ...match.lineups.away.map((p) => ({ index: p.index, number: p.number, name: p.name, side: "away" as const, role: p.role, id: p.id })),
  ], [match.lineups]);
  const [selected, setSelected] = useState<number | null>(null);
  const selectedPlayer = [...match.lineups.home, ...match.lineups.away].find((p) => p.index === selected) ?? null;
  const selectedSide = selectedPlayer ? (match.lineups.home.includes(selectedPlayer) ? "home" : "away") : null;

  const [tab, setTab] = useState<SideTab>("coach");
  const [subOut, setSubOut] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const command = useMutation({
    mutationFn: (payload: LiveCommandPayload) => api.liveCommand(roomId, payload, newKey()),
    onSuccess: ({ data: result }) => {
      queryClient.setQueryData<LiveView>(["live", roomId], (previous) => previous ? { ...previous, match: result.match } : previous);
      const c = result.command;
      setFeedback(c.kind === "FORMATION" ? `Nova formação ${c.formation_code}: os jogadores já estão trocando de posição.` : c.kind === "SUBSTITUTION"
        ? c.status === "APPLIED" ? "Substituição feita." : "Substituição pedida: entra na próxima paralisação."
        : `Ordem enviada: entra em campo no próximo lance (${Math.floor((c.applied_tick ?? 0) / 60)}′).`);
      setSubOut(null);
    },
    onError: (error) => setFeedback(error instanceof Error ? error.message : "O servidor recusou o comando."),
  });

  // The phase follows what is on screen (the server clock is a second ahead of the picture).
  const serverPhase = clock?.phase ?? match.phase;
  const phase = serverPhase === "PRESENTATION" && shown.kind === "WAIT" ? "PRESENTATION"
    : shown.kind === "BREAK" && shown.label === "HALF_TIME" ? "HALF_TIME"
    : displayTick >= 5400 || serverPhase === "FULL_TIME" && shown.tick >= 5400 ? "FULL_TIME"
    : shown.kind === "WAIT" && serverPhase === "PRESENTATION" ? "PRESENTATION"
    : displayTick >= 2700 ? "SECOND_HALF" : "FIRST_HALF";
  const finished = phase === "FULL_TIME" || serverPhase === "FULL_TIME";
  // The coach's own latest order (it reaches the pitch at the next planned moment).
  const ownTactics = match.ordered_tactics ?? match.tactics[you];
  const lastOrder = [...(match.commands ?? [])].reverse().find((c) => c.kind === "TACTICS");
  const orderPending = lastOrder && (lastOrder.applied_tick ?? 0) > displayTick;
  const ownPlayers = match.lineups[you];
  const subs = match.substitutions[you];
  const pending = (match.commands ?? []).filter((c) => c.kind === "SUBSTITUTION" && c.status === "PENDING");
  const subsLeft = match.substitutions.max - subs.used - subs.pending;
  const minute = Math.min(90, Math.floor(displayTick / 60));
  const [, force] = useState(0);
  useEffect(() => { const timer = window.setInterval(() => force((v) => v + 1), 1000); return () => window.clearInterval(timer); }, []);
  // Countdowns are on the picture's clock: server time minus the display delay.
  const countdown = (target?: number | null) => Math.max(0, Math.ceil((target ?? 0) + DISPLAY_DELAY_SECONDS - server.now()));
  const duration = data.live_round?.match_seconds ?? clock?.match_seconds;
  const cutEvents = shown.cut ? match.events.filter((e) => e.tick > shown.cut!.from && e.tick <= shown.cut!.to && KEY_EVENTS.has(e.kind) && e.kind !== "TACTICS").slice(-3) : [];

  const statRows = useMemo(() => buildStatRows(match), [match]);

  const timeline = useMemo(() => shownEvents.filter((event) => KEY_EVENTS.has(event.kind)).reverse(), [shownEvents]);
  const clubName = useCallback((code: string) => club(code).name, [club]);
  const lastKey = timeline[0];

  return <section className="match-center" aria-label={`Partida ao vivo: ${clubName(match.home)} contra ${clubName(match.away)}`}>
    <header className="scorebug">
      <div className="scorebug__meta"><span>BRASILEIRÃO · RODADA {data.live_round?.round_number}{duration ? ` · JOGO DE ${Math.floor(duration / 60)}:${String(duration % 60).padStart(2, "0")}` : ""}</span><b className={`scorebug__status scorebug__status--${phase.toLowerCase()}`}>{phase === "FIRST_HALF" || phase === "SECOND_HALF" ? "● AO VIVO" : PHASE_LABEL[phase]}</b></div>
      <div className="scorebug__main">
        <div className={`scorebug__team ${you === "home" ? "is-you" : ""}`}><ClubCrest club={club(match.home)} /><strong>{clubName(match.home)}</strong>{you === "home" && <small>Você</small>}{holder === "home" && <i className="possession-dot" aria-label="com a bola" />}</div>
        <div className="scorebug__score"><strong aria-live="polite" aria-label={`Placar ${score.home} a ${score.away}`}>{score.home}<i>–</i>{score.away}</strong><time>{phase === "HALF_TIME" ? "INT" : phase === "PRESENTATION" ? "0′" : `${minute}′`}</time></div>
        <div className={`scorebug__team ${you === "away" ? "is-you" : ""}`}><ClubCrest club={club(match.away)} /><strong>{clubName(match.away)}</strong>{you === "away" && <small>Você</small>}{holder === "away" && <i className="possession-dot" aria-label="com a bola" />}</div>
      </div>
      <div className="scorebug__ticker" aria-label="Último lance">{lastKey ? <><b>{lastKey.minute}′</b> {eventText(lastKey, clubName).title} <span>{eventText(lastKey, clubName).detail}</span></> : <span>Aguardando o pontapé inicial</span>}</div>
    </header>

    <div className="match-center__grid">
      <div className="match-center__pitch">
        <PitchCanvas buffer={buffer} driver={driver} players={players} kits={kits} pitch={match.pitch} events={match.events} homeCode={match.home} ownSide={you} selectedIndex={selected} onSelect={setSelected} quality={quality} onStats={onStats} camera={camera}
          label={`Campo 2D: ${clubName(match.home)} (camisa ${kits.home}) ataca para a direita. Clique em um jogador para ver os detalhes.`} />
        {goal && <GoalCelebrationOverlay goal={goal} onDone={closeGoal} />}
        {shown.cut && !goal && <div className="pitch-cut" aria-live="polite"><span className="pitch-cut__clock">⏩ {Math.floor(shown.cut.from / 60)}′ <i>→</i> {Math.floor(shown.cut.to / 60)}′</span>{cutEvents.length > 0 && <ul>{cutEvents.map((e) => <li key={e.event_id}><b>{e.minute}′</b> {eventText(e, clubName).title}</li>)}</ul>}</div>}
        {banner && !goal && <div className={`pitch-banner pitch-banner--${banner.tone}`} role="status">{banner.text}</div>}
        {lagging && !finished && <div className="pitch-banner pitch-banner--warn" role="status">{offline ? "Conexão perdida — reconectando…" : "Aguardando o servidor — a transmissão continua em instantes…"}</div>}
        {phase === "PRESENTATION" && <div className="pitch-overlay pitch-overlay--intro"><p className="kicker">A BOLA VAI ROLAR</p><div className="intro-crests"><ClubCrest club={club(match.home)} size="md" /><b>×</b><ClubCrest club={club(match.away)} size="md" /></div><h2>{clubName(match.home)} × {clubName(match.away)}</h2><p>{match.formations.home} contra {match.formations.away} · Pontapé inicial em <strong>{countdown(clock?.kickoff_at)}s</strong></p><p className="muted">Você ainda pode ajustar a orientação do time no painel do técnico.</p></div>}
        {phase === "HALF_TIME" && <div className="pitch-overlay pitch-overlay--half"><p className="kicker">INTERVALO · {score.home} × {score.away}</p><h2>Hora da conversa no vestiário</h2><div className="half-stats">{statRows.slice(0, 4).map(([label, h, a]) => <div key={label}><b>{h}</b><span>{label}</span><b>{a}</b></div>)}</div><p>Substituições no intervalo <strong>não gastam janela</strong>. Segundo tempo em <strong>{countdown(clock?.halftime_ends_at)}s</strong>.</p></div>}
        <button type="button" className="btn btn--ghost pitch-camera" aria-pressed={camera === "auto"} onClick={() => setCamera(camera === "auto" ? "full" : "auto")}>{camera === "auto" ? "Câmera: dinâmica" : "Câmera: campo inteiro"}</button><label className="pitch-quality">Qualidade<select value={quality} onChange={(event) => setQuality(event.target.value as RenderQuality)}><option value="eco">Econômico (20 fps)</option><option value="standard">Padrão (30 fps)</option><option value="smooth">Fluido (até 60 fps)</option></select></label>
        <div className="pitch-legend" aria-hidden="true"><span><i style={{ background: kits.home }} />{match.home} ataca para a direita (no celular, para cima)</span><span><i style={{ background: kits.away }} />{match.away}</span></div>
      </div>

      <aside className="match-center__side">
        <nav className="seg-tabs" aria-label="Painéis da partida">{([["coach", "Técnico"], ["stats", "Estatísticas"], ["events", "Lances"], ["round", "Rodada"]] as const).map(([key, label]) => <button type="button" key={key} aria-pressed={tab === key} className={tab === key ? "is-active" : ""} onClick={() => setTab(key)}>{label}</button>)}</nav>
        {feedback && <p className="cm-toast" role="status">{feedback}</p>}

        {tab === "coach" && <div className="coach-panel">
          {ownTactics && <section className="coach-block"><h3>Orientação do time <small>{tacticSummary(ownTactics)}</small></h3>
            <TacticRow label="Mentalidade" options={MENTALITIES} value={ownTactics.mentality} disabled={finished || command.isPending} onPick={(mentality) => command.mutate({ kind: "TACTICS", mentality })} />
            <TacticRow label="Pressão" options={PRESSURES} value={ownTactics.pressure} disabled={finished || command.isPending} onPick={(pressure) => command.mutate({ kind: "TACTICS", pressure })} />
            <TacticRow label="Estilo" options={STYLES} value={ownTactics.style} disabled={finished || command.isPending} onPick={(style) => command.mutate({ kind: "TACTICS", style })} />
            <LiveFormation match={match} disabled={finished || command.isPending} onCommand={(payload) => command.mutate(payload)} />
            <p className="hint">{orderPending ? <><b>Ordem enviada.</b> Entra em campo no próximo lance ({Math.floor((lastOrder?.applied_tick ?? 0) / 60)}′).</> : "A ordem entra em campo no próximo lance. O adversário só percebe a nova postura em campo."}</p>
          </section>}
          <section className="coach-block"><h3>Substituições <small>{subs.used}/{match.substitutions.max}{match.substitutions.windows ? ` · janelas ${subs.windows_used}/${match.substitutions.windows}` : ""}</small></h3>
            {pending.map((c) => <p className="pending-sub" key={c.command_id}><span className="pulse" aria-hidden="true" />Aguardando paralisação: entra <b>{nameOf(ownPlayers, c.in_player_id)}</b>, sai <b>{nameOf(ownPlayers, c.out_player_id)}</b></p>)}
            {subsLeft <= 0 ? <p className="hint">Limite de substituições atingido.</p> : finished ? null : subOut === null
              ? <><p className="hint">Escolha quem sai. A troca acontece na próxima bola parada.</p><ul className="sub-list">{ownPlayers.filter((p) => p.on_pitch).map((p) => <li key={p.id}><button type="button" onClick={() => setSubOut(p.id)} disabled={pending.some((c) => c.out_player_id === p.id)}><span className="pos">{POSITION_LABEL[p.role] ?? p.role}</span><b>{p.number}. {p.name}</b><Stamina value={p.stamina} />{p.yellow_cards > 0 && <i className="card-dot" aria-label="Amarelado" />}</button></li>)}</ul></>
              : <SubstitutionPicker out={ownPlayers.find((p) => p.id === subOut)!} bench={ownPlayers.filter((p) => p.available && !pending.some((c) => c.in_player_id === p.id))} busy={command.isPending} onCancel={() => setSubOut(null)} onConfirm={(incoming) => command.mutate({ kind: "SUBSTITUTION", out_player_id: subOut, in_player_id: incoming })} />}
          </section>
          <CommandHistory commands={match.commands ?? []} players={ownPlayers} shownTick={displayTick} />
        </div>}

        {tab === "stats" && <section className="stat-bars" aria-label="Estatísticas ao vivo"><header><span>{match.home}</span><span>{match.away}</span></header>{statRows.map(([label, h, a, hv, av]) => <div className="stat-bar" key={label}><b>{h}</b><span>{label}</span><b>{a}</b><div className="stat-bar__track" aria-hidden="true"><i style={{ width: `${hv + av ? (hv / (hv + av)) * 100 : 50}%`, background: kits.home }} /><i style={{ width: `${hv + av ? (av / (hv + av)) * 100 : 50}%`, background: kits.away }} /></div></div>)}
          <h4>Destaques do seu time</h4><ul className="ratings">{[...ownPlayers].filter((p) => p.entered_tick !== null).sort((a, b) => b.rating - a.rating).slice(0, 5).map((p) => <li key={p.id}><span>{p.name}</span><b className={ratingTone(p.rating)}>{p.rating.toFixed(1)}</b></li>)}</ul>
        </section>}

        {tab === "events" && <EventTimeline events={timeline} clubName={clubName} clubCode={clubCode} />}

        {tab === "round" && <RoundPanel scores={data.scores} ownId={match.id} ownScore={score} table={data.table} baseline={data.official_table} clubCode={clubCode} />}

        {selectedPlayer && <PlayerCard player={selectedPlayer} own={selectedSide === you} club={clubName(selectedSide === "home" ? match.home : match.away)} onClose={() => setSelected(null)} onSubstitute={selectedSide === you && selectedPlayer.on_pitch && subsLeft > 0 && !finished ? () => { setTab("coach"); setSubOut(selectedPlayer.id); } : undefined} />}
      </aside>
    </div>
  </section>;
}

type StatRow = [string, string | number, string | number, number, number];
/** Statistics rows, rebuilt only when the match detail changes (not every display update). */
function buildStatRows(match: LiveMatch): StatRow[] {
  const stats = match.statistics;
  return [
    ["Posse de bola", `${Math.round(stats[match.home]?.possession ?? 50)}%`, `${Math.round(stats[match.away]?.possession ?? 50)}%`, stats[match.home]?.possession ?? 50, stats[match.away]?.possession ?? 50],
    ["Gols esperados (xG)", match.home_xg.toFixed(2), match.away_xg.toFixed(2), match.home_xg, match.away_xg],
    ...(["shots", "shots_on_target", "passes", "pass_accuracy", "corners", "tackles", "fouls", "yellow_cards", "distance"] as const).map((key) => {
      const label = { shots: "Finalizações", shots_on_target: "No alvo", passes: "Passes", pass_accuracy: "Precisão de passe", corners: "Escanteios", tackles: "Desarmes", fouls: "Faltas", yellow_cards: "Amarelos", distance: "Distância (km)" }[key];
      const h = stats[match.home]?.[key] ?? 0; const a = stats[match.away]?.[key] ?? 0;
      return [label, key === "pass_accuracy" ? `${h}%` : h, key === "pass_accuracy" ? `${a}%` : a, h, a] as [string, string | number, string | number, number, number];
    }),
  ];
}

function nameOf(players: MatchPlayer[], id?: string) { return players.find((p) => p.id === id)?.name ?? "—"; }
function ratingTone(value: number) { return value >= 7.5 ? "rating rating--great" : value >= 6.5 ? "rating rating--good" : value >= 5.8 ? "rating" : "rating rating--poor"; }

function TacticRow<T extends string>({ label, options, value, disabled, onPick }: { label: string; options: [T, string][]; value: T; disabled: boolean; onPick: (value: T) => void }) {
  return <fieldset className="tactic-row"><legend>{label}</legend><div>{options.map(([code, name]) => <button type="button" key={code} aria-pressed={value === code} className={value === code ? "is-active" : ""} disabled={disabled || value === code} onClick={() => onPick(code)}>{name}</button>)}</div></fieldset>;
}

function Stamina({ value }: { value: number }) {
  const percent = Math.round(value * 100);
  return <span className={`stamina ${percent < 60 ? "is-low" : percent < 75 ? "is-mid" : ""}`} aria-label={`Condição física ${percent}%`}><i><b style={{ width: `${percent}%` }} /></i><em>{percent}</em></span>;
}

function SubstitutionPicker({ out, bench, busy, onCancel, onConfirm }: { out: MatchPlayer; bench: MatchPlayer[]; busy: boolean; onCancel: () => void; onConfirm: (id: string) => void }) {
  const [choice, setChoice] = useState<string | null>(null);
  const incoming = bench.find((p) => p.id === choice);
  const keys = out.role === "GK" ? ["keeping", "physical", "passing"] : ["pace", "passing", "shooting", "dribbling", "defending", "physical"];
  return <div className="sub-picker">
    <p className="sub-picker__out">Sai <b>{out.name}</b> <span className="pos">{POSITION_LABEL[out.role]}</span> <Stamina value={out.stamina} /></p>
    {bench.length === 0 ? <p className="hint">Nenhum reserva disponível.</p> : <ul className="sub-list">{bench.map((p) => <li key={p.id}><button type="button" aria-pressed={choice === p.id} className={choice === p.id ? "is-active" : ""} onClick={() => setChoice(p.id)}><span className="pos">{POSITION_LABEL[p.position] ?? p.position}</span><b>{p.name}</b><span className="ovr">{p.overall}</span>{p.position !== out.role && <small className="warn">improvisado em {POSITION_LABEL[out.role]}</small>}</button></li>)}</ul>}
    {incoming && <table className="compare"><caption>Comparação</caption><thead><tr><th scope="col">Atributo</th><th scope="col">{out.name.split(" ")[0]}</th><th scope="col">{incoming.name.split(" ")[0]}</th></tr></thead><tbody><tr><th scope="row">Overall</th><td>{out.overall}</td><td className={incoming.overall >= out.overall ? "up" : "down"}>{incoming.overall}</td></tr><tr><th scope="row">Condição</th><td>{Math.round(out.stamina * 100)}%</td><td className="up">100%</td></tr>{keys.map((key) => <tr key={key}><th scope="row">{ATTRIBUTE_LABEL[key]}</th><td>{out.attributes[key]}</td><td className={incoming.attributes[key] >= out.attributes[key] ? "up" : "down"}>{incoming.attributes[key]}</td></tr>)}</tbody></table>}
    <div className="sub-picker__actions"><button type="button" className="btn btn--ghost" onClick={onCancel}>Voltar</button><button type="button" className="btn btn--primary" disabled={!choice || busy} onClick={() => choice && onConfirm(choice)}>{busy ? "Enviando…" : "Confirmar substituição"}</button></div>
  </div>;
}

function CommandHistory({ commands, players, shownTick }: { commands: CommandStatus[]; players: MatchPlayer[]; shownTick: number }) {
  if (!commands.length) return null;
  const label = (c: CommandStatus) => c.status === "REJECTED" ? ["rejected", "Recusada"] : c.status === "PENDING" ? ["pending", "Pendente"] : (c.applied_tick ?? 0) > shownTick ? ["pending", "Agendada"] : ["applied", "Aplicada"];
  return <section className="coach-block"><h3>Suas decisões</h3><ol className="decisions">{[...commands].reverse().slice(0, 6).map((c) => <li key={c.command_id}><span className={`badge badge--${label(c)[0]}`}>{label(c)[1]}</span>{c.kind === "TACTICS" && c.tactics ? tacticSummary(c.tactics) : `Entra ${nameOf(players, c.in_player_id)}, sai ${nameOf(players, c.out_player_id)}`}{c.applied_tick !== undefined && <small> · {Math.floor(c.applied_tick / 60)}′</small>}{c.reason && <small> · {c.reason}</small>}</li>)}</ol></section>;
}

const EventTimeline = memo(function EventTimeline({ events, clubName, clubCode }: { events: EngineEvent[]; clubName: (code: string) => string; clubCode: string }) {
  return <ol className="timeline" aria-label="Linha do tempo">{events.length ? events.map((event) => <TimelineItem key={event.event_id} event={event} clubName={clubName} own={event.team === clubCode} />) : <li className="muted">Os lances aparecem aqui assim que acontecem.</li>}</ol>;
});

const RoundPanel = memo(function RoundPanel({ scores, ownId, ownScore, table, baseline, clubCode }: { scores: LiveView["scores"]; ownId: string; ownScore: { home: number; away: number }; table: LiveView["table"]; baseline: LiveView["official_table"]; clubCode: string }) {
  return <section className="round-panel"><h3>Placar da rodada</h3><ul className="round-scores">{scores.map((s) => <li key={s.id} className={s.id === ownId ? "is-own" : ""}><span>{s.home}</span><b>{s.id === ownId ? `${ownScore.home} × ${ownScore.away}` : `${s.home_goals} × ${s.away_goals}`}</b><span>{s.away}</span></li>)}</ul><h3>Classificação ao vivo</h3><StandingsTable rows={table} baseline={baseline} ownClub={clubCode} live /></section>;
});

function TimelineItem({ event, clubName, own }: { event: EngineEvent; clubName: (code: string) => string; own: boolean }) {
  const text = eventText(event, clubName);
  return <li className={`timeline__item tone-${text.tone} ${own ? "is-own" : ""}`}><time>{event.minute}′</time><div><strong>{text.title}</strong>{text.detail && <span>{text.detail}</span>}</div></li>;
}

function PlayerCard({ player, own, club, onClose, onSubstitute }: { player: MatchPlayer; own: boolean; club: string; onClose: () => void; onSubstitute?: () => void }) {
  const s = player.stats;
  return <section className="player-card" aria-label={`Jogador selecionado: ${player.name}`}>
    <header><div><span className="pos">{POSITION_LABEL[player.role] ?? player.role}</span><h3>{player.number}. {player.name}</h3><small>{club}{player.sent_off ? " · expulso" : player.on_pitch ? "" : " · fora de campo"}</small></div><b className={ratingTone(player.rating)}>{player.rating ? player.rating.toFixed(1) : "—"}</b><button type="button" className="icon-btn" onClick={onClose} aria-label="Fechar">×</button></header>
    {own && <Stamina value={player.stamina} />}
    <dl className="mini-stats"><div><dt>Gols</dt><dd>{s.goals}</dd></div><div><dt>Assist.</dt><dd>{s.assists}</dd></div><div><dt>Passes</dt><dd>{s.passes_completed}/{s.passes}</dd></div><div><dt>Finaliz.</dt><dd>{s.shots}</dd></div><div><dt>Desarmes</dt><dd>{s.tackles + s.interceptions}</dd></div><div><dt>Distância</dt><dd>{(s.distance / 1000).toFixed(1)} km</dd></div></dl>
    {onSubstitute && <button type="button" className="btn btn--ghost btn--block" onClick={onSubstitute}>Substituir este jogador</button>}
  </section>;
}
