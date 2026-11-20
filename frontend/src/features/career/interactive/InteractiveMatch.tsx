import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ApiError, api, type Club, type InteractiveActionType, type InteractiveFrame, type InteractiveStep, type InteractiveView } from "../../../lib/api";
import { ClubCrest } from "../../../components/ClubCrest";
import { inkOn, matchKits } from "../clubColors";
import { predictTarget, type Aim, type Geometry, toScreen, fromScreen, inferType } from "./gesture";
import "./interactive.css";

/**
 * Modo Jogável: the decisive moments of the coach's match.
 *
 * The server is the only authority (state, physics, timers, score). This screen polls
 * the state (a few bytes when nothing changed), plays the official physics frames of
 * each executed action, and turns a drag gesture into ONE action request: direction =
 * drag direction, power = drag length (relative to the pitch, so the same gesture
 * means the same intent at any resolution). The predicted line is a forecast only.
 */
const POLL_MS = 350;
const TYPE_LABEL: Record<InteractiveActionType, string> = { PASS: "Passe", LOFT: "Lançamento / cruzamento", CARRY: "Conduzir", SHOT: "Chute" };
const TYPE_KEYS: Record<string, InteractiveActionType | "AUTO"> = { "1": "AUTO", "2": "PASS", "3": "LOFT", "4": "CARRY", "5": "SHOT" };

type Pending = { aim: Aim; type: InteractiveActionType } | null;

function useInteractive(roomId: string) {
  const [view, setView] = useState<InteractiveView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const latest = useRef<InteractiveView | null>(null);
  const [offline, setOffline] = useState(false);
  const poll = useCallback(async (full = false) => {
    try {
      const known = full ? undefined : latest.current?.revision;
      const response = await api.interactive(roomId, known);
      const data = response.data;
      setOffset(data.server_now - Date.now() / 1000);
      setOffline(false);
      if (data.unchanged && latest.current) {
        const merged = { ...latest.current, minute: data.minute, server_now: data.server_now, connected: data.connected ?? latest.current.connected };
        latest.current = merged;
        setView(merged);
      } else {
        latest.current = data;
        setView(data);
      }
      setError(null);
    } catch (cause) {
      if (cause instanceof ApiError && cause.kind === "network") setOffline(true);
      else setError(cause instanceof Error ? cause.message : "Falha ao atualizar a partida.");
    }
  }, [roomId]);
  useEffect(() => {
    let alive = true;
    let timer = 0;
    const loop = async () => { await poll(); if (alive) timer = window.setTimeout(loop, POLL_MS); };
    void loop();
    // Coming back to the tab (or the network) = reconnecting: full authoritative state.
    const wake = () => { if (document.visibilityState === "visible") void poll(true); };
    document.addEventListener("visibilitychange", wake);
    window.addEventListener("online", wake);
    return () => { alive = false; window.clearTimeout(timer); document.removeEventListener("visibilitychange", wake); window.removeEventListener("online", wake); };
  }, [poll]);
  const replace = (data: InteractiveView) => { latest.current = data; setView(data); };
  return { view, error, offset, offline, refresh: () => poll(true), replace };
}

/** Which official frames are on screen now: the executing action, or the bot's replay sequence. */
function playback(view: InteractiveView, now: number): { frames: InteractiveFrame[]; t: number; step: InteractiveStep | null } | null {
  const opp = view.opportunity;
  if (!opp) return null;
  if (opp.replay && opp.replay.length) {
    let start = opp.replay[0].starts_at;
    for (const step of opp.replay) {
      const end = start + step.duration;
      if (now < end + 0.6 || step === opp.replay[opp.replay.length - 1]) return { frames: step.frames, t: Math.max(0, now - start), step };
      start = end + 0.6;
    }
  }
  if (opp.last && (view.state === "EXECUTING" || view.state === "OUTCOME")) return { frames: opp.last.frames, t: Math.max(0, now - opp.last.starts_at), step: opp.last };
  return null;
}

function sample(frames: InteractiveFrame[], t: number): InteractiveFrame {
  if (!frames.length) return [];
  if (t <= frames[0][0]) return frames[0];
  for (let i = 1; i < frames.length; i += 1) {
    if (frames[i][0] >= t) {
      const a = frames[i - 1], b = frames[i];
      const k = (t - a[0]) / Math.max(1e-6, b[0] - a[0]);
      return a.map((v, index) => v + (b[index] - v) * k);
    }
  }
  return frames[frames.length - 1];
}

export function InteractiveMatch({ roomId, clubCode, clubs }: { roomId: string; clubCode: string; clubs: Club[] }) {
  const { view, error, offset, offline, refresh, replace } = useInteractive(roomId);
  const canvas = useRef<HTMLCanvasElement | null>(null);
  const wrap = useRef<HTMLDivElement | null>(null);
  const [mode, setMode] = useState<InteractiveActionType | "AUTO">("AUTO");
  const [aim, setAim] = useState<Aim | null>(null);
  const [pending, setPending] = useState<Pending>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const drag = useRef<{ id: number; sx: number; sy: number } | null>(null);
  const viewRef = useRef(view);
  viewRef.current = view;
  const aimRef = useRef(aim);
  aimRef.current = aim;
  const geometry = useRef<Geometry>({ width: 1, height: 1, portrait: false, pad: 0 });
  const club = useCallback((code: string): Club => clubs.find((c) => c.code === code) ?? { code, name: code, sort_order: 0 }, [clubs]);
  const kits = useMemo(() => (view ? matchKits(view.home, view.away) : { home: "#fff", away: "#000" }), [view?.home, view?.away]); // eslint-disable-line react-hooks/exhaustive-deps

  const opp = view?.opportunity ?? null;
  const yourTurn = Boolean(view?.your_turn && view.state === "DECISION" && !pending);

  // --------------------------------------------------------------- drawing
  useEffect(() => {
    let raf = 0;
    const draw = () => {
      raf = requestAnimationFrame(draw);
      const element = canvas.current, box = wrap.current, current = viewRef.current;
      if (!element || !box || !current) return;
      const ratio = Math.min(2, window.devicePixelRatio || 1);
      const portrait = box.clientHeight > box.clientWidth * 1.1;
      const width = box.clientWidth, height = box.clientHeight;
      if (element.width !== Math.round(width * ratio) || element.height !== Math.round(height * ratio)) {
        element.width = Math.round(width * ratio); element.height = Math.round(height * ratio);
        element.style.width = `${width}px`; element.style.height = `${height}px`;
      }
      const g: Geometry = { width, height, portrait, pad: 14, ratio: current.pitch.length / current.pitch.width };
      geometry.current = g;
      const ctx = element.getContext("2d");
      if (!ctx) return;
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      drawPitch(ctx, g, current.pitch);
      const o = current.opportunity;
      if (!o) return;
      const now = Date.now() / 1000 + offset;
      const play = playback(current, now);
      let ball: [number, number, number] = [o.ball[0], o.ball[1], 0];
      let positions = o.positions;
      if (play && current.state !== "DECISION") {
        const frame = sample(play.frames, play.t);
        ball = [frame[1], frame[2], frame[3]];
        positions = o.roster.map((_, i) => [frame[4 + i * 2], frame[5 + i * 2]] as [number, number]);
      }
      const attackKit = o.attacking === current.home ? kits.home : kits.away;
      const defendKit = o.attacking === current.home ? kits.away : kits.home;
      // Trajectory preview (forecast, never a guarantee).
      const a = aimRef.current;
      if (a && current.state === "DECISION" && o.roster[carrierIndexOf(o)]) drawAim(ctx, g, current, positions[carrierIndexOf(o)], a);
      const unit = Math.max(7, Math.min(13, (portrait ? g.width : g.height) / 44));
      o.roster.forEach((p, i) => {
        const [x, y] = toScreen(g, positions[i][0], positions[i][1]);
        const keeper = p.role === "GK";
        const kit = p.team === "A" ? attackKit : defendKit;
        const fill = keeper ? (p.team === "A" ? "#F5B83D" : "#9B6BFF") : kit;
        ctx.beginPath(); ctx.fillStyle = "rgba(0,0,0,0.28)"; ctx.ellipse(x + 2, y + 3, unit, unit * 0.62, 0, 0, Math.PI * 2); ctx.fill();
        ctx.beginPath(); ctx.fillStyle = fill; ctx.arc(x, y, unit, 0, Math.PI * 2); ctx.fill();
        ctx.lineWidth = 2; ctx.strokeStyle = p.team === "A" ? "#FFFFFF" : "#0D1117"; ctx.stroke();
        if (p.id === o.carrier && current.state === "DECISION") {
          ctx.beginPath(); ctx.strokeStyle = "#B7F34B"; ctx.lineWidth = 3; ctx.arc(x, y, unit + 5 + Math.sin(now * 6) * 1.5, 0, Math.PI * 2); ctx.stroke();
        }
        ctx.fillStyle = inkOn(fill); ctx.font = `800 ${Math.round(unit * 0.95)}px "Barlow Condensed", "Arial Narrow", sans-serif`;
        ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(String(p.number || ""), x, y + 0.5);
        if (p.id === o.carrier && current.state === "DECISION") {
          ctx.font = `700 ${Math.round(unit * 0.9)}px Inter, sans-serif`; ctx.fillStyle = "#FFFFFF";
          ctx.fillText(p.name.split(" ").slice(-1)[0], x, y - unit - 9);
        }
      });
      const [bx, by] = toScreen(g, ball[0], ball[1]);
      const lift = Math.min(14, ball[2] * 3);
      const br = Math.max(4.5, unit * 0.48) * (1 + Math.min(0.5, ball[2] / 8));
      ctx.beginPath(); ctx.fillStyle = "rgba(0,0,0,0.35)"; ctx.ellipse(bx + lift * 0.5 + 1, by + lift + 2, br, br * 0.6, 0, 0, Math.PI * 2); ctx.fill();
      ctx.beginPath(); ctx.fillStyle = "rgba(255,255,255,0.25)"; ctx.arc(bx, by, br + 4, 0, Math.PI * 2); ctx.fill();
      ctx.beginPath(); ctx.fillStyle = "#FFFFFF"; ctx.arc(bx, by, br, 0, Math.PI * 2); ctx.fill();
      ctx.lineWidth = 1.6; ctx.strokeStyle = "#0D1117"; ctx.stroke();
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [offset, kits]);

  // --------------------------------------------------------------- gestures
  const carrierPos = (): [number, number] | null => {
    const v = viewRef.current;
    if (!v?.opportunity) return null;
    const i = carrierIndexOf(v.opportunity);
    return i >= 0 ? v.opportunity.positions[i] : null;
  };
  const updateAim = (clientX: number, clientY: number) => {
    const element = canvas.current, start = drag.current, v = viewRef.current, from = carrierPos();
    if (!element || !start || !v || !from) return;
    const rect = element.getBoundingClientRect();
    const g = geometry.current;
    const [nx0, ny0] = fromScreen(g, start.sx - rect.left, start.sy - rect.top);
    const [nx1, ny1] = fromScreen(g, clientX - rect.left, clientY - rect.top);
    // Drag vector in metres; power = drag length relative to 40% of the pitch length.
    const dx = (nx1 - nx0) * v.pitch.length, dy = (ny1 - ny0) * v.pitch.width;
    const length = Math.hypot(dx, dy);
    if (length < 1.2) { setAim(null); return; }
    const power = Math.max(0.05, Math.min(1, length / (v.pitch.length * 0.4)));
    const type = mode === "AUTO" ? inferType(v, from, dx / length, dy / length) : mode;
    setAim({ ux: dx / length, uy: dy / length, power, type: v.opportunity?.kind === "PENALTY" ? "SHOT" : type });
  };
  const onPointerDown = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (!yourTurn || drag.current) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = { id: event.pointerId, sx: event.clientX, sy: event.clientY };
    setAim(null);
  };
  const onPointerMove = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (drag.current?.id !== event.pointerId) return;
    updateAim(event.clientX, event.clientY);
  };
  const cancel = () => { drag.current = null; setAim(null); };
  const submit = async (chosen: Aim) => {
    const v = viewRef.current, from = carrierPos();
    if (!v?.opportunity || !from || pending) return;
    const target = predictTarget(v, from, chosen);
    setPending({ aim: chosen, type: chosen.type });
    setAim(null);
    try {
      const result = await api.interactiveAction(roomId, {
        action_id: crypto.randomUUID(), opportunity_id: v.opportunity.id, revision: v.revision, type: chosen.type,
        x: Math.max(-0.1, Math.min(1.1, target[0])), y: Math.max(-0.1, Math.min(1.1, target[1])), power: Math.round(chosen.power * 1000) / 1000,
      });
      replace(result.data.match);
      setFeedback(null);
    } catch (cause) {
      setFeedback(cause instanceof Error ? cause.message : "Ação recusada.");
      void refresh();
    } finally {
      setPending(null);
    }
  };
  const onPointerUp = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (drag.current?.id !== event.pointerId) return;
    updateAim(event.clientX, event.clientY);
    const chosen = aimRef.current;
    drag.current = null;
    if (!chosen || !yourTurn) { setAim(null); if (yourTurn) setFeedback("Arraste para indicar a direção e a força."); return; }
    void submit(chosen);
  };
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") cancel();
      const picked = TYPE_KEYS[event.key];
      if (picked) setMode(picked);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  // A new decision (or its end) clears any half-made gesture.
  useEffect(() => { cancel(); }, [view?.revision]);

  if (!view) return <div className="panel-loading" role="status">{error ?? "Entrando em campo…"}</div>;
  if (view.state === "NONE") return <div className="panel-loading" role="status">Aguardando a partida jogável…</div>;
  const now = Date.now() / 1000 + offset;
  const left = view.deadline ? Math.max(0, view.deadline - now) : null;
  const grace = view.grace_until ? Math.max(0, Math.ceil(view.grace_until - now)) : null;
  const attackingName = opp ? club(opp.attacking).name : "";
  const you = view.you;
  const spectator = !you;
  const rival = you ? (you === view.home ? view.away : view.home) : null;
  const rivalHuman = rival ? view.humans.includes(rival) : false;
  const rivalAway = rival && rivalHuman && view.connected[rival] === false;
  const step = playback(view, now)?.step ?? null;
  const banner = bannerText(view, clubCode, attackingName, step, left, grace, club);
  const lastGoal = [...view.events].reverse().find((e) => e.kind === "GOAL");

  return <section className="im" aria-label={`Modo Jogável: ${club(view.home).name} contra ${club(view.away).name}`}>
    <header className="im-bug">
      <div className={`im-bug__team ${you === view.home ? "is-you" : ""}`}><ClubCrest club={club(view.home)} size="sm" /><strong>{club(view.home).name}</strong><i style={{ background: kits.home }} /></div>
      <div className="im-bug__score"><b aria-live="polite">{view.score.home}<span>–</span>{view.score.away}</b><time>{view.state === "HALF_TIME" ? "INT" : view.state === "FINISHED" ? "FIM" : `${Math.min(90, Math.floor(view.minute))}′`}</time></div>
      <div className={`im-bug__team im-bug__team--away ${you === view.away ? "is-you" : ""}`}><i style={{ background: kits.away }} /><strong>{club(view.away).name}</strong><ClubCrest club={club(view.away)} size="sm" /></div>
    </header>

    <div className="im-stage">
      <div className="im-pitch" ref={wrap}>
        <canvas ref={canvas} className={yourTurn ? "is-live" : ""} aria-label={yourTurn ? "Campo: arraste a partir de qualquer ponto para escolher direção e força da jogada. Solte para executar. Esc cancela." : "Campo 2D da jogada"}
          onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={cancel} onLostPointerCapture={() => { if (drag.current) cancel(); }} />
        {banner && <div className={`im-banner im-banner--${banner.tone}`} role="status"><b>{banner.title}</b>{banner.detail && <span>{banner.detail}</span>}</div>}
        {left !== null && view.state === "DECISION" && <div className={`im-timer ${left < 3 ? "is-low" : ""}`} aria-label={`${Math.ceil(left)} segundos para decidir`}><svg viewBox="0 0 36 36" aria-hidden="true"><circle cx="18" cy="18" r="15" /><circle cx="18" cy="18" r="15" style={{ strokeDashoffset: 94.2 * (1 - left / view.decision_seconds) }} /></svg><b>{Math.ceil(left)}</b></div>}
        {aim && <div className="im-power" aria-hidden="true"><span>{TYPE_LABEL[aim.type]}</span><i><em style={{ width: `${Math.round(aim.power * 100)}%` }} /></i><b>{Math.round(aim.power * 100)}%</b></div>}
        {(offline || rivalAway) && <div className="im-banner im-banner--warn im-banner--bottom" role="status">{offline ? "Conexão perdida — reconectando… (sua jogada fica congelada por até 30 s)" : `O técnico do ${club(rival!).name} caiu. Aguardando reconexão (até 30 s); depois a IA assume os ataques dele.`}</div>}
        {lastGoal && view.state === "OUTCOME" && opp?.status === "GOAL" && <div className="im-goal" aria-hidden="true">GOL!</div>}
      </div>
      <aside className="im-side">
        {!spectator && <div className="im-modes" role="radiogroup" aria-label="Tipo de jogada">
          {(["AUTO", "PASS", "LOFT", "CARRY", "SHOT"] as const).map((key, index) => <button type="button" key={key} role="radio" aria-checked={mode === key} className={mode === key ? "is-active" : ""} onClick={() => setMode(key)} disabled={opp?.kind === "PENALTY" && key !== "SHOT" && key !== "AUTO"}><kbd>{index + 1}</kbd>{key === "AUTO" ? "Automático" : TYPE_LABEL[key]}</button>)}
        </div>}
        <p className="im-help">{spectator ? "Você está assistindo: seu clube não joga esta rodada." : "Arraste no campo: a direção do gesto é a direção da bola, o tamanho do gesto é a força. Solte para executar. A linha é uma previsão — o passe pode sair torto sob pressão, e a defesa e o goleiro reagem sozinhos."}</p>
        {feedback && <p className="im-feedback" role="alert">{feedback}</p>}
        {opp && <p className="im-opp"><b>{opp.label}</b> · {club(opp.attacking).name} ataca → · jogada {opp.actions}/{opp.max_actions}</p>}
        <ol className="im-events" aria-label="Lances">{[...view.events].reverse().slice(0, 12).map((e) => <li key={e.event_id} className={`im-ev im-ev--${e.kind.toLowerCase()}`}><b>{e.minute}′</b> {eventLabel(e.kind, e.outcome)} <span>{e.player_name ?? (e.kind === "CHANCE" ? club(e.team ?? "").name : "")}</span></li>)}</ol>
        {view.state === "FINISHED" && <p className="im-final">Fim de jogo. O resultado já está registrado; a rodada termina quando os outros jogos acabarem.</p>}
        {view.state === "HALF_TIME" && <p className="im-final">Intervalo. Ajuste táticas e escalação na próxima rodada; nesta partida o time segue o plano salvo.</p>}
        <dl className="im-stats">{statRow(view, "Chances", "chances")}{statRow(view, "Chutes", "shots")}{statRow(view, "No gol", "shots_on_target")}{statRow(view, "Passes certos", "passes_completed")}{statRow(view, "Defesas", "saves")}</dl>
      </aside>
    </div>
  </section>;
}

function carrierIndexOf(opp: NonNullable<InteractiveView["opportunity"]>): number {
  return opp.roster.findIndex((p) => p.id === opp.carrier);
}

function statRow(view: InteractiveView, label: string, key: string) {
  return <div key={key}><b>{view.stats[view.home]?.[key] ?? 0}</b><dt>{label}</dt><b>{view.stats[view.away]?.[key] ?? 0}</b></div>;
}

function eventLabel(kind: string, outcome: string): string {
  if (kind === "GOAL") return "⚽ GOL";
  if (kind === "SHOT") return outcome === "ON_TARGET" ? "Chute no gol" : outcome === "GOAL" ? "Finalização" : "Chute para fora";
  if (kind === "SAVE") return "🧤 Defesa";
  if (kind === "CHANCE") return "Oportunidade";
  if (kind === "INTERCEPTION") return "Interceptação";
  if (kind === "TACKLE") return "Desarme";
  if (kind === "CORNER") return "Escanteio";
  return kind;
}

function bannerText(view: InteractiveView, clubCode: string, attackingName: string, step: InteractiveStep | null, left: number | null, grace: number | null, club: (code: string) => Club):
  { title: string; detail?: string; tone: string } | null {
  const opp = view.opportunity;
  if (view.state === "CLOCK") return { title: `⏩ ${Math.floor(view.minute)}′`, detail: "Simulação rápida até o próximo momento decisivo", tone: "clock" };
  if (view.state === "HALF_TIME") return { title: "Intervalo", detail: `${view.score.home} × ${view.score.away}`, tone: "clock" };
  if (view.state === "FINISHED") return { title: "Fim de jogo", detail: `${club(view.home).name} ${view.score.home} × ${view.score.away} ${club(view.away).name}`, tone: "end" };
  if (!opp) return null;
  if (view.state === "DECISION") {
    if (grace !== null) return { title: opp.attacking === clubCode ? "Reconectado?" : "Técnico desconectado", detail: `Jogada congelada. A IA assume em ${grace}s se ele não voltar.`, tone: "warn" };
    if (view.your_turn) return { title: `${opp.label}: sua jogada!`, detail: left === null ? "Sem cronômetro" : undefined, tone: "you" };
    return { title: `${opp.label} do ${attackingName}`, detail: view.controller === "HUMAN" ? "O adversário está decidindo… a sua defesa é automática" : undefined, tone: "rival" };
  }
  if (view.state === "EXECUTING" || view.state === "REPLAY") {
    const by = step?.by === "TIMEOUT" ? "Tempo esgotado: a IA jogou por você · " : step?.by === "AI_TAKEOVER" || step?.by === "AI_CONTROL" ? "IA no controle · " : "";
    return { title: view.state === "REPLAY" ? `${opp.label} do ${attackingName}` : `${by}${step ? { PASS: "Passe", LOFT: "Bola longa", CARRY: "Condução", SHOT: "Chute!" }[step.type] : ""}`, tone: view.state === "REPLAY" ? "rival" : "play" };
  }
  if (view.state === "OUTCOME") return { title: opp.status === "GOAL" ? `GOL do ${attackingName}!` : (opp.result ?? "Fim da jogada"), tone: opp.status === "GOAL" ? "goal" : "end" };
  return null;
}

// ----------------------------------------------------------------- canvas helpers
function drawPitch(ctx: CanvasRenderingContext2D, g: Geometry, pitch: InteractiveView["pitch"]) {
  ctx.fillStyle = "#1f7a3a";
  ctx.fillRect(0, 0, g.width, g.height);
  const stripes = 12;
  for (let i = 0; i < stripes; i += 1) {
    if (i % 2) continue;
    const [x0, y0] = toScreen(g, i / stripes, 0), [x1, y1] = toScreen(g, (i + 1) / stripes, 1);
    ctx.fillStyle = "#238541";
    ctx.fillRect(Math.min(x0, x1), Math.min(y0, y1), Math.abs(x1 - x0), Math.abs(y1 - y0));
  }
  ctx.strokeStyle = "rgba(255,255,255,0.85)"; ctx.lineWidth = 2;
  const line = (points: [number, number][]) => { ctx.beginPath(); points.forEach(([x, y], i) => { const [sx, sy] = toScreen(g, x, y); if (i) ctx.lineTo(sx, sy); else ctx.moveTo(sx, sy); }); ctx.stroke(); };
  line([[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]);
  line([[0.5, 0], [0.5, 1]]);
  const [cx, cy] = toScreen(g, 0.5, 0.5);
  const [ex] = toScreen(g, 0.5 + 9.15 / pitch.length, 0.5);
  const [, ey] = toScreen(g, 0.5, 0.5 + 9.15 / pitch.width);
  ctx.beginPath(); ctx.arc(cx, cy, Math.max(Math.abs(ex - cx), Math.abs(ey - cy)), 0, Math.PI * 2); ctx.stroke();
  const bx = pitch.box / pitch.length, by = Math.min(0.48, (pitch.box + pitch.goal / 2 + 4) / pitch.width);
  const sx = (pitch.box / 2.75) / pitch.length, sy = (pitch.goal / 2 + 5.5) / pitch.width;
  for (const side of [0, 1]) {
    const x = side ? 1 : 0, dir = side ? -1 : 1;
    line([[x, 0.5 - by], [x + dir * bx, 0.5 - by], [x + dir * bx, 0.5 + by], [x, 0.5 + by]]);
    line([[x, 0.5 - sy], [x + dir * sx, 0.5 - sy], [x + dir * sx, 0.5 + sy], [x, 0.5 + sy]]);
    const gy = pitch.goal / 2 / pitch.width, depth = 1.6 / pitch.length;
    ctx.save(); ctx.strokeStyle = "#FFFFFF"; ctx.lineWidth = 3;
    line([[x, 0.5 - gy], [x - dir * depth, 0.5 - gy], [x - dir * depth, 0.5 + gy], [x, 0.5 + gy]]);
    ctx.restore();
  }
}

function drawAim(ctx: CanvasRenderingContext2D, g: Geometry, view: InteractiveView, from: [number, number], aim: Aim) {
  const target = predictTarget(view, from, aim);
  const [x0, y0] = toScreen(g, from[0], from[1]);
  const [x1, y1] = toScreen(g, target[0], target[1]);
  const color = aim.type === "SHOT" ? "#FF5A5F" : aim.type === "LOFT" ? "#7CC8FF" : aim.type === "CARRY" ? "#FFD166" : "#B7F34B";
  ctx.save();
  ctx.strokeStyle = color; ctx.lineWidth = 3; ctx.setLineDash(aim.type === "LOFT" ? [8, 7] : aim.type === "CARRY" ? [3, 5] : []);
  ctx.beginPath(); ctx.moveTo(x0, y0);
  if (aim.type === "LOFT") {
    const mx = (x0 + x1) / 2, my = (y0 + y1) / 2 - Math.hypot(x1 - x0, y1 - y0) * 0.25;
    ctx.quadraticCurveTo(mx, my, x1, y1);
  } else ctx.lineTo(x1, y1);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.beginPath(); ctx.fillStyle = color; ctx.globalAlpha = 0.25; ctx.arc(x1, y1, 12, 0, Math.PI * 2); ctx.fill();
  ctx.globalAlpha = 1; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(x1, y1, 6, 0, Math.PI * 2); ctx.stroke();
  ctx.restore();
}

