import { useEffect, useMemo, useRef } from "react";

import { api, type FrameRow } from "../../../lib/api";
import { FrameBuffer, PlaybackClock } from "./frameBuffer";

/**
 * Streams authoritative frames of the coach's own match into a buffer that the canvas
 * reads directly (WebSocket push, with HTTP polling as a fallback). Nothing here goes through React state, so the page does not re-render
 * per frame; reconnects resume from the last tick received.
 */
export function useFrameStream(roomId: string, matchId: string | undefined, active: boolean, ticksPerSecond: number) {
  const buffer = useMemo(() => new FrameBuffer(), []);
  const clock = useRef(new PlaybackClock(ticksPerSecond || 30));
  const status = useRef({ online: true, failures: 0 });

  useEffect(() => { clock.current.setRate(ticksPerSecond || 30); }, [ticksPerSecond]);
  useEffect(() => { buffer.reset(); clock.current = new PlaybackClock(ticksPerSecond || 30); }, [matchId, buffer]); // eslint-disable-line react-hooks/exhaustive-deps

  // Primary path: frames pushed over the room WebSocket.
  const lastPush = useRef(0);
  useEffect(() => {
    if (!active || !matchId) return;
    const onFrames = (event: Event) => {
      const detail = (event as CustomEvent<{ match_id?: string; frames?: FrameRow[] }>).detail;
      if (detail?.match_id !== matchId || !detail.frames) return;
      buffer.push(detail.frames);
      lastPush.current = Date.now();
    };
    window.addEventListener("bm:frames", onFrames);
    return () => window.removeEventListener("bm:frames", onFrames);
  }, [active, matchId, buffer]);

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
        if (data.match_id === matchId) buffer.push(data.frames);
        status.current = { online: true, failures: 0 };
      } catch {
        status.current = { online: false, failures: status.current.failures + 1 };
      }
      if (!stopped) timer = window.setTimeout(poll, status.current.online ? 1000 : Math.min(4000, 600 * status.current.failures));
    };
    void poll();
    return () => { stopped = true; window.clearTimeout(timer); };
  }, [roomId, matchId, active, buffer]);

  const driver = (deltaMs: number) => clock.current.advance(deltaMs, buffer.latestTick);
  return { buffer, clock, driver, status };
}
