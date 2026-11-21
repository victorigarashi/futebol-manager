import type { InteractiveView } from "../../../../lib/api";
import { frame, predictTarget, pxPerMetre, toScreen, type Aim, type Geometry, type Region } from "../gesture";
import { VISUAL, hashOf, shade } from "./config";
import type { Scene, ScenePlayer } from "./presentation";

/**
 * 2D Arcade renderer (top-down, chunky stylised players, original art). Draws the shared
 * Scene only — it never computes a result.
 */
export type Kit = { shirt: string; shorts: string; socks: string; trim: string; number?: string; pattern?: string; gk?: Kit };
export type Overlay = {
  aim: Aim | null; aimValid: boolean; carrierIndex: number; receivers: Set<string>; yourTurn: boolean; pending: Aim | null; now: number;
  label: boolean; quality: "low" | "medium" | "high";
};

let pitchCache: { key: string; canvas: HTMLCanvasElement; k: number } | null = null;

export function geometryFor(width: number, height: number, view: InteractiveView, region?: Region): Geometry {
  const portrait = height > width * 1.1;
  const { length: L, width: W } = view.pitch;
  return { width, height, portrait, pad: 6, ratio: L / W, mx: VISUAL.marginMetres / L, my: VISUAL.marginMetres / W, view: region };
}

/**
 * 2D "Jogada" camera (optional, the full pitch stays one tap away): frames the attack —
 * the ball and the goal it attacks, with the whole width — so players read bigger. Purely
 * visual; it never moves during a gesture.
 */
export function playRegion(view: InteractiveView, ballX: number, ballY: number, width: number, height: number): Region {
  const { length: L, width: W } = view.pitch;
  const m = VISUAL.marginMetres;
  const portrait = height > width * 1.1;
  const dir = view.opportunity?.right === false ? -1 : 1;
  // Metres of pitch length on screen (more of the pitch on small pitches), then the
  // across-span that matches the screen's proportions.
  const along = Math.min(L + 2 * m, L <= 60 ? L * 0.85 : 70);
  const aspect = portrait ? height / Math.max(1, width) : width / Math.max(1, height);
  const across = Math.min(W + 2 * m, along / aspect);
  const cx = ballX * L + dir * along * 0.2;                  // look ahead, towards the goal
  const cy = ballY * W * 0.55 + (W / 2) * 0.45;               // follow the ball, biased to the middle
  const x0 = Math.max(-m, Math.min(L + m - along, cx - along / 2));
  const y0 = Math.max(-m, Math.min(W + m - across, cy - across / 2));
  return { x0: x0 / L, x1: (x0 + along) / L, y0: y0 / W, y1: (y0 + across) / W };
}

export function drawScene2D(ctx: CanvasRenderingContext2D, g: Geometry, dpr: number, view: InteractiveView, scene: Scene | null,
  kits: { attack: Kit; defend: Kit }, overlay: Overlay) {
  drawPitch(ctx, g, dpr, view);
  drawGoals(ctx, g, view, scene, overlay.now);
  if (!scene) return;
  const ppm = pxPerMetre(g, view.pitch.length);
  // Stylised scale (a mobile-football look): about 2.2x a 1.8 m athlete, from px per metre.
  const height = Math.max(VISUAL.playerHeight.min, Math.min(VISUAL.playerHeight.max, ppm * VISUAL.playerHeight.metres));
  const players = scene.players.map((p, i) => ({ p, i, s: toScreen(g, p.x, p.y) }));
  // Rings under the feet (control + possible receivers) go below everybody.
  for (const { p, s } of players) {
    if (p.carrier && overlay.yourTurn) ring(ctx, s[0], s[1], height * 0.42, "#c6f24e", 0.9, overlay.now);
    else if (p.carrier) ring(ctx, s[0], s[1], height * 0.4, "#ffffff", 0.55, overlay.now);
  }
  if (overlay.aim && overlay.carrierIndex >= 0) drawAim(ctx, g, view, [scene.players[overlay.carrierIndex].x, scene.players[overlay.carrierIndex].y], overlay.aim, overlay.aimValid, ppm, overlay.now);
  // Depth: draw from the top of the screen down; the ball between bodies by its ground position.
  const ballS = toScreen(g, scene.ball.x, scene.ball.y);
  const order = [...players].sort((a, b) => a.s[1] - b.s[1]);
  let ballDrawn = false;
  const ballR = Math.max(VISUAL.ballRadius.min, height * VISUAL.ballRadius.perPlayerHeight);
  void dpr;
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
/**
 * The lawn, lines and boards are painted ONCE into a texture in metres (pitch space), then
 * drawn with the current camera transform — the camera can move every frame for free.
 */
function drawPitch(ctx: CanvasRenderingContext2D, g: Geometry, dpr: number, view: InteractiveView) {
  const { length: L, width: W } = view.pitch;
  const m = VISUAL.marginMetres;
  const k = Math.min(32, 4096 / (L + 2 * m));          // texture px per metre
  const key = `${L}x${W}:${view.pitch.goal}:${k}`;
  if (!pitchCache || pitchCache.key !== key) {
    const canvas = document.createElement("canvas");
    canvas.width = Math.round((L + 2 * m) * k); canvas.height = Math.round((W + 2 * m) * k);
    const c = canvas.getContext("2d");
    if (c) { c.scale(k, k); c.translate(m, m); paintPitch(c, view, k); }
    pitchCache = { key, canvas, k };
  }
  const f = frame(g);
  const ppm = pxPerMetre(g, L);
  ctx.fillStyle = "#1d4a2a"; ctx.fillRect(0, 0, g.width, g.height);
  ctx.save();
  if (g.portrait) { ctx.translate(f.ox, f.oy + f.h); ctx.rotate(-Math.PI / 2); }
  else ctx.translate(f.ox, f.oy);
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(pitchCache.canvas, -m * ppm, -m * ppm, (L + 2 * m) * ppm, (W + 2 * m) * ppm);
  ctx.restore();
  void dpr;
}

/** Paint in metres: origin at the corner flag (0, 0), x along the length. */
function paintPitch(ctx: CanvasRenderingContext2D, view: InteractiveView, k: number) {
  const { length: L, width: W, box } = view.pitch;
  const m = VISUAL.marginMetres;
  const grass = VISUAL.grass;
  ctx.fillStyle = grass.outside; ctx.fillRect(-m, -m, L + 2 * m, W + 2 * m);
  // Mowing stripes across the length (also beyond the lines, like a real lawn).
  const stripes = grass.stripes, sw = L / stripes;
  for (let i = -1; i <= stripes; i += 1) { ctx.fillStyle = i % 2 ? grass.light : grass.base; ctx.fillRect(i * sw, -m + 1.2, sw, W + 2 * m - 2.4); }
  // Grass grain (deterministic), then soft light.
  let seed = 7;
  const rand = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
  const specks = Math.round((L * W) * 3.2);
  for (let i = 0; i < specks; i += 1) {
    ctx.fillStyle = rand() < 0.5 ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.05)";
    ctx.fillRect(rand() * L, rand() * W, (1 + rand()) / k, (1.5 + rand() * 2) / k);
  }
  const light = ctx.createRadialGradient(L / 2, W * 0.35, 1, L / 2, W / 2, L * 0.7);
  light.addColorStop(0, "rgba(255,255,230,0.06)"); light.addColorStop(1, "rgba(0,0,0,0.16)");
  ctx.fillStyle = light; ctx.fillRect(-m, -m, L + 2 * m, W + 2 * m);
  // Ad boards (fictional) along the touchlines, outside the field of play.
  const brands: [string, string, string][] = [["RESENHA FC", "#0f4fa8", "#ffd31a"], ["BRASILEIRÃO MANAGER", "#e8352e", "#ffffff"], ["VAI PRA CIMA", "#14975a", "#ffffff"],
    ["GOLAÇO", "#111827", "#c6f24e"], ["TABELINHA", "#0ea5e9", "#ffffff"], ["BOLA NA REDE", "#7a2bd1", "#ffffff"], ["CRAQUE DA RODADA", "#ffd31a", "#111111"]];
  const bw = Math.max(8, L / 7), bh = Math.min(1.0, m * 0.32);
  ctx.textAlign = "center"; ctx.textBaseline = "middle";
  for (const [y, flip] of [[-m + 0.15, 0], [W + m - 0.15 - bh, 1]] as const) {
    for (let x = 0, i = flip * 3; x < L; x += bw, i += 1) {
      const [text, bg, fg] = brands[i % brands.length];
      ctx.fillStyle = bg; ctx.fillRect(x, y, Math.min(bw, L - x) - 0.15, bh);
      ctx.fillStyle = fg; ctx.font = `900 ${bh * 0.62}px "Barlow Condensed", Inter, sans-serif`;
      ctx.fillText(text, x + Math.min(bw, L - x) / 2, y + bh / 2 + 0.02, Math.min(bw, L - x) * 0.9);
    }
  }
  // Lines.
  ctx.strokeStyle = VISUAL.line; ctx.lineWidth = 0.12 * Math.max(1, 105 / L) ** 0.5; ctx.lineCap = "round"; ctx.lineJoin = "round";
  const poly = (pts: [number, number][], close = false) => { ctx.beginPath(); pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); if (close) ctx.closePath(); ctx.stroke(); };
  const arc = (cx: number, cy: number, r: number, a0: number, a1: number) => { ctx.beginPath(); ctx.arc(cx, cy, r, a0, a1); ctx.stroke(); };
  const dot = (x: number, y: number) => { ctx.beginPath(); ctx.fillStyle = VISUAL.line; ctx.arc(x, y, 0.22, 0, Math.PI * 2); ctx.fill(); };
  const s = L / 105;
  poly([[0, 0], [L, 0], [L, W], [0, W]], true);
  poly([[L / 2, 0], [L / 2, W]]);
  arc(L / 2, W / 2, Math.max(3, 9.15 * s), 0, Math.PI * 2);
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
    arc(x, 0, 1, end ? Math.PI / 2 : 0, end ? Math.PI : Math.PI / 2);
    arc(x, W, 1, end ? Math.PI : -Math.PI / 2, end ? Math.PI * 1.5 : 0);
  }
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
  const hair = VISUAL.hair[(look >>> 4) % VISUAL.hair.length];
  const boots = VISUAL.boots[(look >>> 8) % VISUAL.boots.length];
  const hairStyle = (look >>> 12) % 4;
  const wear = p.keeper ? (kit.gk ?? { shirt: VISUAL.keeperKits[p.team], shorts: shade(VISUAL.keeperKits[p.team], -0.45), socks: VISUAL.keeperKits[p.team], trim: "#ffffff" }) : kit;
  const shirt = wear.shirt, shorts = wear.shorts, socks = wear.socks;
  const [fx, fy] = screenDir(g, p.facing);
  const side = fx >= 0 ? 1 : -1;               // sprite mirrored left/right
  const back = fy < -0.45;                       // running up the screen: we see the back (number)
  const run = Math.min(1, p.speed / 7.5);
  const phase = p.stride * Math.PI * 2;
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
  // Athletic proportions (head ~1/6 of the height, long legs, shoulders wider than hips).
  const u = h / 10;
  const hip = -u * 4.7, shoulder = -u * 7.7;
  const thigh = u * 2.35, shin = u * 2.3;
  // Legs: thigh + shin with a knee that folds on the recovery stroke; socks and boots.
  const legW = u * 0.78;
  for (const which of [-1, 1]) {
    const swing = which === 1 ? legA + kickLeg : -legA;
    const hx = which * u * 0.42;
    const kx = hx + Math.sin(swing) * thigh * side, ky = hip + Math.cos(swing) * thigh;
    const bend = Math.max(0, -Math.sin(swing)) * 1.1;
    const fx2 = kx + Math.sin(swing - bend) * shin * side, fy2 = Math.min(0, ky + Math.cos(swing - bend) * shin);
    limb(ctx, hx, hip, kx, ky, legW, skin);
    const sx = kx + (fx2 - kx) * 0.3, sy = ky + (fy2 - ky) * 0.3;
    limb(ctx, kx, ky, sx, sy, legW * 0.92, skin);
    limb(ctx, sx, sy, fx2, fy2, legW * 0.9, socks);
    ctx.fillStyle = boots; ctx.beginPath(); ctx.ellipse(fx2 + side * u * 0.3, fy2 + u * 0.05, u * 0.62, u * 0.3, 0, 0, Math.PI * 2); ctx.fill();
  }
  // Shorts (slightly wider than the hips).
  ctx.fillStyle = shorts; roundRect(ctx, -u * 1.05, hip - u * 0.9, u * 2.1, u * 1.55, u * 0.3); ctx.fill();
  ctx.fillStyle = "rgba(0,0,0,0.12)"; ctx.fillRect(-u * 0.04, hip - u * 0.2, u * 0.08, u * 0.85);
  // Arms: sleeve + forearm with an elbow; behind the torso when seen from behind.
  const arm = (which: number) => {
    const ax = which * u * 1.28, ay = shoulder + u * 0.35;
    let ang = which * 0.18 + (which === 1 ? armA : -armA) * 0.9;
    if (armsUp) ang = which * 2.6; else if (armsWide) ang = which * 1.0;
    const reach = u * 1.45;
    const ex = ax + Math.sin(ang) * reach * (armsUp || armsWide ? 1 : side * which), ey = ay + Math.cos(ang) * reach;
    const elbow = armsUp ? 0 : 0.35 + Math.abs(armA) * 0.5;
    const wx = ex + Math.sin(ang - elbow * side) * u * 1.35 * (armsUp || armsWide ? 1 : side * which), wy = ey + Math.cos(ang - elbow * side) * u * 1.35;
    limb(ctx, ax, ay, ax + (ex - ax) * 0.55, ay + (ey - ay) * 0.55, u * 0.72, shirt);
    limb(ctx, ax + (ex - ax) * 0.55, ay + (ey - ay) * 0.55, ex, ey, u * 0.55, skin);
    limb(ctx, ex, ey, wx, wy, u * 0.5, p.keeper ? "#f4f4f4" : skin);
  };
  if (back) { arm(-1); arm(1); }
  // Torso: tapered jersey (shoulders > waist), kit pattern, collar, number.
  const torso = () => { ctx.beginPath(); ctx.moveTo(-u * 1.45, shoulder + u * 0.25); ctx.quadraticCurveTo(-u * 1.45, shoulder, -u * 1.0, shoulder);
    ctx.lineTo(u * 1.0, shoulder); ctx.quadraticCurveTo(u * 1.45, shoulder, u * 1.45, shoulder + u * 0.25);
    ctx.lineTo(u * 1.1, hip - u * 0.75); ctx.lineTo(-u * 1.1, hip - u * 0.75); ctx.closePath(); };
  ctx.fillStyle = shirt; torso(); ctx.fill();
  ctx.save(); torso(); ctx.clip();
  ctx.fillStyle = wear.trim;
  const th = hip - u * 0.75 - shoulder;
  if (wear.pattern === "hoops") for (let i = 0; i < 3; i += 1) ctx.fillRect(-u * 1.5, shoulder + th * (0.18 + i * 0.3), u * 3, th * 0.12);
  else if (wear.pattern === "stripes") for (let i = 0; i < 4; i += 1) ctx.fillRect(-u * 1.3 + i * u * 0.75, shoulder, u * 0.32, th);
  else if (wear.pattern === "sash") { ctx.beginPath(); ctx.moveTo(-u * 1.5, shoulder + th * 0.05); ctx.lineTo(-u * 0.9, shoulder); ctx.lineTo(u * 1.5, shoulder + th * 0.8); ctx.lineTo(u * 1.5, shoulder + th); ctx.lineTo(u * 0.9, shoulder + th); ctx.closePath(); ctx.fill(); }
  ctx.fillStyle = "rgba(0,0,0,0.12)"; ctx.fillRect(-u * 1.5, shoulder + th * 0.55, u * 3, th * 0.45);    // soft shading
  ctx.restore();
  ctx.fillStyle = wear.trim; ctx.beginPath(); ctx.ellipse(0, shoulder + u * 0.05, u * 0.5, u * 0.22, 0, 0, Math.PI * 2); ctx.fill();  // collar
  ctx.strokeStyle = "rgba(0,0,0,0.3)"; ctx.lineWidth = 1; torso(); ctx.stroke();
  if (p.number && h >= 28 && back) {
    ctx.fillStyle = wear.number ?? contrast(shirt); ctx.font = `900 ${Math.round(u * 1.35)}px "Barlow Condensed", "Arial Narrow", sans-serif`;
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(String(p.number), 0, shoulder + th * 0.42);
  }
  if (!back) { arm(-1); arm(1); }
  // Neck and head (human-sized), hair by style, a simple face when seen from the front.
  ctx.fillStyle = skin; ctx.fillRect(-u * 0.28, shoulder - u * 0.45, u * 0.56, u * 0.55);
  const hy = shoulder - u * 1.15, hr = u * 0.82;
  ctx.fillStyle = skin; ctx.beginPath(); ctx.ellipse(side * u * 0.05, hy, hr * 0.88, hr, 0, 0, Math.PI * 2); ctx.fill();
  ctx.strokeStyle = "rgba(0,0,0,0.25)"; ctx.lineWidth = 0.8; ctx.stroke();
  ctx.fillStyle = hair;
  ctx.beginPath();
  if (back) ctx.ellipse(side * u * 0.05, hy - hr * 0.1, hr * 0.9, hr * 0.92, 0, Math.PI * 0.95, Math.PI * 2.05);
  else ctx.ellipse(side * u * 0.02, hy - hr * 0.42, hr * 0.9, hr * (hairStyle === 0 ? 0.45 : 0.62), 0, Math.PI, Math.PI * 2);
  ctx.fill();
  if (back) { ctx.beginPath(); ctx.ellipse(side * u * 0.05, hy + hr * 0.05, hr * 0.88, hr * 0.7, 0, 0, Math.PI); ctx.fill(); }
  if (hairStyle === 2) { ctx.beginPath(); ctx.ellipse(0, hy - hr * 0.95, hr * 0.35, hr * 0.3, 0, 0, Math.PI * 2); ctx.fill(); }
  if (!back && h >= 34) {
    ctx.fillStyle = "#1a1a1a";
    const ex = side * hr * 0.3;
    ctx.beginPath(); ctx.arc(ex - hr * 0.22, hy + hr * 0.02, Math.max(0.8, hr * 0.09), 0, Math.PI * 2); ctx.arc(ex + hr * 0.22, hy + hr * 0.02, Math.max(0.8, hr * 0.09), 0, Math.PI * 2); ctx.fill();
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

// ---------------------------------------------------------------------------- aim (minimal: one dashed line + a small dot)
/**
 * The only aiming aid: a thin dashed line from the ball along the drag, ending in a small
 * dot at the predicted destination. Its length shows the power. A lofted ball is drawn
 * along its real height profile (the same apex the physics uses); nothing else is drawn.
 */
export function drawAim(ctx: CanvasRenderingContext2D, g: Geometry, view: InteractiveView, from: [number, number], aim: Aim, valid: boolean, ppm: number, now: number) {
  const target = predictTarget(view, from, aim);
  const [x0, y0] = toScreen(g, from[0], from[1]);
  const [x1, y1] = toScreen(g, target[0], target[1]);
  if (Math.hypot(x1 - x0, y1 - y0) < 4) return;
  const color = valid ? "rgba(255,255,255,0.95)" : "rgba(255,110,110,0.95)";
  ctx.save();
  ctx.lineCap = "round";
  ctx.setLineDash([7, 7]);
  ctx.lineDashOffset = -now * 18;
  // Soft dark underlay keeps the line readable on every stripe of grass.
  for (const [w, c] of [[4, "rgba(0,0,0,0.28)"], [2.2, color]] as const) {
    ctx.strokeStyle = c; ctx.lineWidth = w;
    ctx.beginPath(); ctx.moveTo(x0, y0);
    if (aim.type === "LOFT") {
      for (let i = 1; i <= 24; i += 1) {
        const k = i / 24;
        const lift = 4 * 3.2 * k * (1 - k) * ppm * 0.85;      // same apex as the server's lofted ball
        ctx.lineTo(x0 + (x1 - x0) * k, y0 + (y1 - y0) * k - lift);
      }
    } else ctx.lineTo(x1, y1);
    ctx.stroke();
  }
  ctx.setLineDash([]);
  ctx.beginPath(); ctx.fillStyle = "rgba(0,0,0,0.3)"; ctx.arc(x1, y1 + 1, 5, 0, Math.PI * 2); ctx.fill();
  ctx.beginPath(); ctx.fillStyle = color; ctx.arc(x1, y1, 4, 0, Math.PI * 2); ctx.fill();
  ctx.restore();
}
