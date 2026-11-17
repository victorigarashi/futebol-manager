import type { GameMode } from "./api";

export type ModeInfo = {
  id: GameMode;
  name: string;
  tagline: string;
  description: string;
  /** Clubs the mode can start with (the server enforces the same list). */
  sizes: readonly (4 | 6 | 8 | 10 | 12 | 16 | 20)[];
  defaultSize: 4 | 6 | 8 | 10 | 12 | 16 | 20;
  /** Qualitative length only: no promise of measured times. */
  length: string;
  squads: string;
  accent: string;
};

export const GAME_MODES: readonly ModeInfo[] = [
  {
    id: "TRADITIONAL", name: "Carreira", tagline: "Temporadas, mercado e títulos",
    description: "Monte o elenco no mercado, dispute o Brasileirão, playoffs e Copa, e leve o clube por várias temporadas.",
    sizes: [4, 6, 8, 10, 12, 16, 20], defaultSize: 20, length: "Longa · várias sessões", squads: "Mercado inicial", accent: "#90fca3",
  },
  {
    id: "DRAFT", name: "Draft", tagline: "Três cartas por posição",
    description: "Cada técnico monta o time escolhendo uma entre três cartas por posição. Depois, campeonato completo.",
    sizes: [4, 6, 8, 10, 12, 16, 20], defaultSize: 8, length: "Média a longa", squads: "Cartas do Draft", accent: "#7dd3fc",
  },
  {
    id: "DRAFT_KNOCKOUT", name: "Draft Eliminatório", tagline: "Monte o time e vá direto ao mata-mata",
    description: "O Draft de sempre, mas sem pontos corridos: chave sorteada, jogo único, pênaltis no empate. Quem perde, sai.",
    sizes: [4, 8, 16], defaultSize: 8, length: "Curta · uma sessão", squads: "Cartas do Draft", accent: "#f5c451",
  },
  {
    id: "SURVIVOR", name: "Último Sobrevivente", tagline: "A cada rodada, os piores caem",
    description: "Todos jogam ao mesmo tempo com os elencos reais. Depois de cada rodada os últimos da classificação são eliminados, até sobrar um.",
    sizes: [8, 12, 16, 20], defaultSize: 12, length: "Curta a média", squads: "Elencos reais dos clubes", accent: "#f87171",
  },
  {
    id: "PACK", name: "Pack & Play", tagline: "Abra pacotes, monte o time, jogue",
    description: "Cada técnico abre pacotes gratuitos de atletas reais, monta o time com as cartas que tirou e parte para um torneio rápido.",
    sizes: [4, 8, 16], defaultSize: 8, length: "Curta · uma sessão", squads: "Cartas dos pacotes", accent: "#c4b5fd",
  },
];

export const modeInfo = (mode?: GameMode | null): ModeInfo => GAME_MODES.find((m) => m.id === mode) ?? GAME_MODES[0];

/** Modes without a league: knockout tournament or survival rounds. */
export const isShortMode = (mode?: GameMode | null) => mode === "DRAFT_KNOCKOUT" || mode === "PACK" || mode === "SURVIVOR";
export const usesDraft = (mode?: GameMode | null) => mode === "DRAFT" || mode === "DRAFT_KNOCKOUT";

/** Stages of the knockout tournament for a bracket size (same rule as the server). */
export const tournamentStages = (size: number) => size >= 16 ? ["Oitavas", "Quartas", "Semifinal", "Final"] : size >= 8 ? ["Quartas", "Semifinal", "Final"] : ["Semifinal", "Final"];

/** Active clubs at the start of each survival round (same rule as the server). */
export function survivorPath(size: number, configured: number): number[] {
  const path = [size];
  let active = size;
  while (active > 2) {
    const auto = Math.max(2, 2 * roundHalfEven((active * 0.25) / 2));
    let out = configured || auto;
    out = Math.max(2, out - (out % 2));
    active -= Math.min(out, active - 2);
    path.push(active);
  }
  return path;
}

/** Python's round(): halves go to the even neighbour (2.5 → 2), like the server. */
function roundHalfEven(value: number): number {
  const floor = Math.floor(value);
  const diff = value - floor;
  if (Math.abs(diff - 0.5) < 1e-9) return floor % 2 === 0 ? floor : floor + 1;
  return Math.round(value);
}
