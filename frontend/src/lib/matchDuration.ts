import type { MatchDuration } from "./api";

/** Real length of a live match chosen by the host (the 90 game minutes are condensed). */
export const MATCH_DURATIONS: { value: MatchDuration; label: string; hint: string }[] = [
  { value: 90, label: "1:30", hint: "Compacto: gols e lances decisivos" },
  { value: 120, label: "2:00", hint: "Mais jogadas construídas" },
  { value: 180, label: "3:00", hint: "Transmissão estendida, menos cortes" },
];

export const durationLabel = (seconds?: number) => MATCH_DURATIONS.find((d) => d.value === seconds)?.label ?? "1:30";
