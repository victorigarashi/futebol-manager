import type { Pattern } from "../../../../football/athlete/kit";
import { BOOT_COLOURS, HAIR_COLOURS, SKIN_TONES } from "../../../../football/athlete/palette";
import { cellXY, directionIndex, paletteFor, recolour, type AtlasMeta } from "../../../../football/sprites/atlas";
import type { Geometry } from "../gesture";
import { hashOf, VISUAL } from "./config";
import { ACT, type ScenePlayer } from "./presentation";
import type { Kit } from "./renderer2d";

/**
 * V8 2D athletes: sprites rendered FROM the 3D athlete (same body, same clips), 8 directions,
 * one mask atlas per shirt pattern recoloured per team and look (football/sprites/bake.ts).
 * The frame of the run cycle advances with the OFFICIAL distance run (no sliding), action
 * frames follow the server cues, the keeper dive follows his real displacement.
 *
 * The bake needs WebGL; until it is ready (or without WebGL) the V6 vector sprites draw.
 */
type Bank = { meta: AtlasMeta; atlas: HTMLCanvasElement };
const banks = new Map<Pattern, Bank | "pending" | "failed">();
const tinted = new Map<string, HTMLCanvasElement>();
const progress: Record<string, number> = {};
const queue: (() => void)[] = [];
let working = false;

function pump() {
  if (working) return;
  const job = queue.shift();
  if (!job) return;
  working = true;
  // One recolour/bake per idle slot: never a long freeze in the middle of a play.
  const run = () => { try { job(); } finally { working = false; pump(); } };
  const idle = (window as unknown as { requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => void }).requestIdleCallback;
  if (idle) idle(run, { timeout: 250 }); else window.setTimeout(run, 16);
}

function patternOf(kit: Kit): Pattern {
  return kit.pattern === "stripes" || kit.pattern === "hoops" || kit.pattern === "sash" ? kit.pattern : "plain";
}

async function loadStatic(pattern: Pattern): Promise<Bank> {
  const base = `${import.meta.env.BASE_URL ?? "/"}sprites/atlas-${pattern}`;
  const meta = await fetch(`${base}.json`).then((r) => { if (!r.ok) throw new Error("no atlas"); return r.json() as Promise<AtlasMeta>; });
  const img = new Image();
  img.src = `${base}.png`;
  await img.decode();
  const atlas = document.createElement("canvas");
  atlas.width = img.naturalWidth; atlas.height = img.naturalHeight;
  atlas.getContext("2d", { willReadFrequently: true })!.drawImage(img, 0, 0);
  return { atlas, meta };
}

function bank(pattern: Pattern): Bank | null {
  const b = banks.get(pattern);
  if (b && b !== "pending" && b !== "failed") return b;
  if (!b) {
    banks.set(pattern, "pending");
    // Pre-baked atlas (public/sprites, scripts/bake-sprites.cjs): loads in milliseconds.
    // Fallback: bake it here from the 3D athlete (needs WebGL; a few seconds).
    loadStatic(pattern).then((b2) => banks.set(pattern, b2)).catch(() => {
      queue.push(() => {
        import("../../../../football/sprites/bake").then(({ bakeAtlas }) => bakeAtlas({ cell: 64, elevationDeg: 56, pattern, outline: true, posterize: 6, onProgress: (k) => { progress[pattern] = k; } })
          .then(({ canvas, meta }) => banks.set(pattern, { atlas: canvas, meta }))
          .catch(() => banks.set(pattern, "failed")))
          .catch(() => banks.set(pattern, "failed"));     // bake module unavailable (offline): vector sprites
      });
      pump();
    });
  }
  return null;
}

function sheetFor(p: ScenePlayer, kit: Kit): { sheet: HTMLCanvasElement; meta: AtlasMeta } | null {
  const wear = p.keeper ? (kit.gk ?? { shirt: VISUAL.keeperKits[p.team], shorts: "#2a2a33", socks: VISUAL.keeperKits[p.team], trim: "#ffffff" }) : kit;
  const pattern = p.keeper ? "plain" : patternOf(wear);
  const b = bank(pattern);
  if (!b) return null;
  // Memory budget: an atlas is ~11.8 MB in RGBA, so a team has TWO looks (skin/hair/boots)
  // plus the keeper: at most 6 recoloured sheets per match (~70 MB), never one per player.
  const look = p.keeper ? 0 : hashOf(p.id) % 2;
  const seed = hashOf(wear.shirt + look);
  const skin = SKIN_TONES[(seed >>> 3) % SKIN_TONES.length];
  const hair = HAIR_COLOURS[(seed >>> 7) % HAIR_COLOURS.length];
  const boots = BOOT_COLOURS[(seed >>> 11) % BOOT_COLOURS.length];
  const key = `${pattern}|${wear.shirt}|${wear.trim}|${wear.shorts}|${wear.socks}|${p.keeper ? "gk" : look}|${skin}|${hair}|${boots}`;
  const hit = tinted.get(key);
  if (hit) return { sheet: hit, meta: b.meta };
  if (!tinted.has(key + "#q")) {
    tinted.set(key + "#q", b.atlas);
    queue.push(() => {
      const kitSpec = { primary: wear.shirt, secondary: wear.trim, pattern, shorts: wear.shorts, socks: wear.socks, number: 0, numberColor: wear.trim };
      tinted.set(key, recolour(b.atlas, paletteFor(kitSpec, skin, hair, boots, p.keeper), true));
    });
    pump();
  }
  return null;
}

/** Which baked animation and frame shows this athlete now. */
function animFor(p: ScenePlayer, meta: AtlasMeta): { name: string; frame: number } {
  const A = (n: string) => meta.anims.find((a) => a.name === n) ?? meta.anims[0];
  const cycle = (n: string) => ({ name: n, frame: Math.floor(((p.stride % 1) + 1) % 1 * A(n).frames) });
  const oneShot = (n: string, k: number) => ({ name: n, frame: Math.min(A(n).frames - 1, Math.max(0, Math.floor(k * A(n).frames))) });
  if (p.keeper && (p.pose === "dive" || p.act === ACT.GK_DIVE || p.act === ACT.GK_DOWN)) return oneShot("gk_dive", p.act === ACT.GK_DOWN ? 1 : p.poseK);
  if (p.keeper && (p.pose === "ready" || p.pose === "hold" || p.act === ACT.GK_SET) && p.speed < 1.5) return { name: "gk_ready", frame: Math.floor(Date.now() / 160) % A("gk_ready").frames };
  if (p.pose === "kick") return oneShot(p.poseK > 0 && p.speed > 6 ? "shot" : "pass", p.poseK);
  if (p.pose === "header") return oneShot("header", p.poseK);
  if (p.pose === "celebrate") return { name: "celebrate", frame: Math.floor(Date.now() / 120) % A("celebrate").frames };
  if (p.act === ACT.RECEIVE) return oneShot("receive", 0.5);
  if (p.speed < 0.6) return { name: "idle", frame: Math.floor(Date.now() / 250) % A("idle").frames };
  if (p.act === ACT.DRIBBLE) return cycle("dribble");
  return cycle(p.speed > 6.2 ? "sprint" : "run");
}

/**
 * Draw one athlete from the atlas. Returns false when the atlas is not ready (the caller
 * draws the vector sprite instead). `h` is the on-screen body height in px.
 */
export function drawSpriteAthlete(ctx: CanvasRenderingContext2D, x: number, y: number, h: number, p: ScenePlayer, kit: Kit, g: Geometry,
  screenDir: (g: Geometry, angle: number) => [number, number]): boolean {
  (window as unknown as { __bmSprites?: unknown }).__bmSprites = spriteStatus;
  const res = sheetFor(p, kit);
  if (!res) return false;
  const { sheet, meta } = res;
  const { name, frame } = animFor(p, meta);
  const anim = meta.anims.find((a) => a.name === name);
  if (!anim) return false;
  const [fx, fy] = screenDir(g, p.facing);
  let dir = directionIndex(fx, fy);
  if (name === "gk_dive") dir = Math.sign(fx || 1) * (p.poseDir || 1) > 0 ? 2 : 6;   // dive sideways on screen
  const [sx, sy] = cellXY(meta, anim.row0 + dir, frame);
  // The cell holds 2.7 m around a 1.83 m body seen from 56°: scale so the drawn body matches `h`.
  const size = h * (meta.metresPerCell / 1.83) * 1.42;
  // ground shadow under the feet
  ctx.fillStyle = "rgba(0,0,0,0.28)";
  ctx.beginPath(); ctx.ellipse(x + h * 0.05, y + h * 0.02, h * 0.24, h * 0.08, 0, 0, Math.PI * 2); ctx.fill();
  ctx.imageSmoothingEnabled = true;
  ctx.drawImage(sheet, sx, sy, meta.cell, meta.cell, x - (meta.anchor[0] / meta.cell) * size, y - (meta.anchor[1] / meta.cell) * size, size, size);
  return true;
}

/** Start baking early (the Lab and the match call it when the 2D view opens). */
export function warmSprites(kits: Kit[]) {
  for (const k of kits) bank(patternOf(k));
  bank("plain");
}

/** Diagnostics (Lab): state of the atlas banks and recoloured sheets. */
export function spriteStatus(): { banks: Record<string, string>; sheets: number; queued: number } {
  const out: Record<string, string> = {};
  for (const [k, v] of banks) out[k] = typeof v === "string" ? `${v} ${Math.round((progress[k] ?? 0) * 100)}%` : "ready";
  return { banks: out, sheets: [...tinted.keys()].filter((k) => !k.endsWith("#q")).length, queued: queue.length };
}
