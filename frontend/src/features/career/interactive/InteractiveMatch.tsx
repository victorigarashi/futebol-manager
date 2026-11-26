import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ApiError, type Club, type InteractiveActionType, type InteractiveView } from "../../../lib/api";
import { ClubCrest } from "../../../components/ClubCrest";
import { clubColors, matchKits } from "../clubColors";
import { aimFromDrag, attackDir, fromScreen, predictTarget, toScreen, type Aim, type Geometry } from "./gesture";
import { adjustPower, aimAtMate, initialAim, mates, POWER_STEP, retype, rotateAim } from "./keyboardAim";
import { roomSource, type MatchSource } from "./source";
import { buildScene, crossedCues, type Scene } from "./render/presentation";
import { drawScene2D, geometryFor, playRegion, type Kit, type Overlay } from "./render/renderer2d";
import type { Region } from "./gesture";
import { readLocal, writeLocal } from "../../../lib/storage";
import type { Renderer3D } from "./render/renderer3d";
import { autoQuality, readExperience, readFpsCap, readQuality, readShadows, writeExperience, writeFpsCap, writeQuality, writeShadows, type Experience, type QualityChoice } from "./render/preference";
import { cyclePreset, normalizeCamera, presetSettings, readCameraSettings, writeCameraSettings, PRESET_LABEL, type CameraSettings } from "./render/cameraPresets";
import { CameraPanel } from "./CameraPanel";
import { matchSound } from "./sound";
import "./interactive.css";

/**
 * Modo Jogável — the decisive moments of a match, drawn by the coach's own choice of
 * renderer (2D Arcade or 3D Imersivo). The server is the only authority (state, physics,
 * timers, score): both renderers draw the same official frames through the shared
 * presentation layer, and both turn a drag into the same intent (direction and power in
 * pitch metres) and send ONE action. The predicted line is a forecast only.
 */
const POLL_MS = 350;
const TYPE_LABEL: Record<InteractiveActionType, string> = { PASS: "Passe", LOFT: "Lançamento / cruzamento", CARRY: "Conduzir", SHOT: "Chute" };
const TYPE_ICON: Record<InteractiveActionType | "AUTO", string> = { AUTO: "✦", PASS: "➜", LOFT: "⤴", CARRY: "⇢", SHOT: "◎" };
/** Only events that do NOT end the move get a toast: the end of a move is explained once, by the outcome banner. */
const CUE_LABEL: Record<string, [string, string]> = {
  BLOCK: ["Bloqueado!", "bad"], POST: ["Na trave!", "wood"], BAR: ["No travessão!", "wood"], HEADER: ["Cabeçada!", "good"], DRIBBLE: ["Passou pelo marcador!", "good"],
};
const TYPE_KEYS: Record<string, InteractiveActionType | "AUTO"> = { "1": "AUTO", "2": "PASS", "3": "LOFT", "4": "CARRY", "5": "SHOT" };
const NO_OVERLAY: Overlay = { aim: null, aimValid: true, carrierIndex: -1, receivers: new Set(), yourTurn: true, pending: null, now: 0, label: false, quality: "high" };

function useInteractive(source: MatchSource) {
  const [view, setView] = useState<InteractiveView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const latest = useRef<InteractiveView | null>(null);
  const [offline, setOffline] = useState(false);
  const poll = useCallback(async (full = false) => {
    try {
      const data = await source.fetch(full ? undefined : latest.current?.revision);
      setOffset(data.server_now - Date.now() / 1000);
      setOffline(false);
      if (data.unchanged && latest.current) {
        const merged = { ...latest.current, minute: data.minute, server_now: data.server_now, connected: data.connected ?? latest.current.connected };
        latest.current = merged; setView(merged);
      } else { latest.current = data; setView(data); }
      setError(null);
    } catch (cause) {
      if (cause instanceof ApiError && cause.kind === "network") setOffline(true);
      else setError(cause instanceof Error ? cause.message : "Falha ao atualizar a partida.");
    }
  }, [source]);
  useEffect(() => {
    let alive = true, timer = 0;
    const loop = async () => { await poll(); if (alive) timer = window.setTimeout(loop, POLL_MS); };
    void loop();
    const wake = () => { if (document.visibilityState === "visible") void poll(true); };
    document.addEventListener("visibilitychange", wake);
    window.addEventListener("online", wake);
    return () => { alive = false; window.clearTimeout(timer); document.removeEventListener("visibilitychange", wake); window.removeEventListener("online", wake); };
  }, [poll]);
  const replace = (data: InteractiveView) => { latest.current = data; setView(data); };
  return { view, error, offset, offline, refresh: () => poll(true), replace };
}

/** The match's official kits (server selection); a local fallback only for an old server. */
function teamKits(view: InteractiveView): { home: Kit; away: Kit } {
  const k = view.kits;
  if (k) {
    const kit = (m: typeof k.home): Kit => ({ shirt: m.shirt, shorts: m.shorts, socks: m.socks, trim: m.trim, number: m.number, pattern: m.pattern });
    return { home: { ...kit(k.home), gk: kit(k.home_gk) }, away: { ...kit(k.away), gk: kit(k.away_gk) } };
  }
  const local = matchKits(view.home, view.away);
  const one = (code: string, shirt: string): Kit => { const c = clubColors(code); const second = shirt.toLowerCase() === c.primary.toLowerCase() ? c.secondary : c.primary; return { shirt, shorts: second, socks: shirt, trim: second }; };
  return { home: one(view.home, local.home), away: one(view.away, local.away) };
}

export function InteractiveMatch({ roomId, clubCode, clubs, source: given, onExit }: { roomId: string; clubCode: string; clubs: Club[]; source?: MatchSource; onExit?: () => void }) {
  const source = useMemo(() => given ?? roomSource(roomId), [given, roomId]);
  const { view, error, offset, offline, refresh, replace } = useInteractive(source);
  const root = useRef<HTMLElement | null>(null);
  const stage = useRef<HTMLDivElement | null>(null);
  const canvas2d = useRef<HTMLCanvasElement | null>(null);
  const host3d = useRef<HTMLDivElement | null>(null);
  const r3d = useRef<Renderer3D | null>(null);
  const [experience, setExperienceState] = useState<Experience>(readExperience);
  const [qualityChoice, setQualityChoice] = useState<QualityChoice>(readQuality);
  const [r3dStatus, setR3dStatus] = useState<"off" | "loading" | "ready">("off");
  const [notice, setNotice] = useState<string | null>(null);
  const [mode, setMode] = useState<InteractiveActionType | "AUTO">("AUTO");
  const [aim, setAim] = useState<Aim | null>(null);
  const [pending, setPending] = useState<Aim | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [panel, setPanel] = useState(false);
  const [soundOpen, setSoundOpen] = useState(false);
  const [sound, setSound] = useState(matchSound.settings);
  const [camera, setCameraState] = useState<CameraSettings>(readCameraSettings);
  const [cameraOpen, setCameraOpen] = useState(false);
  const [shadows, setShadows] = useState(readShadows);
  const [fpsCap, setFpsCap] = useState<0 | 30 | 60 | 120>(readFpsCap);
  const [cam2d, setCam2d] = useState<"play" | "full">(() => (readLocal("bm_cam2d") === "full" ? "full" : "play"));
  const cam2dRef = useRef(cam2d); cam2dRef.current = cam2d;
  const fpsCapRef = useRef(fpsCap); fpsCapRef.current = fpsCap;
  const regionRef = useRef<Region | null>(null);
  const [toast, setToast] = useState<{ text: string; tone: string; id: number } | null>(null);
  const [celebration, setCelebration] = useState<{ name: string; club: string; until: number } | null>(null);
  const drag = useRef<{ id: number; start: [number, number] } | null>(null);
  const viewRef = useRef(view); viewRef.current = view;
  const aimRef = useRef(aim); aimRef.current = aim;
  const pendingRef = useRef(pending); pendingRef.current = pending;
  const receiversRef = useRef<Set<string>>(new Set());
  const geometry = useRef<Geometry>({ width: 1, height: 1, portrait: false, pad: 0 });
  const sceneRef = useRef<Scene | null>(null);
  const sentKick = useRef(false);
  const club = useCallback((code: string): Club => clubs.find((c) => c.code === code) ?? { code, name: code, sort_order: 0 }, [clubs]);
  const kitsKey = view ? `${view.home}|${view.away}|${JSON.stringify(view.kits ?? null)}` : "";
  const kits = useMemo(() => (viewRef.current ? teamKits(viewRef.current) : null), [kitsKey]); // eslint-disable-line react-hooks/exhaustive-deps
  const opp = view?.opportunity ?? null;
  const yourTurn = Boolean(view?.your_turn && view.state === "DECISION" && !pending);
  const yourTurnRef = useRef(yourTurn); yourTurnRef.current = yourTurn;

  const setExperience = (value: Experience, persist = true) => { setExperienceState(value); if (persist) writeExperience(value); };
  // Camera changes apply at once and are saved in this browser only (never sent to the server).
  const changeCamera = (next: CameraSettings) => {
    const safe = normalizeCamera(next);
    setCameraState(safe);
    writeCameraSettings(safe);
  };

  // Immersive: no page scroll (and no league chrome) behind the match.
  useEffect(() => { document.body.classList.add("im-open"); return () => document.body.classList.remove("im-open"); }, []);

  // --------------------------------------------------------------- 3D: loaded on demand, with a safe fallback
  useEffect(() => {
    if (experience !== "3D") { setR3dStatus("off"); return; }
    let cancelled = false;
    setR3dStatus("loading");
    import("./render/renderer3d").then(({ Renderer3D: R, webglAvailable }) => {
      if (cancelled) return;
      if (!webglAvailable()) throw new Error("WebGL indisponível");
      const quality = qualityChoice === "auto" ? autoQuality() : qualityChoice;
      const renderer = new R(quality);
      renderer.setCamera(camera);
      renderer.setShadows(shadows);
      host3d.current?.append(renderer.canvas, renderer.overlay);
      r3d.current = renderer;
      setR3dStatus("ready");
    }).catch(() => {
      if (cancelled) return;
      setNotice("O 3D não está disponível neste dispositivo — mostrando a partida em 2D.");
      setExperience("2D", false);
    });
    return () => {
      cancelled = true;
      const renderer = r3d.current;
      r3d.current = null;
      if (renderer) { renderer.canvas.remove(); renderer.overlay.remove(); renderer.dispose(); }
    };
  }, [experience]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (r3d.current && qualityChoice !== "auto") r3d.current.setQuality(qualityChoice); writeQuality(qualityChoice); }, [qualityChoice]);
  useEffect(() => { r3d.current?.setCamera(camera); }, [camera, r3dStatus]);
  useEffect(() => { r3d.current?.setShadows(shadows); writeShadows(shadows); }, [shadows, r3dStatus]);
  useEffect(() => { writeFpsCap(fpsCap); }, [fpsCap]);

  // --------------------------------------------------------------- frame loop (no React render per frame)
  useEffect(() => {
    let raf = 0;
    let lastStep = "", lastT = 0, lastState = "", lastFrame = performance.now(), slowSince = 0;
    let frames: number[] = [];
    let diagLast = performance.now(), diagFrames = 0, diagCpu = 0;
    const diag = (() => { try { return window.location.hash.startsWith("#lab") && localStorage.getItem("bm_lab_diag") === "1"; } catch { return false; } })();
    const diagEl = diag ? Object.assign(document.createElement("div"), { className: "im-diag" }) : null;
    if (diagEl) stage.current?.append(diagEl);
    let lastPaint = 0;
    const draw = () => {
      raf = requestAnimationFrame(draw);
      // Optional frame-rate cap (presentation only; the official state keeps its own clock).
      const minInterval = fpsCapRef.current ? 1000 / fpsCapRef.current : 0;
      const paintedAt = performance.now();
      if (minInterval && paintedAt - lastPaint < minInterval - 1) return;
      lastPaint = paintedAt;
      const box = stage.current, current = viewRef.current;
      if (!box || !current) return;
      const cpu0 = performance.now();
      if (diagEl) {
        // Lab diagnostics (never in public matches): FPS, CPU per frame, measured foot sliding.
        diagFrames += 1;
        if (cpu0 - diagLast > 1000) {
          const r = r3d.current as unknown as { footSlide?: number } | null;
          diagEl.textContent = `${current.engine ?? "v6"} · ${r ? "3D" : "2D"} · ${Math.round(diagFrames * 1000 / (cpu0 - diagLast))} FPS · CPU ${(diagCpu / Math.max(1, diagFrames)).toFixed(1)} ms/quadro`
            + (r?.footSlide ? ` · deslize dos pés ${r.footSlide.toFixed(0)} cm/s` : "") + ` · rev ${current.revision}`;
          diagLast = cpu0; diagFrames = 0; diagCpu = 0;
        }
        queueMicrotask(() => { diagCpu += performance.now() - cpu0; });
      }
      const width = box.clientWidth, height = box.clientHeight;
      const now = Date.now() / 1000 + offset;
      const scene = buildScene(current, now);
      sceneRef.current = scene;
      const o = current.opportunity;
      const carrierIndex = o ? o.roster.findIndex((p) => p.id === o.carrier) : -1;
      const attackHome = o ? o.attacking === current.home : true;
      const both = kits ?? teamKits(current);
      const kitA = attackHome ? both.home : both.away;
      const kitD = attackHome ? both.away : both.home;
      const a = aimRef.current;
      const overlay: Overlay = {
        aim: a, aimValid: Boolean(a && aimValid(current, a)), carrierIndex, receivers: receiversRef.current,
        yourTurn: yourTurnRef.current, pending: pendingRef.current, now, label: !a && !pendingRef.current && current.state === "DECISION", quality: "high",
      };
      // Sounds and one-shot effects from the official cues crossed since the last frame.
      const step = scene?.step ?? null;
      if (step && scene) {
        const key = `${step.starts_at}:${step.carrier}:${step.type}`;
        const from = key === lastStep ? lastT : -0.01;
        for (const cue of crossedCues(step, from, scene.t)) {
          if (cue.kind === "KICK") { if (sentKick.current && step.by === "HUMAN") sentKick.current = false; else if (cue.action === "PASS") matchSound.pass(); else matchSound.kick(cue.power ?? 0.6); }
          else if (cue.kind === "POST" || cue.kind === "BAR") matchSound.post();
          else if (cue.kind === "SAVE") matchSound.save();
          else if (cue.kind === "TACKLE" || cue.kind === "INTERCEPT" || cue.kind === "BLOCK") matchSound.tackle();
          else if (cue.kind === "HEADER") matchSound.pass();
          const label = cue.kind === "SAVE" && !cue.hold ? ["Defesa! Bola viva", "save"] as [string, string] : CUE_LABEL[cue.kind];
          if (label) setToast({ text: label[0], tone: label[1], id: Date.now() });
          else if (cue.kind === "GOAL") {
            matchSound.goal();
            const shooter = o?.roster.find((p) => p.id === (step.shooter ?? cue.id));
            if (o) setCelebration({ name: shooter?.name ?? "", club: o.attacking, until: now + 2.4 });
          }
        }
        lastStep = key; lastT = scene.t;
      }
      if (current.state !== lastState) {
        if (current.state === "HALF_TIME") matchSound.whistle(2);
        else if (current.state === "FINISHED") matchSound.whistle(3);
        else if (lastState === "HALF_TIME") matchSound.whistle(1);
        if (current.state === "DECISION" && current.your_turn) matchSound.swell(0.25, 0.8);
        lastState = current.state;
      }
      const renderer = r3d.current;
      if (renderer?.lost) { setNotice("O contexto gráfico 3D foi perdido — a partida continua em 2D."); setExperience("2D", false); return; }
      if (renderer) {
        // The renderer may finish loading before the stage exists (first poll): attach it here.
        if (host3d.current && renderer.canvas.parentElement !== host3d.current) host3d.current.append(renderer.canvas, renderer.overlay);
        if (renderer.canvas.style.width !== `${width}px` || renderer.canvas.style.height !== `${height}px`) renderer.resize(width, height);
        renderer.render(current, scene, { attack: kitA, defend: kitD }, overlay, now);
        // Adaptive quality first, then a safe 2D fallback (same match, same timer: only the drawing changes).
        const t = performance.now(); frames.push(t - lastFrame); lastFrame = t;
        if (frames.length > 120) frames.shift();
        const avg = frames.reduce((x, y) => x + y, 0) / frames.length;
        if (frames.length >= 120 && avg > 42 && document.visibilityState === "visible") {
          if (!slowSince) slowSince = t;
          if (t - slowSince > 4000) {
            slowSince = 0; frames = [];
            if (renderer.quality !== "low") renderer.setQuality(renderer.quality === "high" ? "medium" : "low");
            else { setNotice("O 3D ficou lento neste dispositivo — mudamos para o 2D. Você pode voltar ao 3D no botão do topo."); setExperience("2D", false); }
          }
        } else slowSince = 0;
        return;
      }
      const element = canvas2d.current;
      if (!element) return;
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      if (element.width !== Math.round(width * dpr) || element.height !== Math.round(height * dpr)) {
        element.width = Math.round(width * dpr); element.height = Math.round(height * dpr);
        element.style.width = `${width}px`; element.style.height = `${height}px`;
      }
      // 2D camera: smooth follow of the attack, frozen while a gesture is being drawn.
      let region: Region | undefined;
      if (cam2dRef.current === "play" && scene) {
        const want = playRegion(current, scene.ball.x, scene.ball.y, width, height);
        const prev = regionRef.current;
        if (drag.current && prev) region = prev;
        else if (!prev || Math.abs(prev.x1 - prev.x0 - (want.x1 - want.x0)) > 1e-6 || Math.abs(prev.y1 - prev.y0 - (want.y1 - want.y0)) > 1e-6) region = want;
        else { const k = 0.08; region = { x0: prev.x0 + (want.x0 - prev.x0) * k, x1: prev.x1 + (want.x1 - prev.x1) * k, y0: prev.y0 + (want.y0 - prev.y0) * k, y1: prev.y1 + (want.y1 - prev.y1) * k }; }
        regionRef.current = region;
      } else regionRef.current = null;
      const g = geometryFor(width, height, current, region);
      geometry.current = g;
      const ctx = element.getContext("2d");
      if (!ctx) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      drawScene2D(ctx, g, dpr, current, scene, { attack: kitA, defend: kitD }, overlay);
    };
    raf = requestAnimationFrame(draw);
    return () => { cancelAnimationFrame(raf); diagEl?.remove(); };
  }, [offset, kits, r3dStatus]);

  // Lab-only playtest hook (#lab): lets the automated playtest drag from real screen points.
  // Read-only: it exposes the official view and the projection, never a way to change the state.
  useEffect(() => {
    let flag = false;
    try { flag = localStorage.getItem("bm_playtest") === "1"; } catch { /* optional */ }
    if (!window.location.hash.startsWith("#lab") && !flag) return;
    const w = window as unknown as { __bmMatch?: unknown };
    w.__bmMatch = {
      view: () => viewRef.current,
      experience: () => (r3d.current && !r3d.current.lost ? "3D" : "2D"),
      toClient: (nx: number, ny: number): [number, number] | null => {
        const renderer = r3d.current;
        if (renderer && !renderer.lost) return renderer.clientOf(nx, ny);
        const element = canvas2d.current;
        if (!element) return null;
        const rect = element.getBoundingClientRect();
        const [sx, sy] = toScreen(geometry.current, nx, ny);
        return [rect.left + sx, rect.top + sy];
      },
    };
    return () => { delete w.__bmMatch; };
  }, []);

  // --------------------------------------------------------------- gestures (same intent in 2D and 3D)
  const pick = (clientX: number, clientY: number): [number, number] | null => {
    const renderer = r3d.current;
    if (renderer && !renderer.lost) return renderer.pick(clientX, clientY);
    const element = canvas2d.current;
    if (!element) return null;
    const rect = element.getBoundingClientRect();
    return fromScreen(geometry.current, clientX - rect.left, clientY - rect.top);
  };
  const carrierPos = (): [number, number] | null => {
    const v = viewRef.current;
    if (!v?.opportunity) return null;
    const i = v.opportunity.roster.findIndex((p) => p.id === v.opportunity!.carrier);
    return i >= 0 ? v.opportunity.positions[i] : null;
  };
  const updateAim = (clientX: number, clientY: number) => {
    const start = drag.current, v = viewRef.current, from = carrierPos();
    if (!start || !v || !from) return;
    const end = pick(clientX, clientY);
    if (!end) return;
    const next = aimFromDrag(v, from, start.start, end, mode);
    aimRef.current = next;
    setAim(next);
    receiversRef.current = next ? receiversFor(v, from, next) : new Set();
  };
  const onPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    matchSound.unlock();
    if (!yourTurn || drag.current) return;
    const v = viewRef.current;
    if (r3d.current && v) { r3d.current.settle(v, sceneRef.current, NO_OVERLAY); r3d.current.freeze(true); }
    const start = pick(event.clientX, event.clientY);
    if (!start) { r3d.current?.freeze(false); return; }
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = { id: event.pointerId, start };
    setAim(null);
  };
  const onPointerMove = (event: React.PointerEvent<HTMLDivElement>) => { if (drag.current?.id === event.pointerId) updateAim(event.clientX, event.clientY); };
  const cancel = () => { drag.current = null; setAim(null); receiversRef.current = new Set(); r3d.current?.freeze(false); };
  const submit = async (chosen: Aim) => {
    const v = viewRef.current, from = carrierPos();
    if (!v?.opportunity || !from || pendingRef.current) return;
    const target = predictTarget(v, from, chosen);
    setPending(chosen);
    setAim(null);
    // Immediate feedback that the gesture was taken — never the result (only the server knows it).
    if (chosen.type !== "CARRY") { if (chosen.type === "PASS") matchSound.pass(); else matchSound.kick(chosen.power); sentKick.current = true; }
    try { navigator.vibrate?.(12); } catch { /* optional */ }
    try {
      const result = await source.act({
        action_id: crypto.randomUUID(), opportunity_id: v.opportunity.id, revision: v.revision, type: chosen.type,
        x: Math.max(-0.1, Math.min(1.1, target[0])), y: Math.max(-0.1, Math.min(1.1, target[1])), power: Math.round(chosen.power * 1000) / 1000,
      });
      replace(result.match);
      setFeedback(null);
    } catch (cause) {
      sentKick.current = false;
      setFeedback(cause instanceof Error ? cause.message : "Ação recusada.");
      void refresh();
    } finally {
      setPending(null);
      r3d.current?.freeze(false);
    }
  };
  const onPointerUp = (event: React.PointerEvent<HTMLDivElement>) => {
    if (drag.current?.id !== event.pointerId) return;
    updateAim(event.clientX, event.clientY);
    const chosen = aimRef.current;
    drag.current = null;
    receiversRef.current = new Set();
    if (!chosen || !yourTurn) { setAim(null); r3d.current?.freeze(false); if (yourTurn) setFeedback("Arraste mais longe para indicar a direção e a força."); return; }
    // The decision timer already ran out here: the server has (or is about to have) the AI's
    // choice — say so instead of sending a gesture that can only be refused.
    const dl = viewRef.current?.deadline;
    if (dl && Date.now() / 1000 + offset > dl - 0.05) { setAim(null); r3d.current?.freeze(false); setFeedback("Tempo esgotado: a IA decidiu esta jogada."); void refresh(); return; }
    void submit(chosen);
  };
  // Keyboard play (no mouse needed): arrows aim, Tab picks a team-mate, Enter/Space plays.
  // The handler lives in a ref so it always sees the current view, aim and mode.
  const mateIndex = useRef(-1);
  const keyHandler = useRef<(event: KeyboardEvent) => void>(() => {});
  keyHandler.current = (event: KeyboardEvent) => {
    matchSound.unlock();
    const target = event.target as HTMLElement | null;
    if (target && (target.tagName === "INPUT" || target.tagName === "SELECT" || target.tagName === "TEXTAREA" || target.isContentEditable)) return;
    if (event.key === "Escape") { cancel(); setCelebration(null); mateIndex.current = -1; return; }
    const v = viewRef.current, from = carrierPos();
    const turn = yourTurnRef.current && !!v?.opportunity && !!from && !pendingRef.current;
    const picked = TYPE_KEYS[event.key];
    if (picked) {
      setMode(picked);
      if (turn && aimRef.current) setAim(retype(v!, from!, aimRef.current, picked));
      return;
    }
    if (!turn || drag.current) return;
    const keys = ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Tab", "Enter", " "];
    if (!keys.includes(event.key)) return;
    event.preventDefault();
    if (!aimRef.current && r3d.current) { r3d.current.settle(v!, sceneRef.current, NO_OVERLAY); r3d.current.freeze(true); }
    if (event.key === "Enter" || event.key === " ") {
      const chosen = aimRef.current;
      if (!chosen) { const first = initialAim(v!, from!, mode); setAim(first); receiversRef.current = receiversFor(v!, from!, first); return; }
      const dl = v!.deadline;
      if (dl && Date.now() / 1000 + offset > dl - 0.05) { setAim(null); r3d.current?.freeze(false); setFeedback("Tempo esgotado: a IA decidiu esta jogada."); void refresh(); return; }
      mateIndex.current = -1;
      receiversRef.current = new Set();
      void submit(chosen);
      return;
    }
    let next = aimRef.current ?? initialAim(v!, from!, mode);
    if (event.key === "ArrowLeft") next = rotateAim(v!, from!, next, -1, mode);
    else if (event.key === "ArrowRight") next = rotateAim(v!, from!, next, 1, mode);
    else if (event.key === "ArrowUp") next = adjustPower(v!, from!, next, POWER_STEP, mode);
    else if (event.key === "ArrowDown") next = adjustPower(v!, from!, next, -POWER_STEP, mode);
    else if (event.key === "Tab") {
      const list = mates(v!, from!);
      if (list.length) {
        mateIndex.current = ((mateIndex.current + (event.shiftKey ? -1 : 1)) % list.length + list.length) % list.length;
        next = aimAtMate(v!, from!, list[mateIndex.current].at, mode);
      }
    }
    setAim(next);
    receiversRef.current = receiversFor(v!, from!, next);
  };
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => keyHandler.current(event);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  useEffect(() => { if (!drag.current) { setAim(null); receiversRef.current = new Set(); } }, [view?.revision]);
  useEffect(() => { if (!toast) return; const id = window.setTimeout(() => setToast(null), 1300); return () => window.clearTimeout(id); }, [toast]);
  useEffect(() => { if (!feedback) return; const id = window.setTimeout(() => setFeedback(null), 4000); return () => window.clearTimeout(id); }, [feedback]);
  useEffect(() => { if (!celebration) return; const id = window.setTimeout(() => setCelebration(null), 2400); return () => window.clearTimeout(id); }, [celebration]);
  useEffect(() => { if (!notice) return; const id = window.setTimeout(() => setNotice(null), 7000); return () => window.clearTimeout(id); }, [notice]);

  const toggleFullscreen = () => {
    const element = root.current;
    if (!element) return;
    if (document.fullscreenElement) void document.exitFullscreen?.();
    else void element.requestFullscreen?.().catch(() => setNotice("Tela cheia indisponível neste navegador."));
  };

  if (!view) return <section className="im im--loading" ref={root}><div className="panel-loading" role="status">{error ?? "Entrando em campo…"}</div></section>;
  if (view.state === "NONE") return <section className="im im--loading" ref={root}><div className="panel-loading" role="status">Aguardando a partida jogável…</div></section>;
  const now = Date.now() / 1000 + offset;
  const left = view.deadline ? Math.max(0, view.deadline - now) : null;
  const grace = view.grace_until ? Math.max(0, Math.ceil(view.grace_until - now)) : null;
  const attackingName = opp ? club(opp.attacking).name : "";
  const you = view.you;
  const spectator = !you;
  const rival = you ? (you === view.home ? view.away : view.home) : null;
  const rivalAway = rival && view.humans.includes(rival) && view.connected[rival] === false;
  const banner = bannerText(view, attackingName, left, grace, club);
  const right = view.attacks_right ?? {};
  const half = view.half ?? (view.minute >= 45 ? 2 : 1);
  void clubCode;

  return <section className={`im im--${experience.toLowerCase()}`} ref={root} aria-label={`Modo Jogável: ${club(view.home).name} contra ${club(view.away).name}`}>
    <div className="im-stage" ref={stage}>
      <canvas ref={canvas2d} className="im-canvas" hidden={r3dStatus === "ready"} aria-hidden="true" />
      <div className="im-3d" ref={host3d} hidden={r3dStatus !== "ready"} aria-hidden="true" />
      <div className={`im-input ${yourTurn ? "is-live" : ""}`} role="application" aria-label={yourTurn ? "Campo: arraste para escolher direção e força da jogada; solte para executar. Esc cancela. Teclas 1 a 5 escolhem o tipo." : "Campo da partida"}
        onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={cancel} onLostPointerCapture={() => { if (drag.current) cancel(); }} />

      <header className="im-bug">
        <div className={`im-bug__team ${you === view.home ? "is-you" : ""}`}><ClubCrest club={club(view.home)} size="sm" /><abbr title={club(view.home).name}>{view.home}</abbr><i className={`im-dir ${right[view.home] ? "is-right" : "is-left"}`} title={right[view.home] ? "ataca para a direita" : "ataca para a esquerda"} /></div>
        <b className="im-bug__score" aria-live="polite">{view.score.home}<span>:</span>{view.score.away}</b>
        <div className={`im-bug__team im-bug__team--away ${you === view.away ? "is-you" : ""}`}><i className={`im-dir ${right[view.away] ? "is-right" : "is-left"}`} title={right[view.away] ? "ataca para a direita" : "ataca para a esquerda"} /><abbr title={club(view.away).name}>{view.away}</abbr><ClubCrest club={club(view.away)} size="sm" /></div>
        <time className="im-bug__clock">{view.state === "HALF_TIME" ? "INT" : view.state === "FINISHED" ? "FIM" : `${Math.min(90, Math.floor(view.minute))}′`}<small>{half}ºT</small></time>
        {view.duration?.mode === "LIMITED" && view.duration.limit_at && view.state !== "FINISHED" && <span className={`im-limit ${view.duration.limit_reached ? "is-over" : ""}`} title={`Duração da partida: ${Math.round(view.duration.seconds / 60 * 10) / 10} min (definida na sala). Ao esgotar, nenhum lance novo começa; a IA conclui o lance em andamento.`}>
          ⏱ {view.duration.limit_reached ? "0:00" : clockText(Math.max(0, view.duration.limit_at - now))}</span>}
      </header>

      <div className="im-tools">
        <button type="button" className="im-tool im-tool--exp" onClick={() => setExperience(experience === "3D" ? "2D" : "3D")} title="Trocar a visualização (a jogada e o tempo continuam)">{experience === "3D" ? "2D" : "3D"}</button>
        {experience === "3D" ? <>
          <button type="button" className="im-tool im-tool--cam" onClick={() => changeCamera(presetSettings(cyclePreset(camera.preset)))} title={`Câmera: ${PRESET_LABEL[camera.preset]} — clique para trocar`} aria-label={`Câmera ${PRESET_LABEL[camera.preset]}: trocar`}>{PRESET_LABEL[camera.preset]}</button>
          <button type="button" className={`im-tool ${cameraOpen ? "is-on" : ""}`} onClick={() => setCameraOpen(!cameraOpen)} title="Câmera e gráficos" aria-expanded={cameraOpen}>🎥</button>
        </>
          : <button type="button" className={`im-tool ${cam2d === "full" ? "is-on" : ""}`} onClick={() => { const next = cam2d === "full" ? "play" : "full"; setCam2d(next); writeLocal("bm_cam2d", next); }} title={cam2d === "full" ? "Câmera da jogada" : "Campo inteiro"} aria-pressed={cam2d === "full"}>⛶</button>}
        <button type="button" className={`im-tool ${sound.muted ? "" : "is-on"}`} onClick={() => { matchSound.unlock(); setSoundOpen(!soundOpen); }} title="Som e gráficos" aria-expanded={soundOpen}>{sound.muted ? "🔇" : "🔊"}</button>
        <button type="button" className={`im-tool ${panel ? "is-on" : ""}`} onClick={() => setPanel(!panel)} title="Lances e estatísticas" aria-expanded={panel}>☰</button>
        <button type="button" className="im-tool" onClick={toggleFullscreen} title="Tela cheia">⤢</button>
        {onExit && <button type="button" className="im-tool" onClick={onExit} title="Sair">✕</button>}
      </div>
      {soundOpen && <div className="im-pop" role="dialog" aria-label="Som e gráficos">
        <label><input type="checkbox" checked={!sound.muted} onChange={(e) => { matchSound.set({ muted: !e.target.checked }); setSound({ ...matchSound.settings }); }} /> Som</label>
        <input type="range" min={0} max={1} step={0.05} value={sound.volume} aria-label="Volume" onChange={(e) => { matchSound.set({ volume: Number(e.target.value), muted: false }); setSound({ ...matchSound.settings }); }} />
      </div>}
      {cameraOpen && experience === "3D" && <CameraPanel value={camera} onChange={changeCamera} quality={qualityChoice} onQuality={setQualityChoice}
        shadows={shadows} onShadows={setShadows} fpsCap={fpsCap} onFpsCap={setFpsCap} onClose={() => setCameraOpen(false)} />}

      {banner && <div className={`im-banner im-banner--${banner.tone}`} role="status"><b>{banner.title}</b>{banner.detail && <span>{banner.detail}</span>}</div>}
      {left !== null && view.state === "DECISION" && <div className={`im-timer ${left < 3 ? "is-low" : ""}`} aria-label={`${Math.ceil(left)} segundos para decidir`}><svg viewBox="0 0 36 36" aria-hidden="true"><circle cx="18" cy="18" r="15" /><circle cx="18" cy="18" r="15" style={{ strokeDashoffset: 94.2 * (1 - left / view.decision_seconds) }} /></svg><b>{Math.ceil(left)}</b></div>}
      {(offline || rivalAway) && <div className="im-banner im-banner--warn im-banner--low" role="status">{offline ? "Conexão perdida — reconectando… (sua jogada fica congelada por até 30 s)" : `O técnico do ${club(rival!).name} caiu. Aguardando até 30 s; depois a IA assume os ataques dele.`}</div>}
      {notice && <div className="im-banner im-banner--warn im-banner--low" role="status">{notice}</div>}
      {view.duration?.limit_reached && view.state !== "FINISHED" && <div className="im-banner im-banner--warn im-banner--low" role="status">Tempo da partida esgotado: a IA conclui o lance em andamento e o jogo termina.</div>}
      {feedback && <div className="im-feedback" role="alert">{feedback}</div>}
      {toast && <div key={toast.id} className={`im-toast im-toast--${toast.tone}`} role="status">{toast.text}</div>}
      {r3dStatus === "loading" && <div className="im-loading3d" role="status">Preparando o estádio 3D…</div>}
      {celebration && <button type="button" className="im-goal" onClick={() => setCelebration(null)} aria-label="Pular comemoração"><b>GOL!</b><span>{celebration.name} · {club(celebration.club).name}</span><small>toque para pular</small></button>}

      {aim && <div className="im-power" aria-live="off">{Math.round(aim.power * 100)}%</div>}
      {!spectator && <nav className={`im-actions ${yourTurn ? "" : "is-idle"}`} role="radiogroup" aria-label="Tipo de jogada" aria-disabled={!yourTurn}>
        {(["AUTO", "PASS", "LOFT", "CARRY", "SHOT"] as const).map((key, index) => <button type="button" key={key} role="radio" aria-checked={mode === key} title={`${key === "AUTO" ? "Automático" : TYPE_LABEL[key]} (tecla ${index + 1})`}
          className={`${mode === key ? "is-active" : ""} ${aim?.type === key && mode === "AUTO" ? "is-auto" : ""}`} onClick={() => setMode(key)} disabled={opp?.kind === "PENALTY" && key !== "SHOT" && key !== "AUTO"}>
          <span aria-hidden="true">{TYPE_ICON[key]}</span><em>{key === "AUTO" ? "Auto" : key === "LOFT" ? "Lançar" : TYPE_LABEL[key]}</em><kbd>{index + 1}</kbd></button>)}
      </nav>}
      {opp && view.state === "DECISION" && <div className="im-chip">{opp.label} · jogada {opp.actions + 1}/{opp.max_actions}</div>}

      <aside className={`im-panel ${panel ? "is-open" : ""}`} aria-hidden={!panel}>
        <h2>{club(view.home).name} <b>{view.score.home}–{view.score.away}</b> {club(view.away).name}</h2>
        {spectator && <p className="im-help">Você está assistindo: seu clube não joga esta rodada.</p>}
        {view.state === "HALF_TIME" && <p className="im-help">Intervalo: os times trocam de lado. Nesta partida cada time segue o plano salvo.</p>}
        {view.state === "FINISHED" && <p className="im-help">Fim de jogo. O resultado já está registrado; a rodada termina quando os outros jogos acabarem.</p>}
        <dl className="im-stats">{statRow(view, "Chances", "chances")}{statRow(view, "Chutes", "shots")}{statRow(view, "No gol", "shots_on_target")}{statRow(view, "Passes certos", "passes_completed")}{statRow(view, "Defesas", "saves")}{statRow(view, "Desarmes", "tackles")}</dl>
        <ol className="im-events" aria-label="Lances">{[...view.events].reverse().slice(0, 14).map((e) => <li key={e.event_id} className={`im-ev im-ev--${e.kind.toLowerCase()}`}><b>{e.minute}′</b> {eventLabel(e.kind, e.outcome)} <span>{e.player_name ?? (e.kind === "CHANCE" ? club(e.team ?? "").name : "")}</span></li>)}</ol>
        <p className="im-help im-keys">Teclado: ← → miram, ↑ ↓ força, Tab escolhe um companheiro, 1–5 tipo de ação, Enter ou Espaço executa, Esc cancela.</p>
        <p className="im-help">Ou arraste no campo: direção do gesto = direção da bola; tamanho do gesto = força. A seta e a linha são uma previsão: o passe pode sair torto sob pressão, e a defesa e o goleiro reagem sozinhos.</p>
      </aside>
    </div>
  </section>;
}

function aimValid(view: InteractiveView, aim: Aim): boolean {
  if (aim.type !== "SHOT") return true;
  return aim.ux * attackDir(view) > 0.05;   // a shot has to go towards the rival goal
}

/** Team-mates the moderate pass assistance would consider (same angular window as the server). */
function receiversFor(view: InteractiveView, from: [number, number], aim: Aim): Set<string> {
  const out = new Set<string>();
  const opp = view.opportunity;
  if (!opp || (aim.type !== "PASS" && aim.type !== "LOFT")) return out;
  const L = view.pitch.length, W = view.pitch.width;
  const angle = Math.atan2(aim.uy * W, aim.ux * L);
  const windowAngle = view.physics.assist_angle ?? 0.24;
  const target = predictTarget(view, from, aim);
  const want = Math.hypot((target[0] - from[0]) * L, (target[1] - from[1]) * W);
  opp.roster.forEach((p, i) => {
    if (p.team !== "A" || p.role === "GK" || p.id === opp.carrier) return;
    const dx = (opp.positions[i][0] - from[0]) * L, dy = (opp.positions[i][1] - from[1]) * W;
    const d = Math.hypot(dx, dy);
    if (d < 2.5 || d < 0.3 * want || d > 1.6 * want + 4) return;
    let diff = Math.atan2(dy, dx) - angle; diff = Math.atan2(Math.sin(diff), Math.cos(diff));
    if (Math.abs(diff) <= windowAngle) out.add(p.id);
  });
  return out;
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

function bannerText(view: InteractiveView, attackingName: string, left: number | null, grace: number | null, club: (code: string) => Club):
  { title: string; detail?: string; tone: string } | null {
  const opp = view.opportunity;
  if (view.state === "CLOCK") return { title: `⏩ ${Math.floor(view.minute)}′`, detail: "Simulação rápida até o próximo lance", tone: "clock" };
  if (view.state === "HALF_TIME") return { title: "Intervalo · troca de lado", detail: `${view.score.home} × ${view.score.away}`, tone: "clock" };
  if (view.state === "FINISHED") return { title: "Fim de jogo", detail: `${club(view.home).name} ${view.score.home} × ${view.score.away} ${club(view.away).name}`, tone: "end" };
  if (!opp) return null;
  if (view.state === "DECISION") {
    if (grace !== null) return { title: "Técnico desconectado", detail: `Jogada congelada. A IA assume em ${grace}s.`, tone: "warn" };
    if (view.your_turn) return { title: "Sua jogada", detail: left === null ? "Sem cronômetro" : undefined, tone: "you" };
    return { title: `${opp.label} · ${attackingName}`, detail: view.controller === "HUMAN" ? "O adversário está decidindo — sua defesa é automática" : undefined, tone: "rival" };
  }
  if (view.state === "REPLAY") return { title: `${opp.label} · ${attackingName}`, tone: "rival" };
  if (view.state === "EXECUTING") {
    const step = opp.last;
    if (step?.by === "TIMEOUT") return { title: "Tempo esgotado: a IA jogou por você", tone: "play" };
    if (step?.by === "TIME_BUDGET") return { title: "Tempo do lance esgotado: a IA concluiu a jogada", tone: "play" };
    if (step?.by === "TIME_LIMIT") return { title: "Tempo da partida esgotado: a IA concluiu a jogada", tone: "play" };
    if (step?.by === "AI_TAKEOVER" || step?.by === "AI_CONTROL") return { title: "IA no controle", tone: "play" };
    return null;
  }
  if (view.state === "OUTCOME") return opp.status === "GOAL" ? null : { title: opp.result ?? "Fim da jogada", tone: "end" };
  return null;
}

/** m:ss of the remaining competitive time. */
function clockText(seconds: number): string {
  const s = Math.ceil(seconds);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
