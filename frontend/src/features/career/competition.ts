import type { KnockoutView } from "../../lib/api";

type Kind = "PLAYOFF" | "CUP" | "TOURNAMENT";

const STAGES: Record<Kind, string[]> = { PLAYOFF: ["QF", "SF", "FINAL"], CUP: ["PRELIM", "R16", "QF", "SF", "FINAL"], TOURNAMENT: ["R16", "QF", "SF", "FINAL"] };
export const STAGE_LABEL: Record<string, string> = { PRELIM: "Fase preliminar", R16: "Oitavas de final", QF: "Quartas de final", SF: "Semifinal", FINAL: "Final" };

/** One competition read from the server's knockout state (nothing decided here). */
export function competitionOf(knockout: KnockoutView, kind: Kind) {
  const ties = Object.values(knockout.ties).filter((t) => t.competition === kind);
  const stages = STAGES[kind].filter((stage) => kind !== "TOURNAMENT" || ties.some((t) => t.stage === stage) || stageFollows(kind, stage, ties)).map((stage) => ({ stage, name: STAGE_LABEL[stage], ties: ties.filter((t) => t.stage === stage).sort((a, b) => a.order - b.order) }));
  const pending = knockout.rounds.find((r) => r.competition === kind && r.status === "PENDING");
  return { stages, ties, pending, currentStage: pending?.stage ?? null, legs: ties[0]?.legs ?? 1, draws: knockout.draws.filter((d) => d.competition === kind) };
}


/** A tournament shows the stages still to come after its first drawn stage. */
function stageFollows(kind: Kind, stage: string, ties: { stage: string }[]): boolean {
  const order = STAGES[kind];
  const first = order.findIndex((s) => ties.some((t) => t.stage === s));
  return first >= 0 && order.indexOf(stage) > first;
}
