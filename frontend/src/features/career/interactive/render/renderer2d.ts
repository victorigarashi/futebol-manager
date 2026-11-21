import type { InteractiveView } from "../../../../lib/api";
import { frame, predictTarget, pxPerMetre, toScreen, type Aim, type Geometry } from "../gesture";
import { VISUAL, hashOf, shade } from "./config";
import type { Scene, ScenePlayer } from "./presentation";

/**
 * 2D Arcade renderer (top-down, chunky stylised players, original art). Draws the shared
 * Scene only — it never computes a result.
 */
export type Kit = { shirt: string; shorts: string; socks: string; trim: string };
export type Overlay = {
  aim: Aim | null; aimValid: boolean; carrierIndex: number; receivers: Set<string>; yourTurn: boolean; pending: Aim | null; now: number;
  label: boolean; quality: "low" | "medium" | "high";
};

let pitchCache: { key: string; canvas: HTMLCanvasElement } | null = null;

export function geometryFor(width: number, height: number, view: InteractiveView): Geometry {
  const portrait = height > width * 1.1;
  const { length: L, width: W } = view.pitch;
  return { width, height, portrait, pad: 6, ratio: L / W, mx: VISUAL.marginMetres / L, my: VISUAL.marginMetres / W };
}

export function drawScene2D(ctx: CanvasRenderingContext2D, g: Geometry, dpr: number, view: InteractiveView, scene: Scene | null,
  kits: { attack: Kit; defend: Kit }, overlay: Overlay) {
  drawPitch(ctx, g, dpr, view);
  drawGoals(ctx, g, view, scene, overlay.now);
  if (!scene) return;
  const ppm = pxPerMetre(g, view.pitch.length);
  const height = Math.max(VISUAL.playerHeight.min, Math.min(VISUAL.playerHeight.max, (g.portrait ? frame(g).w : frame(g).h) * VISUAL.playerHeight.perPitchWidth * 1.15));
  const players = scene.players.map((p, i) => ({ p, i, s: toScreen(g, p.x, p.y) }));
  // Rings under the feet (control + possible receivers) go below everybody.
  for (const { p, s } of players) {
    if (p.carrier && overlay.yourTurn) ring(ctx, s[0], s[1], height * 0.42, "#c6f24e", 0.9, overlay.now);
    else if (p.carrier) ring(ctx, s[0], s[1], height * 0.4, "#ffffff", 0.55, overlay.now);
    else if (overlay.receivers.has(p.id)) ring(ctx, s[0], s[1], height * 0.36, "#7cc8ff", 0.65, overlay.now);
  }
  if (overlay.aim && overlay.carrierIndex >= 0) drawAim(ctx, g, view, [scene.players[overlay.carrierIndex].x, scene.players[overlay.carrierIndex].y], overlay.aim, overlay.aimValid, ppm, overlay.now);
  if (overlay.pending && overlay.carrierIndex >= 0) drawAim(ctx, g, view, [scene.players[overlay.carrierIndex].x, scene.players[overlay.carrierIndex].y], overlay.pending, true, ppm, overlay.now, 0.45);
  // Depth: draw from the top of the screen down; the ball between bodies by its ground position.
  const ballS = toScreen(g, scene.ball.x, scene.ball.y);
  const order = [...players].sort((a, b) => a.s[1] - b.s[1]);
  let ballDrawn = false;
  const ballR = Math.max(VISUAL.ballRadius.min, height * VISUAL.ballRadius.perPlayerHeight);
  for (const { p, s } of order) {
    if (!ballDrawn && ballS[1] < s[1]) { drawBall(ctx, ballS[0], ballS[1], scene.ball.z, ballR, scene.ball.roll, ppm); ballDrawn = true; }
    drawPlayer(ctx, s[0], s[1], height, p, p.team === "A" ? kits.attack : kits.defend, g, ppm, overlay.now);
  }
  if (!ballDrawn && !scene.ball.held) drawBall(ctx, ballS[0], ballS[1], scene.ball.z, ballR, scene.ball.roll, ppm);
  // Only the ball carrier gets a name (no clutter).
  if (overlay.label && overlay.carrierIndex >= 0) {
    const c = scene.players[overlay.carrierIndex];
    const [x, y] = toScreen(g, c.x, c.y);
    nameTag(ctx, x, y - height * 1.12, `${c.number || ""} ${c.name.split(" ").slice(-1)[0]}`.trim(), height);
  }
}

// ---------------------------------------------------------------------------- pitch
function drawPitch(ctx: CanvasRenderingContext2D, g: Geometry, dpr: number, view: InteractiveView) {
  const key = `${g.width}x${g.height}:${g.portrait}:${dpr}:${view.pitch.length}`;
  if (!pitchCache || pitchCache.key !== key) {
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(g.width * dpr); canvas.height = Math.round(g.height * dpr);
    const c = canvas.getContext("2d");
    if (c) { c.setTransform(dpr, 0, 0, dpr, 0, 0); paintPitch(c, g, view); }
    pitchCache = { key, canvas };
  }
  ctx.drawImage(pitchCache.canvas, 0, 0, g.width, g.height);
}

function paintPitch(ctx: CanvasRenderingContext2D, g: Geometry, view: InteractiveView) {
  const { length: L, width: W, box } = view.pitch;
  const grass = VISUAL.grass;
  ctx.fillStyle = grass.outside;
  ctx.fillRect(0, 0, g.width, g.height);
  const f = frame(g);
  // Mowing stripes across the length (beyond the lines too, like a real lawn).
  const stripes = grass.stripes;
  for (let i = -1; i <= stripes; i += 1) {
    const a = toScreen(g, i / stripes, -0.2), b = toScreen(g, (i + 1) / stripes, 1.2);
    ctx.fillStyle = i % 2 ? grass.light : grass.base;
    ctx.fillRect(Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.abs(b[0] - a[0]), Math.abs(b[1] - a[1]));
  }
  // Fine grass texture (deterministic specks) and soft lighting.
  let seed = 7;
  const rand = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
  const specks = Math.min(9000, Math.round((g.width * g.height) / 45));
  for (let i = 0; i < specks; i += 1) {
    ctx.fillStyle = rand() < 0.5 ? "rgba(255,255,255,0.035)" : "rgba(0,0,0,0.045)";
    ctx.fillRect(rand() * g.width, rand() * g.height, 1 + rand() * 1.5, 1 + rand() * 2.5);
  }
  const light = ctx.createRadialGradient(g.width / 2, g.height * 0.35, 10, g.width / 2, g.height / 2, Math.max(g.width, g.height) * 0.75);
  light.addColorStop(0, "rgba(255,255,230,0.07)"); light.addColorStop(1, "rgba(0,0,0,0.22)");
  ctx.fillStyle = light; ctx.fillRect(0, 0, g.width, g.height);
  // Lines (metres -> screen).
  const ppm = pxPerMetre(g, L);
  ctx.strokeStyle = VISUAL.line; ctx.lineWidth = Math.max(1.5, ppm * 0.14); ctx.lineCap = "round"; ctx.lineJoin = "round";
  const P = (xm: number, ym: number) => toScreen(g, xm / L, ym / W);
  const poly = (pts: [number, number][], close = false) => { ctx.beginPath(); pts.forEach(([x, y], i) => { const [sx, sy] = P(x, y); if (i) ctx.lineTo(sx, sy); else ctx.moveTo(sx, sy); }); if (close) ctx.closePath(); ctx.stroke(); };
  const arc = (cx: number, cy: number, r: number, a0: number, a1: number) => { const pts: [number, number][] = []; for (let i = 0; i <= 48; i += 1) { const a = a0 + ((a1 - a0) * i) / 48; pts.push([cx + Math.cos(a) * r, cy + Math.sin(a) * r]); } poly(pts); };
  const dot = (x: number, y: number) => { const [sx, sy] = P(x, y); ctx.beginPath(); ctx.fillStyle = VISUAL.line; ctx.arc(sx, sy, Math.max(2, ppm * 0.22), 0, Math.PI * 2); ctx.fill(); };
  const s = L / 105;
  poly([[0, 0], [L, 0], [L, W], [0, W]], true);
  poly([[L / 2, 0], [L / 2, W]]);
  arc(L / 2, W / 2, 9.15 * s, 0, Math.PI * 2);
  dot(L / 2, W / 2);
  const halfBox = Math.min(W * 0.46, box * (20.16 / 16.5));
  const six = box / 3, halfSix = Math.min(W * 0.3, box * (9.16 / 16.5));
  const spot = box * (11 / 16.5), arcR = box * (9.15 / 16.5);
  for (const end of [0, 1]) {
    const x = end ? L : 0, d = end ? -1 : 1;
    poly([[x, W / 2 - halfBox], [x + d * box, W / 2 - halfBox], [x + d * box, W / 2 + halfBox], [x, W / 2 + halfBox]]);
    poly([[x, W / 2 - halfSix], [x + d * six, W / 2 - halfSix], [x + d * six, W / 2 + halfSix], [x, W / 2 + halfSix]]);
    dot(x + d * spot, W / 2);
    const lim = Math.acos(Math.min(1, (box - spot) / arcR));
    if (end) arc(x + d * spot, W / 2, arcR, Math.PI - lim, Math.PI + lim); else arc(x + d * spot, W / 2, arcR, -lim, lim);
    for (const y of [0, W]) arc(x, y, 1 * s, end ? (y ? Math.PI : Math.PI / 2) : (y ? -Math.PI / 2 : 0), end ? (y ? Math.PI * 1.5 : Math.PI) : (y ? 0 : Math.PI / 2));
  }
  void f;
}

// ---------------------------------------------------------------------------- goals (dynamic: the net ripples)
function drawGoals(ctx: CanvasRenderingContext2D, g: Geometry, view: InteractiveView, scene: Scene | null, now: number) {
  const { length: L, width: W, goal } = view.pitch;
  const ppm = pxPerMetre(g, L);
  const depth = VISUAL.goalDepthMetres, post = (view.pitch.post ?? 0.12) * 1.4;
  for (const end of [0, 1] as const) {
    const x = end ? L : 0, d = end ? 1 : -1;
    const y0 = W / 2 - goal / 2, y1 = W / 2 + goal / 2;
    const P = (xm: number, ym: number) => toScreen(g, xm / L, ym / W);
    const ripple = scene?.ripple && scene.ripple.end === end && scene.ripple.age < VISUAL.netRippleSeconds ? scene.ripple : null;
    const bulge = (ym: number, xm: number) => {
      if (!ripple) return 0;
      const k = 1 - ripple.age / VISUAL.netRippleSeconds;
      const near = Math.exp(-(((ym - ripple.y * W) / 1.6) ** 2));
      return d * near * k * 0.9 * Math.abs(Math.sin(ripple.age * 18)) * (Math.abs(xm - x) / depth);
    };
    // Shadow of the frame on the grass.
    const sh = [P(x + d * depth + 0.4, y0 + 0.5), P(x + d * depth + 0.4, y1 + 0.5), P(x + 0.4, y1 + 0.5), P(x + 0.4, y0 + 0.5)];
    ctx.beginPath(); sh.forEach(([sx, sy], i) => (i ? ctx.lineTo(sx, sy) : ctx.moveTo(sx, sy))); ctx.closePath(); ctx.fillStyle = "rgba(0,0,0,0.22)"; ctx.fill();
    // Net floor.
    const floor = [P(x, y0), P(x + d * depth, y0), P(x + d * depth, y1), P(x, y1)];
    ctx.beginPath(); floor.forEach(([sx, sy], i) => (i ? ctx.lineTo(sx, sy) : ctx.moveTo(sx, sy))); ctx.closePath(); ctx.fillStyle = "rgba(235,245,235,0.18)"; ctx.fill();
    // Mesh.
    ctx.strokeStyle = "rgba(255,255,255,0.55)"; ctx.lineWidth = Math.max(0.6, ppm * 0.035);
    const mesh = 0.45;
    for (let ym = y0; ym <= y1 + 1e-6; ym += mesh) {
      ctx.beginPath();
      for (let k = 0; k <= 6; k += 1) { const xm = x + (d * depth * k) / 6; const [sx, sy] = P(xm + bulge(ym, xm), ym); if (k) ctx.lineTo(sx, sy); else ctx.moveTo(sx, sy); }
      ctx.stroke();
    }
    for (let k = 1; k <= Math.round(depth / mesh); k += 1) {
      const xm = x + d * k * mesh;
      ctx.beginPath();
      for (let ym = y0, j = 0; ym <= y1 + 1e-6; ym += mesh / 2, j += 1) { const [sx, sy] = P(xm + bulge(ym, xm), ym); if (j) ctx.lineTo(sx, sy); else ctx.moveTo(sx, sy); }
      ctx.stroke();
    }
    // Frame: back bar, side bars, crossbar on the line and the two posts (exactly the physical mouth).
    ctx.strokeStyle = "rgba(255,255,255,0.85)"; ctx.lineWidth = Math.max(1, ppm * 0.08);
    const back = [P(x, y0), P(x + d * depth, y0), P(x + d * depth, y1), P(x, y1)];
    ctx.beginPath(); back.forEach(([sx, sy], i) => (i ? ctx.lineTo(sx, sy) : ctx.moveTo(sx, sy))); ctx.stroke();
    ctx.strokeStyle = "#ffffff"; ctx.lineWidth = Math.max(2.5, post * 2 * ppm);
    ctx.beginPath(); const a = P(x, y0), b = P(x, y1); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
    for (const ym of [y0, y1]) { const [sx, sy] = P(x, ym); ctx.beginPath(); ctx.fillStyle = "#ffffff"; ctx.arc(sx, sy, Math.max(2.2, post * ppm * 1.3), 0, Math.PI * 2); ctx.fill(); ctx.strokeStyle = "rgba(0,0,0,0.35)"; ctx.lineWidth = 1; ctx.stroke(); }
  }
  void now;
}

// ---------------------------------------------------------------------------- players
function ring(ctx: CanvasRenderingContext2D, x: number, y: number, r: number, color: string, alpha: number, now: number) {
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.strokeStyle = color; ctx.lineWidth = Math.max(2, r * 0.14);
  ctx.beginPath(); ctx.ellipse(x, y, r * (1 + Math.sin(now * 6) * 0.05), r * 0.45, 0, 0, Math.PI * 2); ctx.stroke();
  ctx.globalAlpha = alpha * 0.25; ctx.fillStyle = color; ctx.fill();
  ctx.restore();
}

/** Screen direction of a pitch angle (handles the portrait rotation). */
function screenDir(g: Geometry, angle: number): [number, number] {
  const ux = Math.cos(angle), uy = Math.sin(angle);
  return g.portrait ? [uy, -ux] : [ux, uy];
}

function limb(ctx: CanvasRenderingContext2D, x0: number, y0: number, x1: number, y1: number, width: number, color: string) {
  ctx.strokeStyle = color; ctx.lineWidth = width; ctx.lineCap = "round";
  ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke();
}

export function drawPlayer(ctx: CanvasRenderingContext2D, x: number, y: number, h: number, p: ScenePlayer, kit: Kit, g: Geometry, ppm: number, now: number) {
  const look = hashOf(p.id);
  const skin = VISUAL.skin[look % VISUAL.skin.length];
  const hair = VISUAL.hair[(look >> 4) % VISUAL.hair.length];
  const boots = VISUAL.boots[(look >> 8) % VISUAL.boots.length];
  const hairStyle = (look >> 12) % 4;
  const shirt = p.keeper ? VISUAL.keeperKits[p.team] : kit.shirt;
  const shorts = p.keeper ? shade(VISUAL.keeperKits[p.team], -0.45) : kit.shorts;
  const socks = p.keeper ? shade(VISUAL.keeperKits[p.team], -0.2) : kit.socks;
  const [fx, fy] = screenDir(g, p.facing);
  const side = fx >= 0 ? 1 : -1;               // sprite mirrored left/right
  const back = fy < -0.45;                       // running up the screen: we see the back (number)
  const run = Math.min(1, p.speed / 7.5);
  const phase = (p.stride / VISUAL.strideMetres) * Math.PI * 2;
  let bob = p.pose === "run" ? Math.abs(Math.sin(phase)) * h * 0.045 * run : Math.sin(now * 2.2 + look) * h * 0.008;
  let lean = p.pose === "run" ? side * run * 0.16 : 0;
  let rot = 0, lift = 0, dx = 0;
  let legA = p.pose === "run" ? Math.sin(phase) * 0.75 * (0.35 + run) : 0;
  let armA = -legA * 0.8;
  let armsUp = false, armsWide = false, kickLeg = 0;
  switch (p.pose) {
    case "kick": { const k = p.poseK; kickLeg = k < 0.35 ? -0.9 * (k / 0.35) : -0.9 + 2.1 * Math.min(1, (k - 0.35) / 0.3); armsWide = true; lean = side * 0.12; break; }
    case "tackle": rot = side * 1.15 * Math.min(1, p.poseK * 2.5); lift = -h * 0.12; dx = side * h * 0.2 * p.poseK; legA = 1.1; break;
    case "header": lift = Math.sin(Math.min(1, p.poseK) * Math.PI) * h * 0.3; armsWide = true; lean = side * 0.25; break;
    case "dive": case "save": {
      const [ddx, ddy] = screenDir(g, Math.PI / 2);
      const dir = p.poseDir * (Math.abs(ddx) > Math.abs(ddy) ? Math.sign(ddx) || 1 : 1);
      rot = dir * 1.35 * Math.min(1, p.poseK * 1.6); dx = dir * h * 0.45 * p.poseK; lift = Math.sin(Math.min(1, p.poseK) * Math.PI) * h * 0.22; armsUp = true; break;
    }
    case "hold": armsWide = false; armA = -1.3; break;
    case "celebrate": armsUp = true; bob = Math.abs(Math.sin(now * 9 + look)) * h * 0.14; legA = Math.sin(now * 9 + look) * 0.3; break;
    case "ready": legA = 0.25; armsWide = true; bob = 0; break;
    default: break;
  }
  // Ground shadow (shrinks when airborne).
  const air = Math.max(0, lift + bob);
  ctx.beginPath(); ctx.fillStyle = `rgba(0,0,0,${0.3 - Math.min(0.15, air / h)})`;
  ctx.ellipse(x + dx * 0.6 + h * 0.06, y + h * 0.03, h * 0.27 * (1 - Math.min(0.4, air / h)), h * 0.09, 0, 0, Math.PI * 2); ctx.fill();
  ctx.save();
  ctx.translate(x + dx, y - lift - bob);
  ctx.rotate(rot);
  ctx.transform(1, 0, -lean, 1, 0, 0);
  const u = h / 10;                              // chibi proportions: big head, short body
  const hip = -u * 3.4, shoulder = -u * 5.9;
  // Legs (thigh + shin feel via two strokes), socks and boots.
  const legW = u * 1.05;
  for (const which of [-1, 1]) {
    const swing = which === 1 ? legA + kickLeg : -legA;
    const hx = which * u * 0.65;
    const kx = hx + Math.sin(swing) * u * 1.8 * side, ky = hip + Math.cos(swing) * u * 1.8;
    const bend = Math.max(0, -Math.sin(swing)) * 0.9;
    const fx2 = kx + Math.sin(swing - bend) * u * 1.7 * side, fy2 = Math.min(0, ky + Math.cos(swing - bend) * u * 1.7);
    limb(ctx, hx, hip, kx, ky, legW, skin);
    limb(ctx, kx, ky, fx2, fy2, legW * 0.95, socks);
    ctx.fillStyle = boots; ctx.beginPath(); ctx.ellipse(fx2 + side * u * 0.35, fy2, u * 0.75, u * 0.42, 0, 0, Math.PI * 2); ctx.fill();
  }
  // Shorts.
  ctx.fillStyle = shorts; roundRect(ctx, -u * 1.55, hip - u * 1.1, u * 3.1, u * 1.5, u * 0.4); ctx.fill();
  // Arms behind the torso when seen from behind.
  const arm = (which: number) => {
    const sx = which * u * 1.55, sy = shoulder + u * 0.45;
    let ang = which * 0.25 + (which === 1 ? armA : -armA) * 0.9;
    if (armsUp) ang = which * 2.6; else if (armsWide) ang = which * 1.05;
    const ex = sx + Math.sin(ang) * u * 2.4 * (armsUp || armsWide ? 1 : side * which), ey = sy + Math.cos(ang) * u * 2.4;
    limb(ctx, sx, sy, sx + (ex - sx) * 0.45, sy + (ey - sy) * 0.45, u * 0.95, shirt);
    limb(ctx, sx + (ex - sx) * 0.45, sy + (ey - sy) * 0.45, ex, ey, u * 0.85, p.keeper ? "#f4f4f4" : skin);
  };
  if (back) { arm(-1); arm(1); }
  // Torso (jersey with a trim band) and number.
  ctx.fillStyle = shirt; roundRect(ctx, -u * 1.75, shoulder, u * 3.5, u * 3.0, u * 0.8); ctx.fill();
  ctx.fillStyle = kit.trim; ctx.globalAlpha = 0.9; ctx.fillRect(-u * 1.75, shoulder + u * 0.15, u * 3.5, u * 0.35); ctx.globalAlpha = 1;
  ctx.strokeStyle = "rgba(0,0,0,0.28)"; ctx.lineWidth = 1; roundRect(ctx, -u * 1.75, shoulder, u * 3.5, u * 3.0, u * 0.8); ctx.stroke();
  if (p.number && h >= 26) {
    ctx.fillStyle = contrast(shirt); ctx.font = `900 ${Math.round(u * (back ? 1.9 : 1.15))}px "Barlow Condensed", "Arial Narrow", sans-serif`;
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(String(p.number), back ? 0 : side * u * 0.75, shoulder + u * (back ? 1.65 : 1.1));
  }
  if (!back) { arm(-1); arm(1); }
  // Head (big, chibi): skin, hair by style, eyes looking where he faces.
  const hy = shoulder - u * 1.9, hr = u * 2.05;
  ctx.fillStyle = skin; ctx.beginPath(); ctx.ellipse(0, hy, hr * 0.95, hr, 0, 0, Math.PI * 2); ctx.fill();
  ctx.strokeStyle = "rgba(0,0,0,0.25)"; ctx.lineWidth = 1; ctx.stroke();
  ctx.fillStyle = hair;
  ctx.beginPath();
  if (back) ctx.ellipse(0, hy - hr * 0.05, hr * 0.97, hr * 0.92, 0, Math.PI * 1.0, Math.PI * 2.0);
  else ctx.ellipse(-side * hr * 0.1, hy - hr * 0.35, hr * 0.92, hr * (hairStyle === 0 ? 0.45 : 0.62), 0, Math.PI, Math.PI * 2);
  ctx.fill();
  if (back) { ctx.beginPath(); ctx.ellipse(0, hy, hr * 0.95, hr * 0.8, 0, 0, Math.PI); ctx.fill(); }
  if (hairStyle === 2) { ctx.beginPath(); ctx.ellipse(0, hy - hr * 0.95, hr * 0.3, hr * 0.35, 0, 0, Math.PI * 2); ctx.fill(); }
  if (!back) {
    ctx.fillStyle = "#1a1a1a";
    const ex = side * hr * 0.35;
    ctx.beginPath(); ctx.arc(ex - hr * 0.22, hy + hr * 0.05, Math.max(1, hr * 0.11), 0, Math.PI * 2); ctx.arc(ex + hr * 0.22, hy + hr * 0.05, Math.max(1, hr * 0.11), 0, Math.PI * 2); ctx.fill();
    if (p.pose === "celebrate") { ctx.beginPath(); ctx.fillStyle = "#5a1a14"; ctx.arc(ex, hy + hr * 0.45, hr * 0.18, 0, Math.PI); ctx.fill(); }
  }
  ctx.restore();
  void ppm;
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r); ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
}

function contrast(color: string): string {
  const m = color.match(/\d+/g);
  let r = 0, gg = 0, b = 0;
  if (color.startsWith("#")) { const n = parseInt(color.slice(1), 16); r = (n >> 16) & 255; gg = (n >> 8) & 255; b = n & 255; }
  else if (m) [r, gg, b] = m.map(Number);
  return 0.299 * r + 0.587 * gg + 0.114 * b > 150 ? "#111111" : "#ffffff";
}

function nameTag(ctx: CanvasRenderingContext2D, x: number, y: number, text: string, h: number) {
  ctx.save();
  ctx.font = `800 ${Math.max(11, Math.round(h * 0.34))}px Inter, system-ui, sans-serif`;
  const w = ctx.measureText(text).width + 14, th = Math.max(16, h * 0.5);
  ctx.fillStyle = "rgba(10,14,20,0.82)"; roundRect(ctx, x - w / 2, y - th, w, th, th / 2); ctx.fill();
  ctx.fillStyle = "#c6f24e"; ctx.beginPath(); ctx.moveTo(x - 5, y); ctx.lineTo(x + 5, y); ctx.lineTo(x, y + 5); ctx.fill();
  ctx.fillStyle = "#ffffff"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(text, x, y - th / 2 + 0.5);
  ctx.restore();
}

// ---------------------------------------------------------------------------- ball
export function drawBall(ctx: CanvasRenderingContext2D, x: number, y: number, z: number, r: number, roll: number, ppm: number) {
  const lift = z * ppm * 0.85;
  const scale = 1 + Math.min(0.6, z * 0.07);
  ctx.beginPath(); ctx.fillStyle = `rgba(0,0,0,${Math.max(0.12, 0.35 - z * 0.04)})`;
  ctx.ellipse(x + lift * 0.25 + r * 0.25, y + r * 0.35, r * (1 - Math.min(0.4, z * 0.05)), r * 0.5, 0, 0, Math.PI * 2); ctx.fill();
  const by = y - lift - r * 0.2, br = r * scale;
  ctx.save();
  ctx.beginPath(); ctx.arc(x, by, br, 0, Math.PI * 2); ctx.fillStyle = "#ffffff"; ctx.fill();
  ctx.clip();
  // Classic panels rolling with the distance travelled.
  const a = roll / Math.max(0.3, r / ppm) * 0.35;
  ctx.fillStyle = "#1b1b1b";
  const patch = (cx: number, cy: number, s: number) => { ctx.beginPath(); for (let i = 0; i < 5; i += 1) { const t = a + (i * Math.PI * 2) / 5; ctx.lineTo(cx + Math.cos(t) * s, cy + Math.sin(t) * s); } ctx.fill(); };
  patch(x + Math.cos(a) * br * 0.15, by + Math.sin(a * 0.7) * br * 0.15, br * 0.36);
  for (let i = 0; i < 5; i += 1) { const t = a + (i * Math.PI * 2) / 5; patch(x + Math.cos(t) * br * 0.95, by + Math.sin(t) * br * 0.95, br * 0.3); }
  const shine = ctx.createRadialGradient(x - br * 0.4, by - br * 0.4, 0, x, by, br * 1.1);
  shine.addColorStop(0, "rgba(255,255,255,0.6)"); shine.addColorStop(1, "rgba(0,0,0,0.25)");
  ctx.fillStyle = shine; ctx.fillRect(x - br, by - br, br * 2, br * 2);
  ctx.restore();
  ctx.beginPath(); ctx.arc(x, by, br, 0, Math.PI * 2); ctx.strokeStyle = "rgba(0,0,0,0.55)"; ctx.lineWidth = 1; ctx.stroke();
}

// ---------------------------------------------------------------------------- aim (intention, never a guarantee)
export function drawAim(ctx: CanvasRenderingContext2D, g: Geometry, view: InteractiveView, from: [number, number], aim: Aim, valid: boolean, ppm: number, now: number, alpha = 1) {
  const target = predictTarget(view, from, aim);
  const [x0, y0] = toScreen(g, from[0], from[1]);
  const [x1, y1] = toScreen(g, target[0], target[1]);
  const color = valid ? VISUAL.aim[aim.type] : VISUAL.aim.invalid;
  const len = Math.hypot(x1 - x0, y1 - y0);
  if (len < 4) return;
  const ux = (x1 - x0) / len, uy = (y1 - y0) / len;
  ctx.save();
  ctx.globalAlpha = alpha;
  // Assistance sector: the real angular window the engine uses to pick a receiver.
  const sector = view.physics.assist_angle ?? 0.24;
  if ((aim.type === "PASS" || aim.type === "LOFT") && valid) {
    ctx.setLineDash([2, 7]); ctx.lineDashOffset = -now * 20; ctx.strokeStyle = "rgba(230,255,140,0.75)"; ctx.lineWidth = 2.5;
    for (const s of [-1, 1]) { const c = Math.cos(sector * s), si = Math.sin(sector * s); const vx = ux * c - uy * si, vy = ux * si + uy * c; ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x0 + vx * len, y0 + vy * len); ctx.stroke(); }
  }
  // Trajectory: lofted balls rise (with their ground shadow), others go straight.
  ctx.setLineDash(aim.type === "CARRY" ? [6, 6] : [12, 8]); ctx.lineDashOffset = -now * 40;
  ctx.lineCap = "round";
  if (aim.type === "LOFT") {
    const apex = Math.min(len * 0.35, 4.2 * ppm * 2);
    ctx.strokeStyle = "rgba(0,0,0,0.35)"; ctx.lineWidth = 3; ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke();
    ctx.strokeStyle = color; ctx.lineWidth = 4; ctx.beginPath(); ctx.moveTo(x0, y0); ctx.quadraticCurveTo((x0 + x1) / 2, (y0 + y1) / 2 - apex * 2, x1, y1); ctx.stroke();
  } else {
    ctx.strokeStyle = "rgba(0,0,0,0.35)"; ctx.lineWidth = 7; ctx.beginPath(); ctx.moveTo(x0, y0 + 2); ctx.lineTo(x1, y1 + 2); ctx.stroke();
    ctx.strokeStyle = color; ctx.lineWidth = 4.5; ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke();
  }
  ctx.setLineDash([]);
  // Big arrow near the ball, its length proportional to the power (the look players expect).
  const arrow = 22 + aim.power * 52;
  const ax = x0 + ux * (14 + arrow), ay = y0 + uy * (14 + arrow);
  const nx = -uy, ny = ux, wBody = 7, wHead = 15;
  ctx.beginPath();
  ctx.moveTo(x0 + ux * 14 + nx * wBody, y0 + uy * 14 + ny * wBody);
  ctx.lineTo(ax - ux * 16 + nx * wBody, ay - uy * 16 + ny * wBody);
  ctx.lineTo(ax - ux * 16 + nx * wHead, ay - uy * 16 + ny * wHead);
  ctx.lineTo(ax, ay);
  ctx.lineTo(ax - ux * 16 - nx * wHead, ay - uy * 16 - ny * wHead);
  ctx.lineTo(ax - ux * 16 - nx * wBody, ay - uy * 16 - ny * wBody);
  ctx.lineTo(x0 + ux * 14 - nx * wBody, y0 + uy * 14 - ny * wBody);
  ctx.closePath();
  ctx.fillStyle = "rgba(0,0,0,0.3)"; ctx.save(); ctx.translate(2, 3); ctx.fill(); ctx.restore();
  ctx.fillStyle = valid ? "#ffd31a" : VISUAL.aim.invalid; ctx.fill();
  ctx.strokeStyle = "rgba(120,80,0,0.7)"; ctx.lineWidth = 1.5; ctx.stroke();
  // Power percentage at the arrow head.
  ctx.font = `900 ${Math.round(15 + aim.power * 5)}px "Barlow Condensed", Inter, sans-serif`;
  ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.lineWidth = 4; ctx.strokeStyle = "rgba(0,0,0,0.65)";
  const label = `${Math.round(aim.power * 100)}%`;
  ctx.strokeText(label, ax + ux * 18, ay + uy * 18 - 4); ctx.fillStyle = "#fff6c7"; ctx.fillText(label, ax + ux * 18, ay + uy * 18 - 4);
  // Destination marker.
  ctx.beginPath(); ctx.strokeStyle = color; ctx.lineWidth = 2.5; ctx.arc(x1, y1, 9 + Math.sin(now * 7) * 1.5, 0, Math.PI * 2); ctx.stroke();
  ctx.beginPath(); ctx.fillStyle = color; ctx.globalAlpha = alpha * 0.3; ctx.arc(x1, y1, 14, 0, Math.PI * 2); ctx.fill();
  ctx.restore();
}
