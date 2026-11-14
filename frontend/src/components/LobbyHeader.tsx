import type { RoomState } from "../lib/api";
import { ConnectionIndicator } from "./ConnectionIndicator";
import { InviteCode } from "./InviteCode";

type LobbyHeaderProps = { room: RoomState; connection: "connecting" | "online" | "reconnecting" | "offline" };

export function LobbyHeader({ room, connection }: LobbyHeaderProps) {
  const budget = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 }).format(room.initial_budget_cents / 100);
  return <header className="lobby-header"><div><p className="section-kicker">SALA DA RESENHA</p><h1>{room.name}</h1><p>A galera tá chegando. Convoca a rapaziada.</p></div><div className="lobby-header__meta"><InviteCode code={room.code} /><ConnectionIndicator state={connection} /><span>{room.participant_count ?? 0} técnicos · {room.bot_count ?? 20} bots</span><span>{room.mode === "FIVE_A_SIDE" ? "5 × 5" : "11 × 11"} · {budget}</span></div></header>;
}
