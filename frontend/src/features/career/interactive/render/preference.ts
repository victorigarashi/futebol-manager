import { readLocal, writeLocal } from "../../../../lib/storage";

/**
 * Each participant's own match experience (2D Arcade or 3D Imersivo) and graphics quality.
 * Kept in this browser only: it is purely a presentation choice, never sent to the server,
 * never shared with the rival and it never changes a result.
 */
export type Experience = "2D" | "3D";
export type QualityChoice = "auto" | "low" | "medium" | "high";
const EXP = "bm_match_experience", QUAL = "bm_match_quality", SHADOWS = "bm_match_shadows", FPS = "bm_match_fps";

export function readExperience(): Experience { return readLocal(EXP) === "3D" ? "3D" : "2D"; }
export function writeExperience(value: Experience) { writeLocal(EXP, value); window.dispatchEvent(new CustomEvent("bm-experience", { detail: value })); }
export function readQuality(): QualityChoice { const v = readLocal(QUAL); return v === "low" || v === "medium" || v === "high" ? v : "auto"; }
export function writeQuality(value: QualityChoice) { writeLocal(QUAL, value); }

/** Shadows on/off (3D only); on by default, saved locally like the rest of the presentation. */
export function readShadows(): boolean { return readLocal(SHADOWS) !== "0"; }
export function writeShadows(on: boolean) { writeLocal(SHADOWS, on ? "1" : "0"); }

/** Optional frame-rate cap for the match loop; 0 = free. */
export function readFpsCap(): 0 | 30 | 60 | 120 {
  const v = Number(readLocal(FPS));
  return v === 30 || v === 60 || v === 120 ? v : 0;
}
export function writeFpsCap(value: number) { writeLocal(FPS, String(value)); }

/** "auto": a first guess from the device; the 3D view then adapts to the measured frame rate. */
export function autoQuality(): "low" | "medium" | "high" {
  const cores = navigator.hardwareConcurrency ?? 4;
  const memory = (navigator as unknown as { deviceMemory?: number }).deviceMemory ?? 4;
  const small = Math.min(window.screen?.width ?? 1280, window.screen?.height ?? 800) < 600;
  if (cores <= 4 || memory <= 3) return "low";
  if (small || cores <= 6) return "medium";
  return "high";
}
