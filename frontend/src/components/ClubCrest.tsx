import { useState, type CSSProperties } from "react";
import type { Club } from "../lib/api";
import { CLUB_CREST_URLS } from "../lib/clubMedia";

type ClubCrestProps = {
  club: Club;
  size?: "sm" | "md" | "lg";
};

// Source: club marks visible in the reference screen supplied with this project. The sprite stays
// local, is never stretched, and lets the product render even when offline.
const crestPositions: Record<Club["code"], { x: number; y: number }> = {
  CAP: { x: -309, y: -219 }, CAM: { x: -519, y: -219 }, BAH: { x: -729, y: -219 }, BOT: { x: -939, y: -219 }, CHA: { x: -1149, y: -219 },
  COR: { x: -309, y: -371 }, CFC: { x: -519, y: -371 }, CRU: { x: -729, y: -371 }, FLA: { x: -939, y: -371 }, FLU: { x: -1149, y: -371 },
  GRE: { x: -309, y: -526 }, INT: { x: -519, y: -526 }, MIR: { x: -729, y: -526 }, PAL: { x: -939, y: -526 },
  REM: { x: -309, y: -680 }, SAN: { x: -519, y: -680 }, SAO: { x: -729, y: -680 }, VAS: { x: -939, y: -680 }, VIT: { x: -1149, y: -680 },
};

export function ClubCrest({ club, size = "md" }: ClubCrestProps) {
  const [imageFailed, setImageFailed] = useState(false);
  const crestUrl = CLUB_CREST_URLS[club.code];
  if (crestUrl && !imageFailed) return <span className={`club-crest club-crest--${size} club-crest--image`} role="img" aria-label={`Escudo do ${club.name}`}><img src={crestUrl} alt="" loading="lazy" decoding="async" referrerPolicy="no-referrer" onError={() => setImageFailed(true)} /></span>;
  const position = crestPositions[club.code];
  if (!position) return <span className={`club-crest club-crest--${size} club-crest--fallback`} role="img" aria-label={`Identidade provisória do ${club.name}; escudo autorizado indisponível`} title="Escudo correto indisponível nos recursos fornecidos">{club.code}</span>;
  return <span className={`club-crest club-crest--${size}`} role="img" aria-label={`Escudo do ${club.name}`} style={{ "--crest-x": `${position.x}px`, "--crest-y": `${position.y}px` } as CSSProperties}><span className="sr-only">Escudo do {club.name}</span></span>;
}
