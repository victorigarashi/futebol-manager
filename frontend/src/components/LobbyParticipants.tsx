import type { Club, Participant } from "../lib/api";
import { ClubCrest } from "./ClubCrest";

type LobbyParticipantsProps = { participants: Participant[]; clubs: Club[] };

export function LobbyParticipants({ participants, clubs }: LobbyParticipantsProps) {
  const byCode = new Map(clubs.map((club) => [club.code, club]));
  return <section className="lobby-participants"><div className="section-heading"><div><p className="section-kicker">TÉCNICOS</p><h2>Quem já entrou em campo</h2></div><span>{participants.filter((p) => p.role !== "BOT").length} técnico(s){participants.some((p) => p.role === "BOT") ? ` · ${participants.filter((p) => p.role === "BOT").length} bot(s)` : ""}</span></div><div className="participant-grid">{participants.map((participant) => {
    const club = participant.selected_club_code ? byCode.get(participant.selected_club_code) : undefined;
    return <article className="participant-card" key={participant.user_id}>{club ? <ClubCrest club={club} size="sm" /> : <span className="participant-card__avatar">{participant.display_name.slice(0, 1)}</span>}<div><strong>{participant.display_name}</strong><span>{participant.role === "HOST" ? "Anfitrião" : participant.role === "BOT" ? "Bot" : "Técnico"}</span></div><small>{club?.name ?? "Escolhendo clube"}</small></article>;
  })}</div></section>;
}
