import type { Club, Participant } from "../lib/api";
import { ClubCard, type ClubAvailability } from "./ClubCard";

type ClubSelectionGridProps = {
  clubs: Club[];
  participants: Participant[];
  currentUserId: string | null;
  isLoading: boolean;
  onSelect: (club: Club) => void;
};

export function ClubSelectionGrid({ clubs, participants, currentUserId, isLoading, onSelect }: ClubSelectionGridProps) {
  const owners = new Map(participants.flatMap((participant) => participant.selected_club_code ? [[participant.selected_club_code, participant] as const] : []));
  return <div className="club-selection-grid" aria-label="Clubes disponíveis">
    {clubs.map((club) => {
      const owner = owners.get(club.code);
      const availability: ClubAvailability = isLoading ? "loading" : owner?.user_id === currentUserId ? "selected" : owner ? "occupied" : "available";
      return <ClubCard key={club.code} club={club} availability={availability} managerName={owner?.display_name} onSelect={onSelect} />;
    })}
  </div>;
}
