import { readLocal, writeLocal } from "../../../../lib/storage";

/**
 * Each participant's own match experience (2D Arcade or 3D Imersivo) and graphics quality.
 * Kept in this browser only: it is purely a presentation choice, never sent to the server,
 * never shared with the rival and it never changes a result.
 */
export type Experience = "2D" | "3D";
export type QualityChoice = "auto" | "low" | "medium" | "high";
const EXP = "bm_match_experience", QUAL = "bm_match_quality";

export function readExperience(): Experience { return readLocal(EXP) === "3D" ? "3D" : "2D"; }
export function writeExperience(value: Experience) { writeLocal(EXP, value); window.dispatchEvent(new CustomEvent("bm-experience", { detail: value })); }
export function readQuality(): QualityChoice { const v = readLocal(QUAL); return v === "low" || v === "medium" || v === "high" ? v : "auto"; }
export function writeQuality(value: QualityChoice) { writeLocal(QUAL, value); }

/** "auto": a first guess from the device; the 3D view then adapts to the measured frame rate. */
export function autoQuality(): "low" | "medium" | "high" {
  const cores = navigator.hardwareConcurrency ?? 4;
  const memory = (navigator as unknown as { deviceMemory?: number }).deviceMemory ?? 4;
  const small = Math.min(window.screen?.width ?? 1280, window.screen?.height ?? 800) < 600;
  if (cores <= 4 || memory <= 3) return "low";
  if (small || cores <= 6) return "medium";
  return "high";
}
