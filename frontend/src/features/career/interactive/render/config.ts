/**
 * Visual configuration of the Modo Jogável screen. Purely cosmetic: nothing here can
 * change a result (physics and rules live on the server, backend/app/domain/highlights.py).
 */
export const VISUAL = {
  /** Canvas margin around the touchlines, in metres (room for the goals and nets). */
  marginMetres: 3.2,
  goalDepthMetres: 2.0,
  /** Sprite height in pitch metres (stylised ~2.2x a 1.8 m athlete), clamped in px. */
  playerHeight: { metres: 4.4, min: 30, max: 84 },
  ballRadius: { perPlayerHeight: 0.15, min: 3.2 },
  /** One stride every this many metres run (leg cycle). */
  strideMetres: 1.9,
  kickPoseSeconds: 0.28,
  tacklePoseSeconds: 0.45,
  divePoseSeconds: 0.7,
  headerPoseSeconds: 0.4,
  celebrateSeconds: 2.4,
  netRippleSeconds: 1.1,
  /** Playback never lags the server's official time by more than this (catch-up after latency). */
  maxPlaybackLag: 0.45,
  grass: { base: "#2f8f3f", light: "#36a047", dark: "#28803a", outside: "#246f33", stripes: 14 },
  line: "rgba(255,255,255,0.9)",
  aim: { PASS: "#c6f24e", LOFT: "#7cc8ff", CARRY: "#ffd166", SHOT: "#ff6b6b", invalid: "#ff4d4f" },
  skin: ["#f1c9a5", "#e0ac83", "#c68a5e", "#a8693f", "#8a5530", "#6b3f22", "#4f2d18"],
  hair: ["#1b120c", "#2b1a10", "#4a2e16", "#6b4423", "#c8a165", "#111111", "#3a2a1f"],
  keeperKits: { A: "#f5b83d", D: "#9b6bff" },
  boots: ["#111111", "#f2f2f2", "#ff7a00", "#1e6bff", "#e6007e"],
} as const;

/** Deterministic small hash (same look for a player on every screen). */
export function hashOf(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i += 1) { h ^= text.charCodeAt(i); h = Math.imul(h, 16777619); }
  return h >>> 0;
}

export function shade(hex: string, amount: number): string {
  const value = hex.replace("#", "");
  const n = parseInt(value.length === 3 ? value.split("").map((c) => c + c).join("") : value, 16);
  const ch = (shift: number) => {
    const c = (n >> shift) & 255;
    const v = amount >= 0 ? c + (255 - c) * amount : c * (1 + amount);
    return Math.max(0, Math.min(255, Math.round(v)));
  };
  return `rgb(${ch(16)},${ch(8)},${ch(0)})`;
}
