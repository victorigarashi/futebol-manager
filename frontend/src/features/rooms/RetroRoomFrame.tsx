import type { ReactNode } from "react";

import type { Club, RoomState } from "../../lib/api";
import { ClubCrest } from "../../components/ClubCrest";
import { InviteCode } from "../../components/InviteCode";
import { modeInfo } from "../../lib/gameModes";
import { Connection, RetroFooter, RetroFrame } from "../retro/primitives";
import "../retro/skin.css";
import "./room-retro.css";

const PHASE: Record<string, string> = { WAITING: "Concentração", INITIAL_MARKET: "Mercado aberto", MARKET_SELECTION: "Confirmar contratações", MARKET_REASSIGNMENT: "Redistribuição", MARKET_REVIEW: "Apresentação do elenco", SQUAD_MANAGEMENT: "Prancheta", DRAFT: "Draft", PACK: "Pacotes", SEASON_PREPARATION: "Campeonato", TRANSFER_WINDOW: "Janela de transferências" };

/** The league's steps for its mode (same rules the legacy toolbar used). */
function roomSteps(room: RoomState): { labels: string[]; step: number } {
  const mode = room.game_mode ?? "TRADITIONAL";
  const labels = mode === "SURVIVOR" ? ["Clube", "Elenco", "Sobrevivência"] : mode === "PACK" ? ["Clube", "Pacotes", "Elenco", "Torneio"] : mode === "DRAFT" || mode === "DRAFT_KNOCKOUT" ? ["Clube", "Draft", "Elenco", mode === "DRAFT_KNOCKOUT" ? "Competição" : "Campeonato"] : ["Clube", "Contratações", "Elenco", "Campeonato"];
  const step = room.phase === "WAITING" ? 0 : room.phase.startsWith("MARKET") || room.phase === "INITIAL_MARKET" || room.phase === "DRAFT" || room.phase === "PACK" ? 1 : room.phase === "SQUAD_MANAGEMENT" ? (mode === "SURVIVOR" ? 1 : 2) : labels.length - 1;
  return { labels, step };
}

/**
 * Console frame for every room phase outside the career (market, draft, pack, squad
 * management, club choice): club plate, league status, step strip, invite and menu.
 * The phase's own component renders inside, under the retro skin; no logic lives here.
 */
export function RetroRoomFrame({ room, ownClub, managerName, connection, onHome, error, label, fit, children }: {
  room: RoomState; ownClub: Club | null; managerName: string; connection: "connecting" | "online" | "reconnecting" | "offline";
  onHome: () => void; error?: string | null; label: string; fit?: boolean; children: ReactNode;
}) {
  const { labels, step } = roomSteps(room);
  const info = modeInfo(room.game_mode ?? "TRADITIONAL");
  return <RetroFrame view="career" fit={fit} label={label}
    top={<header className="rt-top">
      <div className="rt-plate">{ownClub && <span className="rt-plate__crest"><ClubCrest club={ownClub} size="md" /></span>}<div className="rt-plate__text"><strong>{ownClub?.name ?? room.name}</strong><span>{ownClub ? `Técnico ${managerName} · ${room.name}` : `Técnico ${managerName}`}</span></div></div>
      <div className="rt-plate rt-plate--right">
        <div className="rt-stat"><small>Etapa</small><b>{PHASE[room.phase] ?? room.phase}</b></div>
        <div className="rt-stat"><small>Modo</small><b>{info.name}</b></div>
        <div className="rt-stat"><small>Formato</small><b>{room.mode === "FIVE_A_SIDE" ? "5 × 5" : "11 × 11"}</b></div>
        <div className="rt-top__tools"><Connection state={connection} /><button type="button" className="rt-iconbtn" onClick={onHome}>Menu</button></div>
      </div>
    </header>}
    nav={<div className="rr-navrow">
      <ol className="rr-steps" aria-label="Etapas da liga">{labels.map((text, index) => <li key={text} aria-current={index === step ? "step" : undefined} className={index < step ? "is-done" : ""}><span>{index < step ? "✓" : index + 1}</span>{text}</li>)}</ol>
      <div className="lb-invite"><InviteCode code={room.code} /></div>
    </div>}
    footer={<RetroFooter hints={[{ key: "Tab", label: "Navegar" }, { key: "Enter", label: "Selecionar" }]} right={`${room.name} · ${PHASE[room.phase] ?? room.phase}`} />}>
    <div className="rt-skin rt-page rr-body">
      {error && <p className="rt-toast rt-toast--error" role="alert">{error}</p>}
      {children}
    </div>
  </RetroFrame>;
}
