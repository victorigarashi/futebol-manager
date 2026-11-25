import type { InteractiveActionType, InteractiveView } from "../../../lib/api";
import { attackDir, inferType, predictTarget, type Aim } from "./gesture";

/**
 * Keyboard play for the decisive moments (no mouse, no touch): the same intent (direction,
 * power, action type) a drag produces, built from keys and the same physics forecast the
 * screen draws. Pure functions: the component only maps keys to them.
 *
 *   ← / →  rotate the aim          ↑ / ↓  more / less power
 *   Tab    next team-mate (power to reach him)     Shift+Tab  previous
 *   1–5    Auto / Pass / Loft / Carry / Shot       Enter or Space  play it     Esc  cancel
 */
export const ROTATE_STEP = Math.PI / 24;     // 7.5°
export const POWER_STEP = 0.05;

type Mode = InteractiveActionType | "AUTO";

function typed(view: InteractiveView, from: [number, number], ux: number, uy: number, power: number, mode: Mode): Aim {
  const type = view.opportunity?.kind === "PENALTY" ? "SHOT" : mode === "AUTO" ? inferType(view, from, ux, uy, power) : mode;
  return { ux, uy, power, type };
}

/** Starting aim when the coach's decision opens: straight at the rival goal, medium power. */
export function initialAim(view: InteractiveView, from: [number, number], mode: Mode): Aim {
  const { length: L, width: W } = view.pitch;
  const dir = attackDir(view);
  const dx = (dir > 0 ? L : 0) - from[0] * L, dy = W / 2 - from[1] * W;
  const n = Math.hypot(dx, dy) || 1;
  return typed(view, from, dx / n, dy / n, 0.4, mode);
}

export function rotateAim(view: InteractiveView, from: [number, number], aim: Aim, steps: number, mode: Mode): Aim {
  const a = Math.atan2(aim.uy, aim.ux) + steps * ROTATE_STEP;
  return typed(view, from, Math.cos(a), Math.sin(a), aim.power, mode);
}

export function adjustPower(view: InteractiveView, from: [number, number], aim: Aim, delta: number, mode: Mode): Aim {
  return typed(view, from, aim.ux, aim.uy, Math.max(0.05, Math.min(1, aim.power + delta)), mode);
}

export function retype(view: InteractiveView, from: [number, number], aim: Aim, mode: Mode): Aim {
  return typed(view, from, aim.ux, aim.uy, aim.power, mode);
}

/** Team-mates of the carrier ordered by angle around him (so Tab sweeps the pitch). */
export function mates(view: InteractiveView, from: [number, number]): { id: string; at: [number, number] }[] {
  const opp = view.opportunity;
  if (!opp) return [];
  const { length: L, width: W } = view.pitch;
  return opp.roster
    .map((p, i) => ({ p, at: opp.positions[i] }))
    .filter(({ p }) => p.team === "A" && p.role !== "GK" && p.id !== opp.carrier)
    .map(({ p, at }) => ({ id: p.id, at, angle: Math.atan2((at[1] - from[1]) * W, (at[0] - from[0]) * L) }))
    .sort((a, b) => a.angle - b.angle)
    .map(({ id, at }) => ({ id, at }));
}

/** Aim at a team-mate: direction to him and the power whose forecast reaches him (bisection on
 * the same predictTarget the screen uses). A long ball becomes a loft in AUTO. */
export function aimAtMate(view: InteractiveView, from: [number, number], target: [number, number], mode: Mode): Aim {
  const { length: L, width: W } = view.pitch;
  const dx = (target[0] - from[0]) * L, dy = (target[1] - from[1]) * W;
  const dist = Math.hypot(dx, dy) || 1;
  const ux = dx / dist, uy = dy / dist;
  const type: InteractiveActionType = mode === "AUTO" ? (dist > 30 * (L / 105) ? "LOFT" : "PASS") : mode;
  if (type === "SHOT") return typed(view, from, ux, uy, 0.7, mode);
  const reach = (power: number) => {
    const [tx, ty] = predictTarget(view, from, { ux, uy, power, type });
    return Math.hypot((tx - from[0]) * L, (ty - from[1]) * W);
  };
  let lo = 0.05, hi = 1;
  for (let i = 0; i < 24; i += 1) {
    const mid = (lo + hi) / 2;
    if (reach(mid) < dist) lo = mid; else hi = mid;
  }
  return { ux, uy, power: Math.round(((lo + hi) / 2) * 1000) / 1000, type };
}
