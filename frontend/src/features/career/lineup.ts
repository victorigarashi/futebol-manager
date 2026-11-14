import type { Formation, SquadPlayer } from "../../lib/api";

/** Same rule as the server's `effective_overall` (the server re-validates on save). */
export function fit(player: SquadPlayer, slotPosition: string): { rating: number; kind: "natural" | "secondary" | "improvised" } {
  if (player.position === slotPosition) return { rating: player.overall, kind: "natural" };
  if (player.secondary_positions?.includes(slotPosition)) return { rating: player.overall, kind: "secondary" };
  const penalty = player.position === "GK" || slotPosition === "GK" ? 12 : 6;
  return { rating: Math.max(1, player.overall - penalty), kind: "improvised" };
}

/** Greedy best XI for a formation: scarce positions first, natural fits preferred. */
export function autoPick(formation: Formation, players: SquadPlayer[]): Record<string, string> {
  const pool = [...players].sort((a, b) => b.overall - a.overall);
  const order: Record<string, number> = { GK: 0, ST: 1, DF: 2, MF: 3 };
  const result: Record<string, string> = {};
  for (const slot of [...formation.slots].sort((a, b) => order[a.position] - order[b.position])) {
    let best = -1;
    let bestRating = -1;
    const keepers = pool.some((p) => p.position === "GK");
    pool.forEach((player, index) => {
      // The server requires a real goalkeeper in goal; keepers never fill outfield slots.
      if (slot.position === "GK" && keepers && player.position !== "GK") return;
      if (slot.position !== "GK" && player.position === "GK" && pool.some((p) => p.position !== "GK")) return;
      const rating = fit(player, slot.position).rating;
      if (rating > bestRating) { best = index; bestRating = rating; }
    });
    if (best >= 0) result[slot.id] = pool.splice(best, 1)[0].id;
  }
  return result;
}

/** Keeps the players already chosen when switching formation, moving them to similar slots. */
export function carryOver(formation: Formation, previous: Record<string, string>, previousFormation: Formation | undefined, players: SquadPlayer[]): Record<string, string> {
  const byId = new Map(players.map((p) => [p.id, p]));
  const chosen = previousFormation ? previousFormation.slots.map((slot) => previous[slot.id]).filter(Boolean) : Object.values(previous);
  const remaining = chosen.map((id) => byId.get(id)).filter((p): p is SquadPlayer => Boolean(p));
  const result: Record<string, string> = {};
  for (const slot of formation.slots) {
    const index = remaining.findIndex((p) => fit(p, slot.position).kind !== "improvised");
    const pick = index >= 0 ? remaining.splice(index, 1)[0] : undefined;
    if (pick) result[slot.id] = pick.id;
  }
  for (const slot of formation.slots) {
    if (!result[slot.id] && remaining.length) result[slot.id] = remaining.shift()!.id;
  }
  const used = new Set(Object.values(result));
  const filler = autoPick(formation, players.filter((p) => !used.has(p.id)));
  for (const slot of formation.slots) if (!result[slot.id] && filler[slot.id]) result[slot.id] = filler[slot.id];
  return result;
}

export function teamStrength(formation: Formation, assignments: Record<string, string>, players: SquadPlayer[]) {
  const byId = new Map(players.map((p) => [p.id, p]));
  const sectors: Record<string, number[]> = { GK: [], DF: [], MF: [], ST: [] };
  let improvised = 0;
  for (const slot of formation.slots) {
    const player = byId.get(assignments[slot.id]);
    if (!player) continue;
    const result = fit(player, slot.position);
    if (result.kind === "improvised") improvised += 1;
    sectors[slot.position].push(result.rating);
  }
  const avg = (values: number[]) => values.length ? values.reduce((a, b) => a + b, 0) / values.length : 0;
  const all = Object.values(sectors).flat();
  return { overall: avg(all), defense: avg([...sectors.GK, ...sectors.DF]), midfield: avg(sectors.MF), attack: avg(sectors.ST), improvised };
}
