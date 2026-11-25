import { NO_CAPABILITIES, type HostMessage, type RuntimeCapabilities } from "./protocol";

/**
 * PESRuntimeBridge: the only way the game talks to a PES 2013 Web runtime. Decoupled from the
 * rest of the game (nothing imports it outside this folder yet) and from the runtime itself
 * (which the user hosts; see ./protocol.ts for the isolation rules).
 *
 * Lifecycle: UNAVAILABLE | IDLE -> CONNECTING -> READY -> PREPARING -> IN_MATCH -> FINISHED,
 * any -> FAILED (with a message, never a made-up result).
 *
 * The only implementation today is UnavailablePESRuntimeBridge: no runtime has been validated,
 * so every operation fails explicitly and the Resenha engine stays the one that plays.
 * A real implementation (an iframe on the user's local origin) is written only after the
 * experiments in docs/pes-integration/01-fase2-diagnostico.md prove what the runtime can do.
 */
export type BridgeState = "UNAVAILABLE" | "IDLE" | "CONNECTING" | "READY" | "PREPARING" | "IN_MATCH" | "FINISHED" | "FAILED";

export type MatchPayloadRef = { match_id: string; checksum: string; payload: unknown };

export type BridgeEvent =
  | { kind: "state"; state: BridgeState; reason?: string }
  | { kind: "host"; message: HostMessage };

export interface PESRuntimeBridge {
  readonly state: BridgeState;
  /** Validated capabilities only (from the server's matrix), never what a host page claims. */
  readonly capabilities: RuntimeCapabilities;
  /** Mount the user's runtime host page (isolated origin) in this container. */
  connect(container: HTMLElement, runtimeUrl: string): Promise<void>;
  /** Hand the match contract to the runtime. Refused unless roster loading and team
   * selection have been validated. */
  prepareMatch(match: MatchPayloadRef): Promise<void>;
  onEvent(listener: (event: BridgeEvent) => void): () => void;
  close(): void;
}

export class RuntimeUnavailableError extends Error {
  constructor(message = "PES 2013 Web: integração experimental, ainda não validada. A partida é jogada na engine atual do Resenha.") {
    super(message);
    this.name = "RuntimeUnavailableError";
  }
}

/** What the game uses today: honest refusal, never a simulated runtime. */
export class UnavailablePESRuntimeBridge implements PESRuntimeBridge {
  readonly state: BridgeState = "UNAVAILABLE";
  readonly capabilities: RuntimeCapabilities = NO_CAPABILITIES;

  connect(): Promise<void> {
    return Promise.reject(new RuntimeUnavailableError());
  }

  prepareMatch(): Promise<void> {
    return Promise.reject(new RuntimeUnavailableError());
  }

  onEvent(): () => void {
    return () => {};
  }

  close(): void {}
}

/** Gate used by any future implementation before sending a match to the runtime. */
export function assertCanPrepare(capabilities: RuntimeCapabilities, mode: "FIVE_A_SIDE" | "ELEVEN_A_SIDE"): void {
  const missing = [
    !capabilities.can_load_custom_roster && "carregar o elenco do Resenha",
    !capabilities.can_select_teams && "selecionar mandante e visitante",
    !(mode === "FIVE_A_SIDE" ? capabilities.supports_5v5 : capabilities.supports_11v11) && `jogar ${mode === "FIVE_A_SIDE" ? "5×5" : "11×11"}`,
  ].filter(Boolean);
  if (missing.length) throw new RuntimeUnavailableError(`O runtime ainda não comprovou: ${missing.join(", ")}.`);
}

export function createPESRuntimeBridge(): PESRuntimeBridge {
  return new UnavailablePESRuntimeBridge();
}
