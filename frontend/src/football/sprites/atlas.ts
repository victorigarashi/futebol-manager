import type { KitSpec, Pattern } from "../athlete/kit";

/** Sprite atlas layout, palettes and runtime recolour. No three.js: this is what the 2D
 * match renderer loads up front; ./bake (WebGL) is only fetched if a pre-baked atlas is missing. */
export const SPRITE_REGIONS = ["skin", "primary", "secondary", "shorts", "socks", "boots", "hair", "gloves", "dark"] as const;
export type SpriteRegion = typeof SPRITE_REGIONS[number];
export const DIRECTIONS = ["S", "SE", "E", "NE", "N", "NW", "W", "SW"] as const;
export type AnimSpec = { name: string; clip: string; frames: number; fps: number; from?: number; to?: number; keeper?: boolean; roll?: boolean };
export const SPRITE_ANIMS: AnimSpec[] = [
  { name: "idle", clip: "idle", frames: 4, fps: 4 },
  { name: "run", clip: "run", frames: 8, fps: 12 },
  { name: "sprint", clip: "sprint", frames: 8, fps: 16 },
  { name: "dribble", clip: "dribble", frames: 8, fps: 12 },
  { name: "pass", clip: "pass_short", frames: 6, fps: 12 },
  { name: "shot", clip: "shot", frames: 8, fps: 14 },
  { name: "receive", clip: "receive", frames: 6, fps: 10 },
  { name: "header", clip: "header", frames: 8, fps: 12 },
  { name: "celebrate", clip: "celebrate", frames: 8, fps: 8 },
  { name: "gk_ready", clip: "gk_ready", frames: 4, fps: 6, keeper: true },
  { name: "gk_dive", clip: "gk_dive_low", frames: 8, fps: 12, keeper: true, roll: true, from: 0.1, to: 0.95 },
];
export type AtlasMeta = {
  cell: number; cols: number; rows: number; blocks: number; elevationDeg: number; metresPerCell: number; anchor: [number, number];
  directions: readonly string[]; anims: { name: string; frames: number; fps: number; row0: number; contactFrame: number | null }[];
  regions: readonly string[]; bakeMs: number; pattern: Pattern;
};
/** Pixel position of (row, frame) in the atlas (rows are reflowed into `blocks` columns of `cols` frames). */
export function cellXY(m: { cell: number; cols: number; blocks: number }, row: number, frame: number): [number, number] {
  return [((row % m.blocks) * m.cols + frame) * m.cell, Math.floor(row / m.blocks) * m.cell];
}

/** "#rrggbb" -> linear RGB 0..1 (same as three.js Color with colour management: sRGB hex in, linear out). */
export function linearRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.replace("#", "").padEnd(6, "0").slice(0, 6), 16);
  const lin = (v: number) => { const c = v / 255; return c <= 0.04045 ? c * 0.0773993808 : Math.pow(c * 0.9478672986 + 0.0521327014, 2.4); };
  return [lin((n >> 16) & 255), lin((n >> 8) & 255), lin(n & 255)];
}

export type SpritePalette = Record<SpriteRegion, string>;
/** Recolour the mask atlas for one kit/look (one pass over the pixels; done once per team). */
export function recolour(atlas: HTMLCanvasElement, pal: SpritePalette, outline = true): HTMLCanvasElement {
  const out = document.createElement("canvas");
  out.width = atlas.width; out.height = atlas.height;
  const src = atlas.getContext("2d", { willReadFrequently: true })!.getImageData(0, 0, atlas.width, atlas.height);
  const dst = new ImageData(atlas.width, atlas.height);
  const cols = SPRITE_REGIONS.map((r) => linearRgb(pal[r]).map((v) => v * 255));
  const W = atlas.width;
  for (let i = 0; i < src.data.length; i += 4) {
    const a = src.data[i + 3];
    if (!a) continue;
    const id = Math.max(0, Math.min(cols.length - 1, Math.round((src.data[i + 1] - 10) / 20)));
    const s = src.data[i] / 255;
    const k = 0.25 + s * 0.95;   // keep some colour in the shadows
    dst.data[i] = Math.min(255, cols[id][0] * k); dst.data[i + 1] = Math.min(255, cols[id][1] * k); dst.data[i + 2] = Math.min(255, cols[id][2] * k); dst.data[i + 3] = a;
  }
  if (outline) {
    // 1 px dark outline around the silhouette (sprite readability on grass)
    const alpha = new Uint8Array(src.data.length / 4);
    for (let i = 0; i < alpha.length; i += 1) alpha[i] = src.data[i * 4 + 3];
    for (let i = 0; i < alpha.length; i += 1) {
      if (alpha[i] >= 128) continue;
      const x = i % W;
      const n = (alpha[i - 1] >= 128 && x > 0) || (alpha[i + 1] >= 128 && x < W - 1) || alpha[i - W] >= 128 || alpha[i + W] >= 128;
      if (n) { dst.data[i * 4] = 18; dst.data[i * 4 + 1] = 22; dst.data[i * 4 + 2] = 20; dst.data[i * 4 + 3] = 170; }
    }
  }
  out.getContext("2d")!.putImageData(dst, 0, 0);
  return out;
}

export function paletteFor(kit: KitSpec, skin: string, hair: string, boots: string, keeper = false): SpritePalette {
  return { skin, primary: kit.primary, secondary: kit.secondary, shorts: kit.shorts, socks: kit.socks, boots, hair, gloves: keeper ? "#f4f4f4" : skin, dark: "#1a1a1a" };
}
/** Direction index (0 = S/facing camera) from a screen-space velocity (x right, y down). */
export function directionIndex(vx: number, vy: number): number {
  const a = Math.atan2(vx, vy);   // 0 = moving down the screen (towards the camera)
  return ((Math.round(a / (Math.PI / 4)) % 8) + 8) % 8;
}
