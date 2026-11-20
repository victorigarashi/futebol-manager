import type { InteractiveActionType, InteractiveView } from "../../../lib/api";

/**
 * Pure geometry of the Modo Jogável screen (unit-testable).
 *
 * Normalised pitch coordinates (0..1, the attacking side always attacks towards x = 1)
 * are mapped to the canvas; on a portrait screen the pitch is rotated so the attack goes
 * up. Gestures are converted back to normalised units, so the same gesture produces the
 * same intent at any resolution or orientation.
 */
export type Geometry = { width: number; height: number; portrait: boolean; pad: number; ratio?: number };
export type Aim = { ux: number; uy: number; power: number; type: InteractiveActionType };

function frame(g: Geometry): { w: number; h: number; ox: number; oy: number } {
  const ratio = g.ratio ?? 105 / 68;
  const availW = g.width - g.pad * 2, availH = g.height - g.pad * 2;
  if (g.portrait) {
    // Pitch length runs vertically.
    const h = Math.min(availH, availW * ratio), w = h / ratio;
    return { w, h, ox: (g.width - w) / 2, oy: (g.height - h) / 2 };
  }
  const w = Math.min(availW, availH * ratio), h = w / ratio;
  return { w, h, ox: (g.width - w) / 2, oy: (g.height - h) / 2 };
}

export function toScreen(g: Geometry, nx: number, ny: number): [number, number] {
  const f = frame(g);
  if (g.portrait) return [f.ox + ny * f.w, f.oy + (1 - nx) * f.h];
  return [f.ox + nx * f.w, f.oy + ny * f.h];
}

export function fromScreen(g: Geometry, sx: number, sy: number): [number, number] {
  const f = frame(g);
  if (g.portrait) return [1 - (sy - f.oy) / f.h, (sx - f.ox) / f.w];
  return [(sx - f.ox) / f.w, (sy - f.oy) / f.h];
}

/** Where the action is aimed (normalised), mirroring the server's formulas (docs/MODO_JOGAVEL.md). */
export function predictTarget(view: InteractiveView, from: [number, number], aim: Aim): [number, number] {
  const { length: L, width: W } = view.pitch;
  const s = L / 105;
  const p = view.physics;
  let metres: number;
  if (aim.type === "PASS") { const v0 = p.pass[0] + p.pass[1] * aim.power; metres = (v0 * v0) / (2 * p.decel); }
  else if (aim.type === "LOFT") metres = (p.loft_range[0] + p.loft_range[1] * aim.power) * s;
  else if (aim.type === "CARRY") metres = (p.carry[0] + p.carry[1] * aim.power) * s;
  else {
    // A shot: to the goal line along the gesture (or 30 m if it points away from goal).
    const fx = from[0] * L, fy = from[1] * W;
    metres = aim.ux > 0.05 ? Math.min(60 * s, (L - fx) / aim.ux) : 30 * s;
    return [(fx + aim.ux * metres) / L, (fy + aim.uy * metres) / W];
  }
  return [from[0] + (aim.ux * metres) / L, from[1] + (aim.uy * metres) / W];
}

/** Automatic action type: a shot when the gesture points at the goal mouth from a shooting range. */
export function inferType(view: InteractiveView, from: [number, number], ux: number, uy: number): InteractiveActionType {
  const { length: L, width: W, goal } = view.pitch;
  const fx = from[0] * L, fy = from[1] * W;
  const toGoal = L - fx;
  if (view.opportunity?.kind === "PENALTY") return "SHOT";
  if (ux > 0.2 && toGoal < 32 * (L / 105)) {
    const yAtLine = fy + (uy / ux) * toGoal;
    if (Math.abs(yAtLine - W / 2) <= goal / 2 + 2) return "SHOT";
  }
  const wide = Math.min(fy, W - fy) < 14 * (W / 68) && toGoal < 25 * (L / 105);
  if (wide && Math.abs(uy) > 0.45) return "LOFT";
  return "PASS";
}
