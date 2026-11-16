import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import type { LiveView } from "../../../lib/api";
import { applyLiveState, applyLiveStats, type LiveStateMessage, type LiveStatsMessage } from "../../../lib/liveState";
import { socketOnline, subscribeSocket } from "../../../lib/socketBus";

/** Whether the room socket is connected (re-renders when it changes). */
export function useSocketOnline(): boolean {
  const [online, setOnline] = useState(socketOnline());
  useEffect(() => subscribeSocket(setOnline), []);
  return online;
}

/**
 * Applies the socket's live messages to the cached live view. A sequence gap or an
 * explicit `live.resync` (the server dropped a backlog for a slow client) triggers a
 * single HTTP reconciliation; nothing is guessed.
 */
export function useLiveStream(roomId: string): void {
  const client = useQueryClient();
  useEffect(() => {
    const key = ["live", roomId];
    let reconciling = false;
    const reconcile = () => {
      if (reconciling) return;
      reconciling = true;
      void client.invalidateQueries({ queryKey: key }).finally(() => { reconciling = false; });
    };
    const onLive = (event: Event) => {
      const message = (event as CustomEvent<LiveStateMessage | LiveStatsMessage | { type: "live.resync" }>).detail;
      if (message.type === "live.resync") { reconcile(); return; }
      const current = client.getQueryData<LiveView>(key);
      if (message.type === "live.state") {
        const result = applyLiveState(current, message);
        if (!result) { if (current?.live_round) reconcile(); return; }
        if (result.gap) { reconcile(); return; }
        client.setQueryData(key, result.view);
      } else {
        const merged = applyLiveStats(current, message);
        if (merged) client.setQueryData(key, merged);
      }
    };
    window.addEventListener("bm:live", onLive);
    return () => window.removeEventListener("bm:live", onLive);
  }, [client, roomId]);
}
