import type { InteractiveActionType, InteractiveView } from "../../../lib/api";

/**
 * Pure geometry of the Modo Jogável screen (unit-testable).
 *
 * Normalised coordinates of the REAL pitch (0..1; each club attacks its own end and the
 * ends switch at half-time — the server already sends everything on the real pitch, so
 * nothing is mirrored here) are mapped to the canvas; on a portrait screen the pitch is rotated so the attack goes
 * up. Gestures are converted back to normalised units, so the same gesture produces the
 * same intent at any resolution or orientation.
 */
/** `mx`/`my`: margin around the touchlines as a fraction of the length/width (room for goals). */
export type Geometry = { width: number; height: number; portrait: boolean; pad: number; ratio?: number; mx?: number; my?: number };
export type Aim = { ux: number; uy: number; power: number; type: InteractiveActionType };

/** Pitch rectangle on the canvas (px). The scale is isotropic: px per metre is the same both ways. */
export function frame(g: Geometry): { w: number; h: number; ox: number; oy: number } {
  const ratio = g.ratio ?? 105 / 68;
  const mx = g.mx ?? 0, my = g.my ?? 0;
  const fullRatio = (ratio * (1 + 2 * mx)) / (1 + 2 * my);
  const availW = g.width - g.pad * 2, availH = g.height - g.pad * 2;
  if (g.portrait) {
    // Pitch length runs vertically.
    const fullH = Math.min(availH, availW * fullRatio), fullW = fullH / fullRatio;
    const h = fullH / (1 + 2 * mx), w = fullW / (1 + 2 * my);
    return { w, h, ox: (g.width - w) / 2, oy: (g.height - h) / 2 };
  }
  const fullW = Math.min(availW, availH * fullRatio), fullH = fullW / fullRatio;
  const w = fullW / (1 + 2 * mx), h = fullH / (1 + 2 * my);
  return { w, h, ox: (g.width - w) / 2, oy: (g.height - h) / 2 };
}

/** Pixels per metre (pitch length `L` metres). */
export function pxPerMetre(g: Geometry, L: number): number {
  const f = frame(g);
  return (g.portrait ? f.h : f.w) / L;
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
    // A shot: to the rival goal line along the gesture (or 30 m if it points away from it).
    const dir = attackDir(view);
    const fx = from[0] * L, fy = from[1] * W;
    const goalX = dir > 0 ? L : 0;
    const towards = aim.ux * dir;
    metres = towards > 0.05 ? Math.min(60 * s, Math.abs(goalX - fx) / towards) : 30 * s;
    return [(fx + aim.ux * metres) / L, (fy + aim.uy * metres) / W];
  }
  return [from[0] + (aim.ux * metres) / L, from[1] + (aim.uy * metres) / W];
}

/** +1 when the attacking club attacks towards x = 1 in this half, -1 towards x = 0. */
export function attackDir(view: InteractiveView): 1 | -1 {
  return view.opportunity?.right === false ? -1 : 1;
}

/** Automatic action type: a shot when the gesture points at the goal mouth from a shooting range. */
export function inferType(view: InteractiveView, from: [number, number], ux: number, uy: number): InteractiveActionType {
  const { length: L, width: W, goal } = view.pitch;
  const dir = attackDir(view);
  const fx = from[0] * L, fy = from[1] * W;
  const toGoal = dir > 0 ? L - fx : fx;
  const forward = ux * dir;
  if (view.opportunity?.kind === "PENALTY") return "SHOT";
  if (forward > 0.2 && toGoal < 32 * (L / 105)) {
    const yAtLine = fy + (uy / forward) * toGoal;
    if (Math.abs(yAtLine - W / 2) <= goal / 2 + 2) return "SHOT";
  }
  const wide = Math.min(fy, W - fy) < 14 * (W / 68) && toGoal < 25 * (L / 105);
  if (wide && Math.abs(uy) > 0.45) return "LOFT";
  return "PASS";
}

/** Drag (two points on the real pitch, normalised) -> intent. Identical for both renderers. */
export function aimFromDrag(view: InteractiveView, from: [number, number], start: [number, number], end: [number, number], mode: InteractiveActionType | "AUTO"): Aim | null {
  const dx = (end[0] - start[0]) * view.pitch.length, dy = (end[1] - start[1]) * view.pitch.width;
  const length = Math.hypot(dx, dy);
  if (length < 1.2) return null;
  // Power = drag length relative to 40% of the pitch length.
  const power = Math.max(0.05, Math.min(1, length / (view.pitch.length * 0.4)));
  const type = view.opportunity?.kind === "PENALTY" ? "SHOT" : mode === "AUTO" ? inferType(view, from, dx / length, dy / length) : mode;
  return { ux: dx / length, uy: dy / length, power, type };
}
