import { useEffect, useMemo, useRef } from "react";

import { api, type BroadcastSegment, type FrameRow } from "../../../lib/api";
import { BroadcastTimeline, DISPLAY_DELAY_SECONDS, ServerClock, type BroadcastView } from "./broadcastClock";
import { FrameBuffer } from "./frameBuffer";
import { backoffDelay } from "../../../lib/serverHealth";

type FramesPush = { match_id?: string; frames?: FrameRow[]; broadcast?: BroadcastSegment[]; server_now?: number };

/**
 * Streams the coach's own match: authoritative frames into a buffer the canvas reads
 * directly, plus the broadcast timeline that says which tick is on screen at each
 * moment of the server clock (WebSocket push, with HTTP polling as a fallback).
 * Nothing here goes through React state, so the page does not re-render per frame.
 */
export function useFrameStream(roomId: string, matchId: string | undefined, active: boolean, initial?: { segments?: BroadcastSegment[] | null; serverNow?: number }) {
  const buffer = useMemo(() => new FrameBuffer(), []);
  const timeline = useMemo(() => new BroadcastTimeline(), []);
  const server = useMemo(() => new ServerClock(), []);
  // starvedSeconds: how far the screen has run past the broadcast it holds (real lag).
  // delayMs: how old pushed frames are when they arrive (server clock vs. its timestamp).
  const status = useRef({ online: true, failures: 0, lastData: Date.now(), starvedSeconds: 0, delayMs: 0 });
  const view = useRef<BroadcastView>({ tick: 0, kind: "WAIT", label: "", cut: null });

  useEffect(() => { buffer.reset(); timeline.reset(); }, [matchId, buffer, timeline]);
  // Live-view refreshes (every second or on demand) also carry the timeline and the server clock.
  useEffect(() => {
    timeline.merge(initial?.segments);
    server.observe(initial?.serverNow);
  }, [initial?.segments, initial?.serverNow, timeline, server]);

  // Primary path: frames pushed over the room WebSocket.
  const lastPush = useRef(0);
  useEffect(() => {
    if (!active || !matchId) return;
    const onFrames = (event: Event) => {
      const detail = (event as CustomEvent<FramesPush>).detail;
      if (detail?.match_id !== matchId) return;
      server.observe(detail.server_now);
      if (typeof detail.server_now === "number") {
        const delay = Math.max(0, (server.now() - detail.server_now) * 1000);
        status.current.delayMs = status.current.delayMs * 0.8 + delay * 0.2;
      }
      timeline.merge(detail.broadcast);
      if (detail.frames) buffer.push(detail.frames);
      lastPush.current = Date.now();
      status.current = { ...status.current, online: true, failures: 0, lastData: Date.now() };
    };
    window.addEventListener("bm:frames", onFrames);
    return () => window.removeEventListener("bm:frames", onFrames);
  }, [active, matchId, buffer, timeline, server]);

  // Fallback: HTTP polling only while the socket is silent (reconnecting, proxies…).
  useEffect(() => {
    if (!active || !matchId) return;
    let stopped = false;
    let timer = 0;
    const poll = async () => {
      if (Date.now() - lastPush.current < 1500) {
        if (!stopped) timer = window.setTimeout(poll, 1000);
        return;
      }
      try {
        const { data } = await api.liveFrames(roomId, buffer.latestTick);
        if (stopped) return;
        if (data.match_id === matchId) {
          server.observe(data.server_now);
          timeline.merge(data.broadcast);
          buffer.push(data.frames);
        }
        status.current = { ...status.current, online: true, failures: 0, lastData: Date.now() };
      } catch {
        status.current = { ...status.current, online: false, failures: status.current.failures + 1 };
      }
      // Fallback polling backs off (with jitter) while the server does not answer.
      if (!stopped) timer = window.setTimeout(poll, status.current.online ? 700 : backoffDelay(status.current.failures - 1, 600, 8000));
    };
    void poll();
    return () => { stopped = true; window.clearTimeout(timer); };
  }, [roomId, matchId, active, buffer, timeline, server]);

  /** Called by the canvas every animation frame: the moment of the broadcast to draw. */
  const driver = (): BroadcastView => {
    const time = server.now() - DISPLAY_DELAY_SECONDS;
    const next = timeline.at(time);
    const last = timeline.last;
    status.current.starvedSeconds = last && !(last.k === "BREAK" && last.label === "FULL_TIME") ? Math.max(0, time - last.r1) : 0;
    // Never draw past the frames we actually hold (slow network): hold the last one.
    if (next.kind === "PLAY" && buffer.latestTick >= 0 && next.tick > buffer.latestTick) next.tick = buffer.latestTick;
    view.current = next;
    return next;
  };
  return { buffer, timeline, server, driver, view, status };
}
