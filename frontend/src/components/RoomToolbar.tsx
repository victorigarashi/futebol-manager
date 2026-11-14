import type { RoomState } from "../lib/api";
import { ConnectionIndicator } from "./ConnectionIndicator";
import { InviteCode } from "./InviteCode";
const phases: Record<string, string> = { WAITING: "Concentração", INITIAL_MARKET: "Mercado aberto", MARKET_SELECTION: "Confirmar contratações", MARKET_REASSIGNMENT: "Redistribuição", MARKET_REVIEW: "Apresentação do elenco", SQUAD_MANAGEMENT: "Prancheta", SEASON_PREPARATION: "Campeonato", TRANSFER_WINDOW: "Janela de transferências" };
export function RoomToolbar({ room, connection, onHome }: { room: RoomState; connection: "connecting" | "online" | "reconnecting" | "offline"; onHome: () => void }) {
  const step = room.phase === "WAITING" ? 0 : room.phase.startsWith("MARKET") || room.phase === "INITIAL_MARKET" ? 1 : room.phase === "SQUAD_MANAGEMENT" ? 2 : 3;
  return <section className="room-toolbar" id="room-top" aria-label="Sua liga"><div><button className="back-link" type="button" onClick={onHome}>← Minhas ligas</button><h2>{room.name}</h2><span>{phases[room.phase] ?? room.phase}</span><ConnectionIndicator state={connection} /></div><InviteCode code={room.code} /><ol className="room-phase-strip" aria-label="Etapas da liga">{["Clube", "Contratações", "Elenco", "Campeonato"].map((label, index) => <li key={label} aria-current={index === step ? "step" : undefined}><span>{index < step ? "✓" : index + 1}</span>{label}</li>)}</ol></section>;
}
