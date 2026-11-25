/**
 * Protocol between Brasileirão Manager and a PES 2013 Web runtime HOST PAGE (v1).
 *
 * Isolation (why there is a host page at all): the runtime is third-party code. It is never
 * loaded into the app's origin (no `new Worker(url)` here): it would get the session token in
 * localStorage and the whole app. The user serves the runtime THEY legitimately own from their
 * own machine (a different origin, e.g. http://127.0.0.1:8765), inside an iframe; the only
 * channel is postMessage, and every message is checked for origin and shape.
 *
 * The keyboard stays inside the iframe (it has focus while playing): the app never relays keys.
 *
 * Nothing about the runtime itself is assumed here: which messages its worker takes, whether it
 * can load a roster, select clubs or report a score are open questions (docs/pes-integration).
 * Messages that need those abilities exist in the protocol but the bridge refuses to send them
 * until the matching capability has been validated.
 */

export const PROTOCOL_VERSION = 1;

/** Origins a runtime host page may live on: the user's own machine only (same rule the
 * runtime's relay was reported to enforce). Never a public host, never the app's origin. */
export function validateRuntimeOrigin(raw: string, appOrigin: string): string {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw new Error("Endereço do runtime inválido.");
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") throw new Error("O runtime precisa ser servido por http(s).");
  if (url.hostname !== "localhost" && url.hostname !== "127.0.0.1") throw new Error("O runtime só pode ser servido pela sua própria máquina (localhost ou 127.0.0.1).");
  if (!url.port) throw new Error("Informe a porta do servidor local do runtime.");
  if (url.username || url.password) throw new Error("O endereço do runtime não pode conter credenciais.");
  if (url.origin === appOrigin) throw new Error("O runtime precisa de uma origem diferente da do jogo (isolamento).");
  return url.origin;
}

export type RuntimeCapabilities = {
  can_load_custom_roster: boolean; can_select_teams: boolean; can_auto_start_match: boolean; can_read_result: boolean;
  can_netplay: boolean; supports_5v5: boolean; supports_11v11: boolean;
};

export const NO_CAPABILITIES: RuntimeCapabilities = {
  can_load_custom_roster: false, can_select_teams: false, can_auto_start_match: false, can_read_result: false,
  can_netplay: false, supports_5v5: false, supports_11v11: false,
};

/** App -> host page. */
export type AppMessage =
  | { v: 1; type: "hello" }
  | { v: 1; type: "prepare-match"; match_id: string; payload_checksum: string; payload: unknown }
  | { v: 1; type: "close" };

/** Host page -> app. A host page reports what it CAN do; the app still trusts only validated
 * capabilities (the server's matrix), never a host's claim on its own. */
export type HostMessage =
  | { v: 1; type: "ready"; runtime: { name: string; build: string } }
  | { v: 1; type: "status"; state: "LOADING" | "MENU" | "IN_MATCH" | "FINISHED" }
  | { v: 1; type: "result"; match_id: string; payload_checksum: string; home_goals: number; away_goals: number }
  | { v: 1; type: "error"; message: string };

const short = (value: unknown, max: number) => typeof value === "string" && value.length > 0 && value.length <= max;
const goals = (value: unknown) => Number.isInteger(value) && (value as number) >= 0 && (value as number) <= 99;

/** Validate a message from the host page: right origin, right version, known shape. Anything
 * else is dropped (returns null) — a page that misbehaves gets no say. */
export function parseHostMessage(data: unknown, origin: string, expectedOrigin: string): HostMessage | null {
  if (origin !== expectedOrigin || typeof data !== "object" || data === null) return null;
  const m = data as Record<string, unknown>;
  if (m.v !== PROTOCOL_VERSION) return null;
  switch (m.type) {
    case "ready": {
      const r = m.runtime as Record<string, unknown> | undefined;
      return r && short(r.name, 80) && short(r.build, 80) ? { v: 1, type: "ready", runtime: { name: r.name as string, build: r.build as string } } : null;
    }
    case "status":
      return ["LOADING", "MENU", "IN_MATCH", "FINISHED"].includes(m.state as string) ? { v: 1, type: "status", state: m.state as "LOADING" } : null;
    case "result":
      return short(m.match_id, 120) && typeof m.payload_checksum === "string" && /^sha256:[0-9a-f]{64}$/.test(m.payload_checksum) && goals(m.home_goals) && goals(m.away_goals)
        ? { v: 1, type: "result", match_id: m.match_id as string, payload_checksum: m.payload_checksum, home_goals: m.home_goals as number, away_goals: m.away_goals as number }
        : null;
    case "error":
      return short(m.message, 500) ? { v: 1, type: "error", message: m.message as string } : null;
    default:
      return null;
  }
}
