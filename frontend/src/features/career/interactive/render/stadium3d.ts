import * as THREE from "three";

/**
 * V8 broadcast visuals — stadium, grass, crowd and lighting (presentation only; the match
 * state, physics and collisions never read anything from here).
 *
 * Target: the approved references 01–03/06 (daylight broadcast, natural lawn with wide
 * mowing stripes, dense crowd behind a dark pitch-level wall, railings and aisles, roof
 * canopy). Everything is generated in code: no photos, logos or third-party textures.
 * The crowd is a painted impostor per stand (one draw call per stand, thousands of fans),
 * which is what the references read as at broadcast distance; animated individual fans
 * would cost a lot for nothing visible.
 */
export type StadiumQuality = "low" | "medium" | "high";
type RGB = string;

let rng = 1;
const rand = () => { rng = (rng * 16807) % 2147483647; return rng / 2147483647; };
const seed = (s: number) => { rng = s; };

function canvasTex(w: number, h: number, paint: (g: CanvasRenderingContext2D) => void, srgb = true): THREE.CanvasTexture {
  const c = document.createElement("canvas"); c.width = w; c.height = h;
  paint(c.getContext("2d")!);
  const t = new THREE.CanvasTexture(c);
  if (srgb) t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 16;
  return t;
}

// ------------------------------------------------------------------------------- lighting
/** Afternoon daylight: filmic tone mapping, warm low sun from the main-stand side, soft sky fill. */
export function applyDaylight(renderer: THREE.WebGLRenderer, scene: THREE.Scene, sun: THREE.DirectionalLight, hemi: THREE.HemisphereLight) {
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.1;
  const sky = skyTexture();
  scene.background = sky;
  scene.fog = new THREE.Fog(0xc9d8e3, 140, 520);
  hemi.color.set(0xdfeaf5); hemi.groundColor.set(0x5b6e44); hemi.intensity = 1.05;
  sun.color.set(0xfff0d8); sun.intensity = 2.15;
  // the sun sits behind the camera's stand (+z) and to the left: long shadows pointing away
  sun.position.set(-55, 62, 70);
  sun.target.position.set(0, 0, 0);
}

function skyTexture(): THREE.CanvasTexture {
  const t = canvasTex(4, 256, (g) => {
    const grad = g.createLinearGradient(0, 0, 0, 256);
    grad.addColorStop(0, "#7ea7c8"); grad.addColorStop(0.55, "#b9cfdf"); grad.addColorStop(1, "#dbe6ee");
    g.fillStyle = grad; g.fillRect(0, 0, 4, 256);
  });
  t.mapping = THREE.EquirectangularReflectionMapping;
  return t;
}

// ------------------------------------------------------------------------------- grass
/**
 * Natural lawn: wide mowing stripes across the length (~5.25 m on 11×11), blade grain,
 * soft colour patches, wear in the goal mouths and centre circle, the near stand's shadow,
 * and the official markings. Same painted lines as before (positions are the physical ones).
 */
export function paintGrass(L: number, W: number, margin: number, box: number, res: number): THREE.CanvasTexture {
  const fullL = L + margin * 2, fullW = W + margin * 2;
  const pxm = res / fullL;
  const H = Math.round(fullW * pxm);
  seed(11);
  const tex = canvasTex(res, H, (g) => {
    const X = (m: number) => (m + margin) * pxm, Y = (m: number) => (m + margin) * pxm;
    g.fillStyle = "#788a3e"; g.fillRect(0, 0, res, H);
    // stripes (20 on 105 m), lighter/darker with a soft edge, extending into the margins
    const n = Math.max(10, Math.round(20 * (L / 105)));
    const w = (L / n) * pxm;
    for (let i = -2; i < n + 2; i += 1) {
      const x0 = X((L / n) * i);
      g.fillStyle = i % 2 ? "#809244" : "#6e8139";
      g.fillRect(x0, 0, w + 1, H);
      const edge = g.createLinearGradient(x0, 0, x0 + w * 0.14, 0);
      edge.addColorStop(0, "rgba(0,0,0,0.05)"); edge.addColorStop(1, "rgba(0,0,0,0)");
      g.fillStyle = edge; g.fillRect(x0, 0, w * 0.14, H);
    }
    // large soft patches (natural variation)
    for (let i = 0; i < 70; i += 1) {
      const cx = rand() * res, cy = rand() * H, r = (5 + rand() * 12) * pxm;
      const p = g.createRadialGradient(cx, cy, 0, cx, cy, r);
      p.addColorStop(0, rand() < 0.5 ? "rgba(120,160,60,0.07)" : "rgba(20,60,20,0.08)"); p.addColorStop(1, "rgba(0,0,0,0)");
      g.fillStyle = p; g.fillRect(cx - r, cy - r, r * 2, r * 2);
    }
    // wear: goal mouths, penalty spots and the centre (paler, slightly brown)
    const wear = (cx: number, cy: number, rx: number, ry: number, a: number) => {
      g.save(); g.translate(X(cx), Y(cy)); g.scale(rx * pxm, ry * pxm);
      const p = g.createRadialGradient(0, 0, 0, 0, 0, 1); p.addColorStop(0, `rgba(150,140,90,${a})`); p.addColorStop(1, "rgba(150,140,90,0)");
      g.fillStyle = p; g.beginPath(); g.arc(0, 0, 1, 0, Math.PI * 2); g.fill(); g.restore();
    };
    for (const end of [0, 1]) { const x = end ? L - 2.5 : 2.5; wear(x, W / 2, 3.5, 5.5, 0.2); wear(end ? L - box * 0.67 : box * 0.67, W / 2, 2.2, 2.2, 0.12); }
    wear(L / 2, W / 2, 5, 5, 0.06);
    // blade grain (fine, two tones)
    const grains = Math.round(res * H / 40);
    for (let i = 0; i < grains; i += 1) {
      g.fillStyle = rand() < 0.5 ? "rgba(255,255,215,0.06)" : "rgba(10,30,5,0.08)";
      g.fillRect(rand() * res, rand() * H, 1 + rand() * 1.5, 1.5 + rand() * 3);
    }
    // the near stand's shadow on the grass (+y side, sun behind that stand): soft band
    const sh = g.createLinearGradient(0, Y(W + margin), 0, Y(W - 9));
    sh.addColorStop(0, "rgba(10,25,20,0.42)"); sh.addColorStop(0.55, "rgba(10,25,20,0.30)"); sh.addColorStop(1, "rgba(10,25,20,0)");
    g.fillStyle = sh; g.fillRect(0, Y(W - 9), res, Y(W + margin) - Y(W - 9));
    // surround slightly darker
    g.fillStyle = "rgba(15,40,15,0.18)";
    g.fillRect(0, 0, res, Y(0)); g.fillRect(0, Y(W), res, margin * pxm); g.fillRect(0, 0, X(0), H); g.fillRect(X(L), 0, margin * pxm, H);
    // markings (12 cm lines), physical positions
    g.strokeStyle = "rgba(250,250,245,0.92)"; g.lineWidth = Math.max(2, 0.12 * pxm); g.lineCap = "round";
    const poly = (pts: [number, number][], close = false) => { g.beginPath(); pts.forEach(([x, y], i) => (i ? g.lineTo(X(x), Y(y)) : g.moveTo(X(x), Y(y)))); if (close) g.closePath(); g.stroke(); };
    const s = L / 105;
    poly([[0, 0], [L, 0], [L, W], [0, W]], true); poly([[L / 2, 0], [L / 2, W]]);
    g.beginPath(); g.arc(X(L / 2), Y(W / 2), 9.15 * s * pxm, 0, Math.PI * 2); g.stroke();
    g.fillStyle = "rgba(250,250,245,0.95)";
    g.beginPath(); g.arc(X(L / 2), Y(W / 2), 0.22 * pxm, 0, Math.PI * 2); g.fill();
    const halfBox = Math.min(W * 0.46, box * (20.16 / 16.5)), six = box / 3, halfSix = Math.min(W * 0.3, box * (9.16 / 16.5));
    const spot = box * (11 / 16.5), arcR = box * (9.15 / 16.5);
    for (const end of [0, 1]) {
      const x = end ? L : 0, d = end ? -1 : 1;
      poly([[x, W / 2 - halfBox], [x + d * box, W / 2 - halfBox], [x + d * box, W / 2 + halfBox], [x, W / 2 + halfBox]]);
      poly([[x, W / 2 - halfSix], [x + d * six, W / 2 - halfSix], [x + d * six, W / 2 + halfSix], [x, W / 2 + halfSix]]);
      g.beginPath(); g.arc(X(x + d * spot), Y(W / 2), 0.22 * pxm, 0, Math.PI * 2); g.fill();
      const lim = Math.acos(Math.min(1, (box - spot) / arcR));
      g.beginPath(); if (end) g.arc(X(x + d * spot), Y(W / 2), arcR * pxm, Math.PI - lim, Math.PI + lim); else g.arc(X(x + d * spot), Y(W / 2), arcR * pxm, -lim, lim); g.stroke();
      // corner arcs
      for (const cy of [0, W]) { g.beginPath(); g.arc(X(x), Y(cy), 1 * s * pxm, cy === 0 ? (end ? Math.PI / 2 : 0) : (end ? Math.PI : -Math.PI / 2), cy === 0 ? (end ? Math.PI : Math.PI / 2) : (end ? Math.PI * 1.5 : 0)); g.stroke(); }
    }
  });
  return tex;
}

// ------------------------------------------------------------------------------- crowd impostor
type Palette = { primary: RGB; secondary: RGB; away: RGB };
const crowdCache = new Map<string, THREE.CanvasTexture>();
/** A painted section of terrace: seat rows, fans (team colours dominant), aisles with stairs. */
function crowdTexture(p: Palette, quality: StadiumQuality): THREE.CanvasTexture {
  const key = `${p.primary}|${p.secondary}|${p.away}|${quality}`;
  const hit = crowdCache.get(key);
  if (hit) return hit;
  const W = quality === "high" ? 4096 : quality === "medium" ? 2048 : 1024;
  const H = W / 4;
  const rows = 34, rowH = H / rows;
  const seatW = rowH * 0.62;
  seed(99);
  const tex = canvasTex(W, H, (g) => {
    g.fillStyle = "#5b6470"; g.fillRect(0, 0, W, H);
    const shirts = [p.primary, p.primary, p.secondary, "#e9e9e6", "#e9e9e6", "#d8d5cc", "#2a2a2a", "#3b4250", "#6f7680", "#8f8a80", p.away].map((c) => muted(c));
    const skins = ["#f1c9a5", "#e0ac83", "#c68a5e", "#a8693f", "#8a5530", "#6b3f22"];
    const hair = ["#1b120c", "#2b1a10", "#4a2e16", "#0e0e0e", "#6b4423"];
    const aisleEvery = Math.round(W / 7);
    for (let r = 0; r < rows; r += 1) {
      const y0 = r * rowH;
      // concrete step and seat row
      g.fillStyle = "#6c7480"; g.fillRect(0, y0 + rowH * 0.78, W, rowH * 0.22);
      g.fillStyle = "#4a525d"; g.fillRect(0, y0 + rowH * 0.74, W, rowH * 0.05);
      const depthShade = 0.55 + 0.45 * (r / rows);   // back rows (top) sit under the roof shadow
      for (let x = rowH * 0.2 + (r % 2) * seatW * 0.5; x < W; x += seatW) {
        if (Math.abs(((x + aisleEvery / 2) % aisleEvery) - aisleEvery / 2) < seatW * 1.4) continue;   // aisle
        if (rand() < 0.05) {   // empty seat
          g.fillStyle = "#4d5a6e"; g.fillRect(x, y0 + rowH * 0.42, seatW * 0.82, rowH * 0.34); continue;
        }
        const standing = rand() < 0.3;
        const top = y0 + rowH * (standing ? 0.02 : 0.14);
        const shirt = shirts[Math.floor(rand() * shirts.length)];
        const bw = seatW * (0.78 + rand() * 0.12);
        const bx = x + (seatW - bw) / 2 + (rand() - 0.5) * seatW * 0.15;
        // torso with shading
        const tg = g.createLinearGradient(bx, 0, bx + bw, 0);
        tg.addColorStop(0, shade(shirt, -0.25 * depthShade)); tg.addColorStop(0.5, shade(shirt, 0.05 - (1 - depthShade) * 0.3)); tg.addColorStop(1, shade(shirt, -0.35));
        g.fillStyle = tg;
        g.beginPath(); g.roundRect(bx, top + rowH * 0.3, bw, rowH * 0.5, bw * 0.28); g.fill();
        // raised arms (celebrating / waving)
        if (standing && rand() < 0.25) { g.strokeStyle = shade(shirt, -0.1); g.lineWidth = Math.max(1, bw * 0.16); g.beginPath(); g.moveTo(bx + bw * 0.85, top + rowH * 0.36); g.lineTo(bx + bw * 1.05, top - rowH * 0.12); g.stroke(); }
        // head and hair
        const hr = bw * 0.24;
        const hx = bx + bw / 2, hy = top + rowH * 0.2;
        g.fillStyle = shade(skins[Math.floor(rand() * skins.length)], -(1 - depthShade) * 0.35);
        g.beginPath(); g.arc(hx, hy, hr, 0, Math.PI * 2); g.fill();
        g.fillStyle = hair[Math.floor(rand() * hair.length)];
        g.beginPath(); g.arc(hx, hy - hr * 0.25, hr * 0.95, Math.PI, Math.PI * 2); g.fill();
      }
    }
    // aisles: stairs with yellow-edged steps
    for (let x = 0; x < W; x += aisleEvery) {
      const ax = x - seatW * 0.9, aw = seatW * 1.8;
      g.fillStyle = "#8a9099"; g.fillRect(ax, 0, aw, H);
      for (let r = 0; r < rows * 2; r += 1) { g.fillStyle = r % 2 ? "#767c86" : "#9aa0a8"; g.fillRect(ax, r * rowH / 2, aw, rowH / 2); }
      g.fillStyle = "#e0c341"; g.fillRect(ax, 0, aw * 0.06, H); g.fillRect(ax + aw * 0.94, 0, aw * 0.06, H);
      g.fillStyle = "#c9ced4"; g.fillRect(ax + aw * 0.47, 0, aw * 0.06, H);   // handrail
    }
    // roof shadow at the very top
    const rs = g.createLinearGradient(0, 0, 0, H * 0.35);
    rs.addColorStop(0, "rgba(10,14,22,0.55)"); rs.addColorStop(1, "rgba(10,14,22,0)");
    g.fillStyle = rs; g.fillRect(0, 0, W, H * 0.35);
  });
  tex.wrapS = THREE.RepeatWrapping;
  tex.anisotropy = 8;
  crowdCache.set(key, tex);
  return tex;
}

/** Fans' clothes read as muted at distance (sun-faded, mixed tones), never as pure UI colours. */
function muted(hex: string): string {
  const c = new THREE.Color(hex);
  const hsl = { h: 0, s: 0, l: 0 }; c.getHSL(hsl);
  c.setHSL(hsl.h, hsl.s * 0.62, Math.min(0.82, hsl.l * 0.92 + 0.04));
  return `#${c.getHexString()}`;
}

function shade(hex: string, amount: number): string {
  const c = new THREE.Color(hex);
  if (amount < 0) c.multiplyScalar(1 + amount); else c.lerp(new THREE.Color(1, 1, 1), amount);
  return `#${c.getHexString()}`;
}

function boardTexture(): THREE.CanvasTexture {
  // pitch-level wall: dark navy panels with a discreet fictitious wordmark (no real sponsors)
  const t = canvasTex(2048, 64, (g) => {
    g.fillStyle = "#1f2c46"; g.fillRect(0, 0, 2048, 64);
    for (let i = 0; i < 8; i += 1) {
      g.fillStyle = i % 2 ? "#22304c" : "#1b2740"; g.fillRect(i * 256, 0, 256, 64);
      g.fillStyle = "rgba(220,230,245,0.22)"; g.font = "700 26px 'Barlow Condensed', 'Arial Narrow', sans-serif"; g.textAlign = "center"; g.textBaseline = "middle";
      g.fillText(i % 2 ? "RESENHA" : "BRASILEIRÃO MANAGER", i * 256 + 128, 33);
    }
    g.fillStyle = "rgba(255,255,255,0.08)"; g.fillRect(0, 0, 2048, 3);
  });
  t.wrapS = THREE.RepeatWrapping;
  return t;
}

// ------------------------------------------------------------------------------- stadium
export type StadiumOptions = { fullL: number; fullW: number; quality: StadiumQuality; shadows: boolean; home: { primary: string; secondary: string }; away: { primary: string } };

/**
 * Bowl: pitch-level wall with fictitious boards, a front concrete wall with a railing,
 * a raked terrace (crowd impostor) on each side and in the corners, a back wall and a roof
 * canopy with steel beams and floodlight strips. Returns the crowd group (it bounces on goals).
 */
export function buildStadium(group: THREE.Group, o: StadiumOptions): THREE.Group {
  const { fullL, fullW, quality } = o;
  const scale = Math.max(0.55, fullL / 121);
  const crowdTex = crowdTexture({ primary: o.home.primary, secondary: o.home.secondary, away: o.away.primary }, quality);
  const concrete = new THREE.MeshLambertMaterial({ color: 0x5d646e });
  const darkWall = new THREE.MeshLambertMaterial({ color: 0x263247 });
  const steel = new THREE.MeshLambertMaterial({ color: 0x7c8590 });
  const roofMat = new THREE.MeshLambertMaterial({ color: 0xd9dee3, side: THREE.DoubleSide });
  const railMat = new THREE.MeshLambertMaterial({ color: 0xc7ccd2 });
  const boardTex = boardTexture();
  const crowd = new THREE.Group();
  // pitch-level boards (1 m) right outside the margins
  const gap = 1.2;
  const boards: [number, number, number, number][] = [[0, -fullW / 2 - gap, fullL + gap * 2, 0], [0, fullW / 2 + gap, fullL + gap * 2, Math.PI], [-fullL / 2 - gap, 0, fullW + gap * 2, Math.PI / 2], [fullL / 2 + gap, 0, fullW + gap * 2, -Math.PI / 2]];
  for (const [x, z, len, ry] of boards) {
    const t = boardTex.clone(); t.needsUpdate = true; t.repeat.set(len / 32, 1);
    const b = new THREE.Mesh(new THREE.BoxGeometry(len, 1.0, 0.2), [darkWall, darkWall, darkWall, darkWall, new THREE.MeshLambertMaterial({ map: t }), darkWall]);
    b.position.set(x, 0.5, z); b.rotation.y = ry; b.castShadow = o.shadows; group.add(b);
  }
  // stands: four sides + four corners, each a raked plane with the crowd impostor
  const front = 4.5 * scale + gap;   // from the touchline margin to the stand's front wall
  const rake = { depth: 24 * scale, rise: 13 * scale, base: 2.2 };
  const sides = [
    // the long sides run through the corners and close the bowl behind the end stands
    { len: fullL + 2 * (front + rake.depth + 1), d: fullW / 2 + front, ry: 0 },
    { len: fullL + 2 * (front + rake.depth + 1), d: fullW / 2 + front, ry: Math.PI },
    { len: fullW + 2, d: fullL / 2 + front, ry: Math.PI / 2 },
    { len: fullW + 2, d: fullL / 2 + front, ry: -Math.PI / 2 },
  ];
  const standGroup = (len: number, d: number, ry: number, texOffset: number, cameraSide: boolean) => {
    const s = new THREE.Group();
    const fans = new THREE.Group();   // the terrace bounces on goals: own group, same rotation as its stand
    // front wall + railing
    const wall = new THREE.Mesh(new THREE.BoxGeometry(len, rake.base, 0.5), darkWall); wall.position.set(0, rake.base / 2, -d); s.add(wall);
    const rail = new THREE.Mesh(new THREE.BoxGeometry(len, 0.06, 0.06), railMat); rail.position.set(0, rake.base + 1.0, -d - 0.2); s.add(rail);
    for (let x = -len / 2; x <= len / 2; x += 2.5) { const post = new THREE.Mesh(new THREE.BoxGeometry(0.05, 1.0, 0.05), railMat); post.position.set(x, rake.base + 0.5, -d - 0.2); s.add(post); }
    // terrace (crowd)
    const slope = Math.hypot(rake.depth, rake.rise);
    const t = crowdTex.clone(); t.needsUpdate = true; t.repeat.set(len / (slope * 4) * 1.0, 1); t.offset.x = texOffset;
    const terrace = new THREE.Mesh(new THREE.PlaneGeometry(len, slope), new THREE.MeshLambertMaterial({ map: t }));
    terrace.position.set(0, rake.base + rake.rise / 2, -d - rake.depth / 2);
    terrace.rotation.x = -(Math.PI / 2 - Math.atan2(rake.rise, rake.depth));
    terrace.receiveShadow = o.shadows;
    fans.add(terrace); fans.rotation.y = ry; crowd.add(fans);
    if (cameraSide) { s.rotation.y = ry; group.add(s); return; }   // the TV gantry side: no roof/back wall between the camera and the pitch
    // back wall, roof canopy and beams
    const backH = rake.base + rake.rise + 6 * scale;
    const back = new THREE.Mesh(new THREE.BoxGeometry(len, backH, 0.8), concrete); back.position.set(0, backH / 2, -d - rake.depth - 0.4); s.add(back);
    if (quality !== "low") {
      const roofDepth = rake.depth * 0.95;
      const roof = new THREE.Mesh(new THREE.PlaneGeometry(len + 2, roofDepth), roofMat);
      roof.position.set(0, backH + 2.5 * scale, -d - rake.depth + roofDepth / 2 - 0.5); roof.rotation.x = -Math.PI / 2 + 0.06; s.add(roof);
      const edge = new THREE.Mesh(new THREE.BoxGeometry(len + 2, 0.9, 0.9), steel); edge.position.set(0, backH + 2.5 * scale + 0.4, -d - rake.depth + roofDepth - 0.5); s.add(edge);
      for (let x = -len / 2; x <= len / 2 + 0.1; x += 10) {
        const beam = new THREE.Mesh(new THREE.BoxGeometry(0.4, 0.8, roofDepth), steel); beam.position.set(x, backH + 2.5 * scale - 0.4, -d - rake.depth + roofDepth / 2 - 0.5); beam.rotation.x = 0.06; s.add(beam);
      }
      for (let x = -len / 2 + 4; x < len / 2; x += 7) { const lamp = new THREE.Mesh(new THREE.BoxGeometry(1.6, 0.6, 0.3), new THREE.MeshBasicMaterial({ color: 0xfffdf0 })); lamp.position.set(x, backH + 2.5 * scale - 0.2, -d - rake.depth + roofDepth - 1.2); s.add(lamp); }
    }
    s.rotation.y = ry;
    group.add(s);
  };
  sides.forEach((sd, i) => standGroup(sd.len, sd.d, sd.ry, i * 0.31, i === 1));
  group.add(crowd);
  return crowd;
}

/** Corner flags at the physical pitch corners (L × W, centred). */
export function cornerFlags(group: THREE.Group, L: number, W: number) {
  const pole = new THREE.MeshLambertMaterial({ color: 0xf4f4f4 });
  const cloth = new THREE.MeshLambertMaterial({ color: 0xf2c230, side: THREE.DoubleSide });
  for (const [sx, sz] of [[1, 1], [-1, 1], [1, -1], [-1, -1]]) {
    const p = new THREE.Mesh(new THREE.CylinderGeometry(0.025, 0.025, 1.5, 6), pole); p.position.set(sx * L / 2, 0.75, sz * W / 2); group.add(p);
    const f = new THREE.Mesh(new THREE.PlaneGeometry(0.42, 0.3), cloth); f.position.set(sx * L / 2 + 0.21, 1.33, sz * W / 2); group.add(f);
  }
}
