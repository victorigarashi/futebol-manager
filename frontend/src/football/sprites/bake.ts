import * as THREE from "three";
import { createAthlete, type Athlete } from "../athlete/athlete";
import { REGIONS, type Region } from "../athlete/body";
import type { KitSpec, Pattern } from "../athlete/kit";
import type { Pose } from "../athlete/rig";
import { CLIPS, samplePose } from "../anim/clips";

/**
 * Sprite pipeline (research prototype):
 *   lofted athlete -> rig -> clip -> orthographic camera (elevated, 8 directions)
 *   -> two passes per cell (lit SHADE, unlit region MASK) -> one mask atlas
 *   -> runtime recolour per kit (one atlas serves every team; no per-team atlases).
 *
 * Mask atlas pixel: R = shade (0-255), G = sprite region id * 20 + 10, B = 0, A = coverage.
 * Kit patterns survive: the mask pass renders the shirt texture with ID colours, so stripes,
 * hoops etc. become the "secondary" region. One atlas per pattern family.
 */
export const SPRITE_REGIONS = ["skin", "primary", "secondary", "shorts", "socks", "boots", "hair", "gloves", "dark"] as const;
export type SpriteRegion = typeof SPRITE_REGIONS[number];
const ID_COLOURS = ["#ff0000", "#00ff00", "#0000ff", "#ffff00", "#ff00ff", "#00ffff", "#ff8000", "#8000ff", "#000000"];
const BODY_TO_SPRITE: Record<Region, SpriteRegion> = {
  skin: "skin", shirt: "primary", trim: "secondary", shorts: "shorts", shortsTrim: "secondary", socks: "socks", sockTrim: "secondary",
  boots: "boots", sole: "dark", hair: "hair", eye: "dark", brow: "hair", lips: "skin", gloves: "gloves",
};
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
export type BakeOptions = { cell: number; elevationDeg: number; pattern: Pattern; outline: boolean; posterize: number; onProgress?: (k: number) => void };

function maskKit(pattern: Pattern): KitSpec {
  // primary/secondary in ID colours; the number is drawn in the secondary ID too
  return { primary: ID_COLOURS[1], secondary: ID_COLOURS[2], pattern, shorts: ID_COLOURS[3], socks: ID_COLOURS[4], number: 10, numberColor: ID_COLOURS[2] };
}

export async function bakeAtlas(opts: BakeOptions): Promise<{ canvas: HTMLCanvasElement; meta: AtlasMeta }> {
  const t0 = performance.now();
  const C = opts.cell;
  const renderer = new THREE.WebGLRenderer({ antialias: false, alpha: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(1);
  renderer.setSize(C * 2, C * 2);   // render at 2x, downsample when packing (clean edges)
  renderer.setClearColor(0x000000, 0);
  const scene = new THREE.Scene();
  const metres = 2.7;
  const cam = new THREE.OrthographicCamera(-metres / 2, metres / 2, metres / 2, -metres / 2, 0.1, 50);
  const el = (opts.elevationDeg * Math.PI) / 180;
  const centre = new THREE.Vector3(0, 0.95, 0);
  cam.position.set(0, centre.y + Math.sin(el) * 10, Math.cos(el) * 10);
  cam.lookAt(centre);
  const hemi = new THREE.HemisphereLight("#ffffff", "#808080", 1.4);
  const sun = new THREE.DirectionalLight("#ffffff", 2.2);
  sun.position.set(-3, 8, 5);
  scene.add(hemi, sun);
  const make = (keeper: boolean): { shade: Athlete; mask: Athlete } => {
    const look = { skin: "#ffffff", hair: "#ffffff", hairStyle: 0, boots: "#ffffff", build: 0.5 };
    const white = Object.fromEntries(REGIONS.map((r) => [r, "#ffffff"])) as Record<Region, string>;
    const shade = createAthlete({ kit: { primary: "#ffffff", secondary: "#ffffff", pattern: "plain", shorts: "#fff", socks: "#fff", number: 0, numberColor: "#ffffff" }, keeper, detail: "medium", look, regionColours: white });
    const ids = Object.fromEntries(REGIONS.map((r) => [r, ID_COLOURS[SPRITE_REGIONS.indexOf(BODY_TO_SPRITE[r])]])) as Record<Region, string>;
    ids.shirt = "#ffffff";   // the shirt comes from the mask texture (primary/secondary IDs)
    const mask = createAthlete({ kit: maskKit(opts.pattern), keeper, detail: "medium", look, regionColours: ids });
    // the mask pass must be unlit and exact
    const m = mask.mesh.material as THREE.MeshStandardMaterial;
    mask.mesh.material = new THREE.MeshBasicMaterial({ map: m.map, vertexColors: true, toneMapped: false });
    // the mask athlete's ambient-occlusion tint must not change the IDs: rebuild colours without AO
    const col = mask.mesh.geometry.getAttribute("color") as THREE.BufferAttribute;
    const reg = mask.mesh.geometry.getAttribute("region") as THREE.BufferAttribute | undefined;
    if (reg) for (let i = 0; i < col.count; i += 1) { const c = new THREE.Color(ids[REGIONS[Math.round(reg.getX(i))]]); col.setXYZ(i, c.r, c.g, c.b); }
    col.needsUpdate = true;
    return { shade, mask };
  };
  const outfield = make(false), keeperA = make(true);
  const totalRows = SPRITE_ANIMS.length * DIRECTIONS.length;
  const cols = Math.max(...SPRITE_ANIMS.map((a) => a.frames));
  // reflow rows into side-by-side blocks so the atlas stays under 4096 px on phones (square-ish)
  const blocks = Math.max(1, Math.round(Math.sqrt(totalRows / cols)));
  const atlas = document.createElement("canvas");
  atlas.width = blocks * cols * C; atlas.height = Math.ceil(totalRows / blocks) * C;
  const ag = atlas.getContext("2d", { willReadFrequently: true })!;
  const cellCanvas = document.createElement("canvas");
  cellCanvas.width = cellCanvas.height = C;
  const cg = cellCanvas.getContext("2d", { willReadFrequently: true })!;
  const idRGB = ID_COLOURS.map((h) => new THREE.Color(h)).map((c) => [c.r * 255, c.g * 255, c.b * 255]);
  const metaAnims: AtlasMeta["anims"] = [];
  let done = 0;
  const grab = (): ImageData => { cg.clearRect(0, 0, C, C); cg.drawImage(renderer.domElement, 0, 0, C * 2, C * 2, 0, 0, C, C); return cg.getImageData(0, 0, C, C); };
  const grabNearest = (): ImageData => {
    // mask: nearest-neighbour downsample (no blended IDs)
    const big = document.createElement("canvas"); big.width = big.height = C * 2;
    const bg = big.getContext("2d", { willReadFrequently: true })!; bg.drawImage(renderer.domElement, 0, 0);
    const src = bg.getImageData(0, 0, C * 2, C * 2).data;
    const out = new ImageData(C, C);
    for (let y = 0; y < C; y += 1) for (let x = 0; x < C; x += 1) { const si = ((y * 2) * C * 2 + x * 2) * 4, di = (y * C + x) * 4; out.data[di] = src[si]; out.data[di + 1] = src[si + 1]; out.data[di + 2] = src[si + 2]; out.data[di + 3] = src[si + 3]; }
    return out;
  };
  for (let ai = 0; ai < SPRITE_ANIMS.length; ai += 1) {
    const A = SPRITE_ANIMS[ai];
    const def = CLIPS[A.clip];
    const pair = A.keeper ? keeperA : outfield;
    const from = A.from ?? 0, to = A.to ?? (def.meta.loop ? 1 - 1 / A.frames : 1);
    let contactFrame: number | null = null;
    if (def.meta.contact) { const k = (def.meta.contact.u - from) / (to - from) * (A.frames - 1); contactFrame = Math.round(Math.max(0, Math.min(A.frames - 1, k))); }
    metaAnims.push({ name: A.name, frames: A.frames, fps: A.fps, row0: ai * DIRECTIONS.length, contactFrame });
    for (let d = 0; d < DIRECTIONS.length; d += 1) {
      for (let f = 0; f < A.frames; f += 1) {
        const u = A.frames === 1 ? from : from + (to - from) * (f / (A.frames - 1 + (def.meta.loop ? 1 : 0)));
        const pose: Pose = samplePose(def, u);
        const yaw = (d * Math.PI) / 4;
        const out: ImageData[] = [];
        for (const which of ["shade", "mask"] as const) {
          const ath = pair[which];
          scene.add(ath.group);
          ath.group.rotation.set(0, yaw, A.roll ? -Math.min(1.35, Math.max(0, (u - 0.2) / 0.5) * 1.35) : 0, "YXZ");
          ath.group.position.set(0, A.roll ? Math.max(0, 0.35 - (u - 0.2) * 0.2) : 0, 0);
          ath.setPose(pose);
          renderer.toneMapping = which === "mask" ? THREE.NoToneMapping : THREE.ACESFilmicToneMapping;
          renderer.render(scene, cam);
          out.push(which === "shade" ? grab() : grabNearest());
          scene.remove(ath.group);
        }
        // pack: R = posterized shade, G = region id, A = coverage
        const [sh, mk] = out;
        const px = new ImageData(C, C);
        for (let i = 0; i < C * C; i += 1) {
          const a = sh.data[i * 4 + 3];
          if (a < 8) continue;
          let lum = (sh.data[i * 4] * 0.3 + sh.data[i * 4 + 1] * 0.59 + sh.data[i * 4 + 2] * 0.11) / Math.max(1, a / 255);
          if (opts.posterize > 1) lum = Math.round((lum / 255) * (opts.posterize - 1)) / (opts.posterize - 1) * 255;
          // region: nearest ID colour of the mask pixel (or of the nearest covered neighbour on edges)
          const ma = mk.data[i * 4 + 3];
          let r = mk.data[i * 4], g = mk.data[i * 4 + 1], b = mk.data[i * 4 + 2];
          if (ma < 128) { const j = nearestCovered(mk, C, i); if (j >= 0) { r = mk.data[j * 4]; g = mk.data[j * 4 + 1]; b = mk.data[j * 4 + 2]; } }
          let best = 0, bd = Infinity;
          for (let k = 0; k < idRGB.length; k += 1) { const dd = (idRGB[k][0] - r) ** 2 + (idRGB[k][1] - g) ** 2 + (idRGB[k][2] - b) ** 2; if (dd < bd) { bd = dd; best = k; } }
          px.data[i * 4] = Math.min(255, lum); px.data[i * 4 + 1] = best * 20 + 10; px.data[i * 4 + 2] = 0; px.data[i * 4 + 3] = a;
        }
        const [cx, cy] = cellXY({ cell: C, cols, blocks }, ai * DIRECTIONS.length + d, f);
        ag.putImageData(px, cx, cy);
        done += 1;
      }
      opts.onProgress?.(done / (SPRITE_ANIMS.reduce((s, a) => s + a.frames, 0) * DIRECTIONS.length));
      await new Promise((r) => setTimeout(r, 0));
    }
  }
  for (const p of [outfield, keeperA]) { p.shade.dispose(); p.mask.dispose(); }
  renderer.dispose();
  // anchor = projection of the feet (origin) in the cell
  const proj = new THREE.Vector3(0, 0, 0).project(cam);
  const anchor: [number, number] = [Math.round((proj.x + 1) / 2 * C), Math.round((1 - proj.y) / 2 * C)];
  return { canvas: atlas, meta: { cell: C, cols, rows: totalRows, blocks, elevationDeg: opts.elevationDeg, metresPerCell: metres, anchor, directions: DIRECTIONS, anims: metaAnims, regions: SPRITE_REGIONS, bakeMs: Math.round(performance.now() - t0), pattern: opts.pattern } };
}

/** Pixel position of (row, frame) in the atlas (rows are reflowed into `blocks` columns of `cols` frames). */
export function cellXY(m: { cell: number; cols: number; blocks: number }, row: number, frame: number): [number, number] {
  return [((row % m.blocks) * m.cols + frame) * m.cell, Math.floor(row / m.blocks) * m.cell];
}

function nearestCovered(img: ImageData, C: number, i: number): number {
  const x = i % C, y = Math.floor(i / C);
  for (let r = 1; r <= 2; r += 1) for (let dy = -r; dy <= r; dy += 1) for (let dx = -r; dx <= r; dx += 1) {
    const xx = x + dx, yy = y + dy;
    if (xx < 0 || yy < 0 || xx >= C || yy >= C) continue;
    const j = yy * C + xx;
    if (img.data[j * 4 + 3] >= 128) return j;
  }
  return -1;
}

export type SpritePalette = Record<SpriteRegion, string>;
/** Recolour the mask atlas for one kit/look (one pass over the pixels; done once per team). */
export function recolour(atlas: HTMLCanvasElement, pal: SpritePalette, outline = true): HTMLCanvasElement {
  const out = document.createElement("canvas");
  out.width = atlas.width; out.height = atlas.height;
  const src = atlas.getContext("2d", { willReadFrequently: true })!.getImageData(0, 0, atlas.width, atlas.height);
  const dst = new ImageData(atlas.width, atlas.height);
  const cols = SPRITE_REGIONS.map((r) => new THREE.Color(pal[r])).map((c) => [c.r * 255, c.g * 255, c.b * 255]);
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
