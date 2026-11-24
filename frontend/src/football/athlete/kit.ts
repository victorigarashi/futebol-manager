import * as THREE from "three";
import { FACE_V0, FACE_V1, SHIRT_V, type Region } from "./body";
import { BOOT_COLOURS, HAIR_COLOURS, SKIN_TONES } from "./palette";
export { BOOT_COLOURS, HAIR_COLOURS, SKIN_TONES };

/**
 * One kit description shared by 3D and 2D (research prototype).
 *
 * The server already picks contrasting kits (CIEDE2000, backend/app/domain/kits.py). This
 * spec is what a renderer needs from that choice: colours, pattern and the shirt number.
 * 3D: a 256 px shirt texture per player (pattern + numbers) and vertex colours for the
 * rest. 2D: the same `regionPalette` recolours one mask-baked sprite atlas (sprites lab),
 * so there is never an atlas per team.
 */
export type Pattern = "plain" | "hoops" | "stripes" | "sash" | "halves";
export type KitSpec = { primary: string; secondary: string; pattern: Pattern; shorts: string; socks: string; number: number; numberColor: string };
export type Cosmetic = { skin: string; hair: string; hairStyle: number; boots: string; build: number };


export const KIT_HOME: KitSpec = { primary: "#d81f26", secondary: "#111111", pattern: "stripes", shorts: "#111111", socks: "#111111", number: 10, numberColor: "#ffffff" };
export const KIT_AWAY: KitSpec = { primary: "#f2f2f2", secondary: "#1d3f8f", pattern: "sash", shorts: "#1d3f8f", socks: "#f2f2f2", number: 9, numberColor: "#1d3f8f" };
export const KIT_KEEPER: KitSpec = { primary: "#2ecc71", secondary: "#0b5d2a", pattern: "halves", shorts: "#0b5d2a", socks: "#2ecc71", number: 1, numberColor: "#0b3d1c" };

/** Deterministic cosmetic look from an id hash (never from name or nationality). */
export function cosmeticFor(hash: number): Cosmetic {
  return {
    skin: SKIN_TONES[hash % SKIN_TONES.length],
    hair: HAIR_COLOURS[(hash >>> 3) % HAIR_COLOURS.length],
    hairStyle: (hash >>> 7) % 5,
    boots: BOOT_COLOURS[(hash >>> 11) % BOOT_COLOURS.length],
    build: ((hash >>> 13) % 100) / 100,
  };
}

export function regionPalette(kit: KitSpec, look: Cosmetic, keeper: boolean): Record<Region, string> {
  return {
    skin: look.skin, shirt: "#ffffff", trim: kit.secondary, shorts: kit.shorts, shortsTrim: kit.secondary,
    socks: kit.socks, sockTrim: kit.secondary, boots: look.boots, sole: look.boots === "#f4f4f4" ? "#202020" : "#e8e8e8",
    hair: look.hair, eye: "#17110d", brow: look.hair, lips: shadeHex(look.skin, -0.25), gloves: keeper ? "#f4f4f4" : look.skin,
  };
}

export function shadeHex(hex: string, amount: number): string {
  const c = new THREE.Color(hex);
  if (amount < 0) c.multiplyScalar(1 + amount); else c.lerp(new THREE.Color(1, 1, 1), amount);
  return `#${c.getHexString()}`;
}

/**
 * Shirt texture: u wraps the torso (back centre = 0.5), v from waist (0) to collar (0.93).
 * The top strip (v > 0.95) is white: every non-shirt vertex samples it and keeps its vertex colour.
 */
export function shirtCanvas(kit: KitSpec, size = 256, look?: Cosmetic): HTMLCanvasElement {
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const g = c.getContext("2d")!;
  const H = size, Wd = size;
  // canvas y grows downwards; texture v grows upwards (flipY)
  g.fillStyle = kit.primary; g.fillRect(0, 0, Wd, H);
  g.fillStyle = kit.secondary;
  // shirt coordinates: sv in [0, 1] covers the torso (texture v in [0, SHIRT_V])
  const vy = (sv: number) => H * (1 - sv * SHIRT_V / 0.93);
  switch (kit.pattern) {
    case "hoops": for (let i = 0; i < 7; i += 2) g.fillRect(0, vy((i + 1) / 7.5 * 0.93), Wd, H * SHIRT_V / 7.5); break;
    case "stripes": { const n = 12; for (let i = 0; i < n; i += 2) g.fillRect((i + 0.5) * Wd / n, 0, Wd / n, H); break; }
    case "halves": g.fillRect(Wd * 0.25, 0, Wd * 0.5, H); break;   // u 0.25..0.75 = the back half; front is primary
    case "sash": {
      // a diagonal band across the front (front is around u = 0 / 1)
      g.save(); g.beginPath();
      for (const off of [0, Wd]) {
        g.moveTo(off - Wd * 0.2, vy(0.0)); g.lineTo(off - Wd * 0.06, vy(0.0)); g.lineTo(off + Wd * 0.2, vy(0.93)); g.lineTo(off + Wd * 0.06, vy(0.93)); g.closePath();
      }
      g.fill(); g.restore(); break;
    }
    default: break;
  }
  // subtle fabric shading: side seams darker, mesh texture noise
  const grad = g.createLinearGradient(0, 0, Wd, 0);
  grad.addColorStop(0, "rgba(0,0,0,0)"); grad.addColorStop(0.25, "rgba(0,0,0,0.10)"); grad.addColorStop(0.5, "rgba(0,0,0,0)"); grad.addColorStop(0.75, "rgba(0,0,0,0.10)"); grad.addColorStop(1, "rgba(0,0,0,0)");
  g.fillStyle = grad; g.fillRect(0, 0, Wd, H);
  for (let y = 0; y < H; y += 2) { g.fillStyle = y % 4 === 0 ? "rgba(255,255,255,0.025)" : "rgba(0,0,0,0.025)"; g.fillRect(0, y, Wd, 1); }
  // back number (big) and front number (small, on the left chest)
  const numberFont = (px: number) => `800 ${px}px "Arial Narrow", "Roboto Condensed", Arial, sans-serif`;
  g.textAlign = "center"; g.textBaseline = "middle";
  g.font = numberFont(H * 0.3);
  g.lineWidth = H * 0.012; g.strokeStyle = kit.primary === kit.numberColor ? kit.secondary : shadeHex(kit.numberColor, kit.numberColor === "#ffffff" ? -0.6 : 0.6);
  // The shirt's UV runs right-to-left over the body (seen from outside), so both numbers are
  // drawn mirrored to read correctly on the 3D model (V8 fix: "10" used to read "01").
  g.save(); g.translate(Wd * 0.5, 0); g.scale(-0.78, 1);
  g.strokeText(String(kit.number), 0, vy(0.6));
  g.fillStyle = kit.numberColor; g.fillText(String(kit.number), 0, vy(0.6));
  g.restore();
  g.font = numberFont(H * 0.075); g.fillStyle = kit.numberColor;
  g.save(); g.translate(Wd * 0.92, 0); g.scale(-1, 1); g.fillText(String(kit.number), 0, vy(0.74)); g.restore();
  // crest placeholder (fictional) on the right chest
  g.beginPath(); g.arc(Wd * 0.085, vy(0.74), H * 0.022, 0, Math.PI * 2); g.fillStyle = kit.secondary; g.fill();
  g.strokeStyle = kit.numberColor; g.lineWidth = 1.5; g.stroke();
  // white band (non-shirt vertices + face patch background)
  g.fillStyle = "#ffffff"; g.fillRect(0, 0, Wd, H * (1 - SHIRT_V) - 1);
  paintFace(g, Wd, H, look);
  return c;
}

/**
 * Face painted as a multiply layer over the skin vertex colour (white = skin unchanged):
 * eye shapes, brows, lip line, nose and cheek shading. Not a likeness of anyone.
 */
function paintFace(g: CanvasRenderingContext2D, W: number, H: number, look?: Cosmetic) {
  const x0 = 0, x1 = W * 0.25, y0 = H * (1 - FACE_V1), y1 = H * (1 - FACE_V0);
  const fx = (f: number) => x0 + (f + 1) / 2 * (x1 - x0);
  const fy = (f: number) => y1 - (f + 1) / 2 * (y1 - y0);
  const sx = (x1 - x0) / 2, sy = (y1 - y0) / 2;
  const brow = look ? shadeHex(look.hair, -0.2) : "#2a1a10";
  g.save();
  g.beginPath(); g.rect(x0, y0, x1 - x0, y1 - y0); g.clip();
  // soft shading: eye sockets, under the nose, cheeks
  const blob = (cx: number, cy: number, rx: number, ry: number, colour: string) => {
    const gr = g.createRadialGradient(fx(cx), fy(cy), 0, fx(cx), fy(cy), Math.max(rx * sx, ry * sy));
    gr.addColorStop(0, colour); gr.addColorStop(1, "rgba(255,255,255,0)");
    g.save(); g.translate(fx(cx), fy(cy)); g.scale(1, (ry * sy) / Math.max(rx * sx, ry * sy)); g.translate(-fx(cx), -fy(cy));
    g.fillStyle = gr; g.beginPath(); g.arc(fx(cx), fy(cy), Math.max(rx * sx, ry * sy), 0, Math.PI * 2); g.fill(); g.restore();
  };
  for (const s of [-1, 1]) blob(s * 0.43, 0.22, 0.26, 0.16, "rgba(150,110,90,0.55)");
  blob(0, -0.12, 0.12, 0.08, "rgba(140,100,80,0.45)");
  // eyes: almond with a dark iris and a light sclera hint
  for (const s of [-1, 1]) {
    g.fillStyle = "#f1ece6";
    g.beginPath(); g.ellipse(fx(s * 0.43), fy(0.22), 0.17 * sx, 0.07 * sy, 0, 0, Math.PI * 2); g.fill();
    g.fillStyle = "#2b1d14";
    g.beginPath(); g.arc(fx(s * 0.41), fy(0.22), 0.075 * sx, 0, Math.PI * 2); g.fill();
    g.strokeStyle = "rgba(40,25,18,0.85)"; g.lineWidth = Math.max(1, sy * 0.04);
    g.beginPath(); g.ellipse(fx(s * 0.43), fy(0.22), 0.17 * sx, 0.07 * sy, 0, Math.PI, Math.PI * 2); g.stroke();
    // brows
    g.strokeStyle = brow; g.lineWidth = Math.max(1.5, sy * 0.07); g.lineCap = "round";
    g.beginPath(); g.moveTo(fx(s * 0.22), fy(0.4)); g.quadraticCurveTo(fx(s * 0.45), fy(0.47), fx(s * 0.66), fy(0.38)); g.stroke();
  }
  // nose line and nostrils
  g.strokeStyle = "rgba(120,80,60,0.35)"; g.lineWidth = Math.max(1, sy * 0.03);
  g.beginPath(); g.moveTo(fx(0.06), fy(0.12)); g.lineTo(fx(0.08), fy(-0.08)); g.stroke();
  g.fillStyle = "rgba(90,55,40,0.55)";
  for (const s of [-1, 1]) { g.beginPath(); g.ellipse(fx(s * 0.07), fy(-0.13), 0.04 * sx, 0.025 * sy, 0, 0, Math.PI * 2); g.fill(); }
  // mouth: lip tone and the lip line
  g.fillStyle = "rgba(170,95,85,0.55)";
  g.beginPath(); g.ellipse(fx(0), fy(-0.46), 0.2 * sx, 0.07 * sy, 0, 0, Math.PI * 2); g.fill();
  g.strokeStyle = "rgba(70,35,30,0.8)"; g.lineWidth = Math.max(1, sy * 0.035);
  g.beginPath(); g.moveTo(fx(-0.19), fy(-0.45)); g.quadraticCurveTo(fx(0), fy(-0.48), fx(0.19), fy(-0.45)); g.stroke();
  g.restore();
}

export function shirtTexture(kit: KitSpec, look?: Cosmetic): THREE.CanvasTexture {
  const t = new THREE.CanvasTexture(shirtCanvas(kit, 256, look));
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 4;
  t.wrapS = THREE.RepeatWrapping;
  return t;
}
