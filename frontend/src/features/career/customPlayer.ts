import type { CustomPlayerRules } from "../../lib/api";

/** The overall the server will compute for a created player (same weights, fetched from
 * /custom-players/rules): a weighted mean of the attributes that matter for the position. */
export function previewOverall(rules: CustomPlayerRules, position: string, attributes: Record<string, number>): number {
  const weights = rules.weights[position] ?? {};
  return Math.round(Object.entries(weights).reduce((sum, [key, w]) => sum + (attributes[key] ?? 0) * w, 0));
}
