import type { RoomState } from "../lib/api";
import { ConnectionIndicator } from "./ConnectionIndicator";
import { InviteCode } from "./InviteCode";
const phases: Record<string, string> = { WAITING: "Concentração", INITIAL_MARKET: "Mercado aberto", MARKET_SELECTION: "Confirmar contratações", MARKET_REASSIGNMENT: "Redistribuição", MARKET_REVIEW: "Apresentação do elenco", SQUAD_MANAGEMENT: "Prancheta", DRAFT: "Draft", PACK: "Pacotes", SEASON_PREPARATION: "Campeonato", TRANSFER_WINDOW: "Janela de transferências" };
export function RoomToolbar({ room, connection, onHome }: { room: RoomState; connection: "connecting" | "online" | "reconnecting" | "offline"; onHome: () => void }) {
  const mode = room.game_mode ?? "TRADITIONAL";
  const labels = mode === "SURVIVOR" ? ["Clube", "Elenco", "Sobrevivência"] : mode === "PACK" ? ["Clube", "Pacotes", "Elenco", "Torneio"] : mode === "DRAFT" || mode === "DRAFT_KNOCKOUT" ? ["Clube", "Draft", "Elenco", mode === "DRAFT_KNOCKOUT" ? "Competição" : "Campeonato"] : ["Clube", "Contratações", "Elenco", "Campeonato"];
  const step = room.phase === "WAITING" ? 0 : room.phase.startsWith("MARKET") || room.phase === "INITIAL_MARKET" || room.phase === "DRAFT" || room.phase === "PACK" ? 1 : room.phase === "SQUAD_MANAGEMENT" ? (mode === "SURVIVOR" ? 1 : 2) : labels.length - 1;
  return <section className="room-toolbar" id="room-top" aria-label="Sua liga"><div><button className="back-link" type="button" onClick={onHome}>← Minhas ligas</button><h2>{room.name}</h2><span>{phases[room.phase] ?? room.phase}</span><ConnectionIndicator state={connection} /></div><InviteCode code={room.code} /><ol className="room-phase-strip" aria-label="Etapas da liga">{labels.map((label, index) => <li key={label} aria-current={index === step ? "step" : undefined}><span>{index < step ? "✓" : index + 1}</span>{label}</li>)}</ol></section>;
}
