import type { ReactNode } from "react";

import type { Club, RoomState } from "../../lib/api";
import { BotSlotsCard } from "../../components/BotSlotsCard";
import { ClubCrest } from "../../components/ClubCrest";
import { InviteCode } from "../../components/InviteCode";
import { LeagueSettingsSummary } from "../../components/LeagueSettingsSummary";
import { LobbyParticipants } from "../../components/LobbyParticipants";
import { modeInfo } from "../../lib/gameModes";
import { ExperiencePicker } from "../career/interactive/ExperiencePicker";
import { Connection, RetroFooter, RetroFrame, RetroNav } from "../retro/primitives";
import "./lobby-retro.css";

type Props = {
  room: RoomState; clubs: Club[]; isHost: boolean; ownClub: Club | null; managerName: string;
  connection: "connecting" | "online" | "reconnecting" | "offline"; error?: string | null; starting: boolean;
  onStart: () => void; onEdit?: () => void; onChangeClub: () => void; onHome: () => void; settingsDialog?: ReactNode;
};

/**
 * Sala da liga in the Retro Career identity (FIFA 14–16 online lobby feel): stadium stage,
 * club plate, horizontal nav and three columns. It only lays out the lobby's existing pieces
 * (participants, bot places, match experience, rules + start, invite); every action is the
 * lobby's own handler and the server stays the authority.
 */
export function RetroLobby({ room, clubs, isHost, ownClub, managerName, connection, error, starting, onStart, onEdit, onChangeClub, onHome, settingsDialog }: Props) {
  const taken = room.participants.filter((p) => p.selected_club_code).length;
  const people = room.participants.filter((p) => p.role !== "BOT").length;
  const info = modeInfo(room.game_mode ?? "TRADITIONAL");
  return <RetroFrame view="menu" fit label="Sala da liga"
    top={<header className="rt-top">
      <div className="rt-plate">{ownClub && <span className="rt-plate__crest"><ClubCrest club={ownClub} size="md" /></span>}<div className="rt-plate__text"><strong>{room.name}</strong><span>{ownClub ? `${ownClub.name} · Técnico ${managerName}` : `Técnico ${managerName}`}</span></div></div>
      <div className="rt-plate rt-plate--right">
        <div className="rt-stat"><small>Modo</small><b>{info.name}</b></div>
        <div className="rt-stat"><small>Formato</small><b>{room.mode === "FIVE_A_SIDE" ? "5 × 5" : "11 × 11"}</b></div>
        <div className="rt-stat"><small>Clubes</small><b>{taken}/{room.team_count}</b></div>
        <div className="rt-stat"><small>Técnicos</small><b>{people}/{room.max_human_participants}</b></div>
        <div className="rt-top__tools"><Connection state={connection} /><button type="button" className="rt-iconbtn" onClick={onHome}>Menu</button></div>
      </div>
    </header>}
    nav={<div className="lb-navrow"><RetroNav label="Sala da liga" items={[{ id: "room", label: "Sala da liga" }, { id: "club", label: "Trocar de clube" }]} current="room" onSelect={(id) => { if (id === "club") onChangeClub(); }} />
      <div className="lb-invite"><InviteCode code={room.code} /></div></div>}
    footer={<RetroFooter hints={[{ key: "Enter", label: "Selecionar" }, { key: "Tab", label: "Navegar" }, { key: "← →", label: "Abas" }]} right={room.phase === "WAITING" ? "Aguardando o anfitrião iniciar a temporada" : "Temporada em andamento"} />}>
    <div className="lb">
      {error && <p className="rt-toast rt-toast--error lb-error" role="alert">{error}</p>}
      <section className="rt-panel lb-col lb-people rt-scroll" aria-label="Técnicos e vagas">
        <LobbyParticipants participants={room.participants} clubs={clubs} />
        <BotSlotsCard room={room} isHost={isHost} clubs={clubs} />
      </section>
      {(room.execution_mode ?? "TECHNICAL") === "INTERACTIVE"
        ? <section className="rt-panel lb-col lb-xp rt-scroll" aria-label="Experiência de partida"><ExperiencePicker /></section>
        : null}
      <section className="rt-panel lb-col lb-rules rt-scroll" aria-label="Regras da liga e início">
        <LeagueSettingsSummary room={room} isHost={isHost} hasClub={Boolean(ownClub)} isStarting={starting} onEdit={onEdit} onStart={onStart} />
      </section>
    </div>
    {settingsDialog}
  </RetroFrame>;
}
