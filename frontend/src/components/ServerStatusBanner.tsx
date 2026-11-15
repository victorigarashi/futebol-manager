import { useEffect, useState } from "react";

import { serverHealth, subscribeServerHealth, type ServerHealth } from "../lib/serverHealth";

const MESSAGES: Record<Exclude<ServerHealth, "ok" | "degraded">, string> = {
  unavailable: "O servidor do jogo está reiniciando. Suas escolhas salvas continuam guardadas; reconectando automaticamente…",
  offline: "Sem conexão com a internet ou com o servidor. Reconectando automaticamente…",
};

/** One clear, global notice while the API cannot be reached (instead of silent failures). */
export function ServerStatusBanner() {
  const [health, setHealth] = useState<ServerHealth>(serverHealth());
  useEffect(() => subscribeServerHealth(setHealth), []);
  if (health === "ok" || health === "degraded") return null;
  return <div className={`server-banner server-banner--${health}`} role="alert" aria-live="assertive"><i aria-hidden="true" />{MESSAGES[health]}</div>;
}
