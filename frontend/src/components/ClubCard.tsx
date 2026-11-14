import type { Club } from "../lib/api";
import { ClubCrest } from "./ClubCrest";

export type ClubAvailability = "available" | "selected" | "occupied" | "loading";

type ClubCardProps = {
  club: Club;
  availability: ClubAvailability;
  managerName?: string;
  onSelect: (club: Club) => void;
};

const statusLabel: Record<ClubAvailability, string> = {
  available: "Livre",
  selected: "Seu clube",
  occupied: "Em jogo",
  loading: "Atualizando",
};

export function ClubCard({ club, availability, managerName, onSelect }: ClubCardProps) {
  const disabled = availability === "occupied" || availability === "loading";
  return <button
    className={`club-card club-card--${availability}`}
    aria-pressed={availability === "selected"}
    type="button"
    disabled={disabled}
    onClick={() => onSelect(club)}
    aria-label={`${club.name}: ${statusLabel[availability]}${managerName ? `, técnico ${managerName}` : ""}`}
  >
    <ClubCrest club={club} />
    <span className="club-card__copy"><strong>{club.name}</strong><small>{managerName ?? statusLabel[availability]}</small></span>
    <span className="club-card__status">{statusLabel[availability]}</span>
  </button>;
}
