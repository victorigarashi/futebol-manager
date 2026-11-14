import type { EngineEvent, MatchPhase } from "../../lib/api";

export const POSITION_LABEL: Record<string, string> = { GK: "GOL", DF: "DEF", MF: "MEI", ST: "ATA" };
export const POSITION_NAME: Record<string, string> = { GK: "Goleiro", DF: "Defensor", MF: "Meio-campista", ST: "Atacante" };
export const PHASE_LABEL: Record<MatchPhase, string> = {
  PRESENTATION: "Apresentação", FIRST_HALF: "1º tempo", HALF_TIME: "Intervalo", SECOND_HALF: "2º tempo", FULL_TIME: "Fim de jogo",
};
export const ATTRIBUTE_LABEL: Record<string, string> = {
  pace: "Velocidade", passing: "Passe", shooting: "Finalização", dribbling: "Drible", defending: "Defesa", physical: "Físico", keeping: "Goleiro",
};

export function eventText(event: EngineEvent, clubName: (code: string) => string): { title: string; detail: string; tone: string } {
  const who = event.player_name ?? "";
  const team = event.team ? clubName(event.team) : "";
  switch (event.kind) {
    case "GOAL": return { title: "GOL!", detail: `${who}${event.secondary_player_name ? ` (assist. ${event.secondary_player_name})` : ""} · ${team}`, tone: "goal" };
    case "SHOT": return {
      title: event.outcome === "ON_TARGET" ? "Finalização no alvo" : event.outcome === "BLOCKED" ? "Finalização bloqueada" : event.outcome === "GOAL" ? "Finalização" : "Finalização para fora",
      detail: `${who}${event.header ? " de cabeça" : ""} · xG ${event.xg.toFixed(2)}`, tone: "shot",
    };
    case "SAVE": return { title: "Defesa do goleiro", detail: `${who || "Goleiro"} · ${team}`, tone: "save" };
    case "BIG_CHANCE": return { title: "Chance clara", detail: `${who} · ${team}`, tone: "shot" };
    case "CORNER": return { title: "Escanteio", detail: team, tone: "minor" };
    case "FOUL": return { title: "Falta", detail: `${who} em ${event.secondary_player_name ?? "adversário"}`, tone: "minor" };
    case "CARD": return { title: event.outcome === "YELLOW" ? "Cartão amarelo" : event.outcome === "SECOND_YELLOW" ? "Segundo amarelo — expulso" : "Cartão vermelho", detail: `${who} · ${team}`, tone: event.outcome === "YELLOW" ? "yellow" : "red" };
    case "SUBSTITUTION": return { title: "Substituição", detail: `Entra ${who}, sai ${event.secondary_player_name ?? ""} · ${team}`, tone: "sub" };
    case "TACTICS": return { title: "Mudança tática", detail: event.tactics ? `${team}: ${tacticSummary(event.tactics)}` : `${team} mudou a postura`, tone: "tactic" };
    case "KICK_OFF": return { title: "Bola rolando", detail: team, tone: "minor" };
    case "HALF_TIME": return { title: "Intervalo", detail: "Fim do primeiro tempo", tone: "phase" };
    case "SECOND_HALF": return { title: "Começa o 2º tempo", detail: "", tone: "phase" };
    case "FULL_TIME": return { title: "Apito final", detail: "", tone: "phase" };
    case "PENALTY": return { title: event.outcome === "SCORED" ? "Pênalti convertido" : "Pênalti perdido", detail: team, tone: "minor" };
    default: return { title: event.kind, detail: who, tone: "minor" };
  }
}

const MENTALITY_SHORT: Record<string, string> = { VERY_DEFENSIVE: "Muito defensiva", DEFENSIVE: "Defensiva", BALANCED: "Equilibrada", ATTACKING: "Ofensiva", VERY_ATTACKING: "Muito ofensiva" };
const PRESSURE_SHORT: Record<string, string> = { LOW: "pressão baixa", MEDIUM: "pressão média", HIGH: "pressão alta" };
const STYLE_SHORT: Record<string, string> = { POSSESSION: "posse", COUNTER: "contra-ataque", DIRECT: "jogo direto", SHORT_BUILDUP: "saída curta", WIDE: "pelas laterais" };

export function tacticSummary(t: { mentality: string; pressure: string; style: string }): string {
  return `${MENTALITY_SHORT[t.mentality] ?? t.mentality}, ${PRESSURE_SHORT[t.pressure] ?? t.pressure}, ${STYLE_SHORT[t.style] ?? t.style}`;
}

export const KEY_EVENTS = new Set(["GOAL", "SHOT", "SAVE", "CARD", "SUBSTITUTION", "TACTICS", "HALF_TIME", "SECOND_HALF", "FULL_TIME", "CORNER", "BIG_CHANCE", "PENALTY"]);

export function newKey(): string {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
}
