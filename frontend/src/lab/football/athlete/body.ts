import * as THREE from "three";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import { BONE_INDEX, JOINT, type BoneName } from "./rig";

/**
 * Athlete mesh built from *lofted* anatomical cross-sections (research prototype).
 *
 * Unlike the V6 athlete (separate capsules per segment), the torso, each leg and each arm
 * is one continuous surface swept along its joint chain, so knees, elbows and hips bend as
 * one skin. Each ring is a super-ellipse with its own half-width, half-depth, offsets and
 * exponent, keyed by distance along the chain (values are real measurements in metres for
 * a 1.82 m athlete). Skin weights blend linearly in metres across each joint.
 *
 * Geometry is built once per (detail, hair, variant) and shared; a player only owns its
 * colour attribute and kit texture.
 */
export type Detail = "low" | "medium" | "high";
export const REGIONS = ["skin", "shirt", "trim", "shorts", "shortsTrim", "socks", "sockTrim", "boots", "sole", "hair", "eye", "brow", "lips", "gloves"] as const;
export type Region = typeof REGIONS[number];
export type BodyVariant = { keeper: boolean; hair: number; build: number };

type V3 = [number, number, number];
type Key = { m: number; w: number; d: number; fz?: number; fx?: number; e?: number };
type Marker = { bone: BoneName; m: number };
type Loft = {
  path: V3[];
  keys: Key[];
  depthRef: V3;
  markers: Marker[];
  blend: number;
  region: (m: number, p: THREE.Vector3, ang: number) => Region;
  uv?: (p: THREE.Vector3, m: number, ang: number) => [number, number];
  radial: number;
  density: number;          // rings per metre
  extraWeight?: (p: THREE.Vector3, w: [number, number, number, number], idx: [number, number, number, number]) => void;
};

const WHITE_UV: [number, number] = [0.5, 0.985];   // kit texture keeps a white strip at the top
/** Kit texture layout (see kit.ts): shirt in v [0, SHIRT_V], face patch in u [0, 0.25] x v [FACE_V0, FACE_V1]. */
export const SHIRT_V = 0.7;
export const FACE_V0 = 0.72, FACE_V1 = 0.97;
/** Planar face projection, clamped to the patch border (white) so the mapping stays continuous. */
function faceUv(dir: THREE.Vector3): [number, number] {
  const k = dir.z > 0.25 ? 1 : 10;
  const fx = Math.max(-1, Math.min(1, (dir.x / 0.75) * k));
  const fy = Math.max(-1, Math.min(1, ((dir.y + 0.1) / 0.75) * (dir.z > 0.25 ? 1 : (dir.y + 0.1 >= 0 ? 10 : 10))));
  const cu = 0.125, cv = (FACE_V0 + FACE_V1) / 2, hu = 0.122, hv = (FACE_V1 - FACE_V0) / 2 * 0.98;
  return [cu + fx * hu, cv + fy * hv];
}
const tmpA = new THREE.Vector3();

function catmull(keys: Key[], m: number, field: keyof Key, fallback: number): number {
  const val = (k: Key) => (k[field] as number | undefined) ?? fallback;
  if (m <= keys[0].m) return val(keys[0]);
  const last = keys[keys.length - 1];
  if (m >= last.m) return val(last);
  let i = 0;
  while (i < keys.length - 2 && keys[i + 1].m < m) i += 1;
  const k0 = keys[Math.max(0, i - 1)], k1 = keys[i], k2 = keys[i + 1], k3 = keys[Math.min(keys.length - 1, i + 2)];
  const t = (m - k1.m) / (k2.m - k1.m);
  // Centripetal-like Catmull-Rom on values with uniform parameter, clamped between neighbours
  const p0 = val(k0), p1 = val(k1), p2 = val(k2), p3 = val(k3);
  const t2 = t * t, t3 = t2 * t;
  const v = 0.5 * (2 * p1 + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t3);
  const lo = Math.min(p1, p2), hi = Math.max(p1, p2), pad = (hi - lo) * 0.25 + 1e-4;
  return Math.max(lo - pad, Math.min(hi + pad, v));
}

function pathLengths(path: V3[]): number[] {
  const out = [0];
  for (let i = 1; i < path.length; i += 1) {
    const [ax, ay, az] = path[i - 1], [bx, by, bz] = path[i];
    out.push(out[i - 1] + Math.hypot(bx - ax, by - ay, bz - az));
  }
  return out;
}

function pointAt(path: V3[], lens: number[], m: number, out: THREE.Vector3): THREE.Vector3 {
  const total = lens[lens.length - 1];
  const mm = Math.max(0, Math.min(total, m));
  let i = 1;
  while (i < lens.length - 1 && lens[i] < mm) i += 1;
  const t = (mm - lens[i - 1]) / Math.max(1e-9, lens[i] - lens[i - 1]);
  const a = path[i - 1], b = path[i];
  return out.set(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t);
}

function buildLoft(spec: Loft): THREE.BufferGeometry {
  const lens = pathLengths(spec.path);
  const total = lens[lens.length - 1];
  const n = Math.max(4, Math.ceil(total * spec.density));
  const stations = new Set<number>();
  for (let i = 0; i <= n; i += 1) stations.add(+(total * i / n).toFixed(5));
  for (const k of spec.keys) if (k.m > 0 && k.m < total) stations.add(+k.m.toFixed(5));
  const ms = [...stations].sort((a, b) => a - b);
  const R = spec.radial;
  const pos: number[] = [], uv: number[] = [], reg: number[] = [], si: number[] = [], sw: number[] = [];
  const P = new THREE.Vector3(), T = new THREE.Vector3(), F = new THREE.Vector3(), S = new THREE.Vector3(), V = new THREE.Vector3();
  const ref = new THREE.Vector3(...spec.depthRef);
  let handed = 0;
  const pushVertex = (v: THREE.Vector3, m: number, ang: number) => {
    pos.push(v.x, v.y, v.z);
    const r = spec.region(m, v, ang);
    reg.push(REGIONS.indexOf(r));
    const [u, w] = spec.uv && (r === "shirt") ? spec.uv(v, m, ang) : WHITE_UV;
    uv.push(u, w);
    const { idx, wt } = weightsAt(spec, m, v);
    si.push(...idx); sw.push(...wt);
  };
  for (const m of ms) {
    pointAt(spec.path, lens, m, P);
    const h = Math.min(0.03, total * 0.05);
    T.copy(pointAt(spec.path, lens, Math.min(total, m + h), tmpA)).sub(pointAt(spec.path, lens, Math.max(0, m - h), V)).normalize();
    F.copy(ref).addScaledVector(T, -ref.dot(T)).normalize();
    S.crossVectors(F, T).normalize();
    if (handed === 0) handed = S.x + S.y * 0.001 >= 0 ? 1 : -1;
    S.multiplyScalar(handed);
    const w = catmull(spec.keys, m, "w", 0.05), d = catmull(spec.keys, m, "d", 0.05);
    const fz = catmull(spec.keys, m, "fz", 0), fx = catmull(spec.keys, m, "fx", 0), ex = catmull(spec.keys, m, "e", 2);
    for (let j = 0; j <= R; j += 1) {
      const a = (j / R) * Math.PI * 2;
      const c = Math.cos(a), s = Math.sin(a);
      const cx = Math.sign(c) * Math.abs(c) ** (2 / ex), sz = Math.sign(s) * Math.abs(s) ** (2 / ex);
      V.copy(P).addScaledVector(S, w * cx + fx).addScaledVector(F, d * sz + fz);
      pushVertex(V, m, a);
    }
  }
  const idx: number[] = [];
  const row = R + 1;
  for (let i = 0; i < ms.length - 1; i += 1) {
    for (let j = 0; j < R; j += 1) {
      const a = i * row + j, b = a + 1, c = a + row, d2 = c + 1;
      idx.push(a, c, b, b, c, d2);
    }
  }
  // caps (fan to the centre of the first/last ring)
  for (const [ring, m] of [[0, ms[0]], [ms.length - 1, ms[ms.length - 1]]] as const) {
    pointAt(spec.path, lens, m, P);
    const fz = catmull(spec.keys, m, "fz", 0), fx = catmull(spec.keys, m, "fx", 0);
    T.copy(pointAt(spec.path, lens, Math.min(total, m + 0.01), tmpA)).sub(pointAt(spec.path, lens, Math.max(0, m - 0.01), V)).normalize();
    F.copy(ref).addScaledVector(T, -ref.dot(T)).normalize();
    S.crossVectors(F, T).normalize().multiplyScalar(handed);
    V.copy(P).addScaledVector(S, fx).addScaledVector(F, fz);
    const centre = pos.length / 3;
    pushVertex(V, m, 0);
    for (let j = 0; j < R; j += 1) {
      const a = ring * row + j, b = a + 1;
      if (ring === 0) idx.push(centre, a, b); else idx.push(centre, b, a);
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("uv", new THREE.Float32BufferAttribute(uv, 2));
  g.setAttribute("region", new THREE.Float32BufferAttribute(reg, 1));
  g.setAttribute("skinIndex", new THREE.Uint16BufferAttribute(si, 4));
  g.setAttribute("skinWeight", new THREE.Float32BufferAttribute(sw, 4));
  g.setIndex(idx);
  orientOutwards(g, spec, lens);
  g.computeVertexNormals();
  return g;
}

/** Flip the winding if the normals point inwards (decided once per loft at its middle ring). */
function orientOutwards(g: THREE.BufferGeometry, spec: Loft, lens: number[]): void {
  const index = g.getIndex()!;
  const pos = g.getAttribute("position") as THREE.BufferAttribute;
  const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3(), centre = new THREE.Vector3();
  const total = lens[lens.length - 1];
  const tri = Math.floor(index.count / 6) * 3;   // a triangle around the middle of the side wall
  a.fromBufferAttribute(pos, index.getX(tri)); b.fromBufferAttribute(pos, index.getX(tri + 1)); c.fromBufferAttribute(pos, index.getX(tri + 2));
  const normal = new THREE.Vector3().subVectors(b, a).cross(new THREE.Vector3().subVectors(c, a));
  const mid = a.clone().add(b).add(c).divideScalar(3);
  // closest point on the path
  let best = Infinity;
  for (let i = 0; i <= 40; i += 1) {
    pointAt(spec.path, lens, total * i / 40, tmpA);
    const dd = tmpA.distanceToSquared(mid);
    if (dd < best) { best = dd; centre.copy(tmpA); }
  }
  if (normal.dot(mid.sub(centre)) < 0) {
    const arr = index.array as Uint16Array | Uint32Array;
    for (let i = 0; i < arr.length; i += 3) { const t = arr[i + 1]; arr[i + 1] = arr[i + 2]; arr[i + 2] = t; }
    index.needsUpdate = true;
  }
}

function smooth01(x: number): number { const t = Math.max(0, Math.min(1, x)); return t * t * (3 - 2 * t); }

function weightsAt(spec: Loft, m: number, p: THREE.Vector3): { idx: [number, number, number, number]; wt: [number, number, number, number] } {
  const mk = spec.markers;
  let i = 0;
  while (i < mk.length - 1 && mk[i + 1].m <= m) i += 1;
  const idx: [number, number, number, number] = [BONE_INDEX[mk[i].bone], 0, 0, 0];
  const wt: [number, number, number, number] = [1, 0, 0, 0];
  const next = mk[i + 1], prev = i > 0 ? mk[i - 1] : null;
  if (next && next.m - m < spec.blend) {
    const w = smooth01(0.5 + (m - next.m) / (2 * spec.blend));
    idx[1] = BONE_INDEX[next.bone]; wt[0] = 1 - w; wt[1] = w;
  } else if (prev && m - mk[i].m < spec.blend) {
    const w = smooth01(0.5 + (m - mk[i].m) / (2 * spec.blend));
    idx[1] = BONE_INDEX[prev.bone]; wt[0] = w; wt[1] = 1 - w;
  }
  spec.extraWeight?.(p, wt, idx);
  const sum = wt[0] + wt[1] + wt[2] + wt[3];
  for (let k = 0; k < 4; k += 1) wt[k] /= sum;
  return { idx, wt };
}

// ------------------------------------------------------------------ head
type HeadOpts = { seg: number; rings: number };
const HEAD_C = new THREE.Vector3(0, 1.706, 0.012);
/** Skull + face as a displaced ellipsoid (unit direction -> surface point). */
function headSurface(dir: THREE.Vector3, out: THREE.Vector3): THREE.Vector3 {
  const { x, y, z } = dir;
  let rx = 0.077, rz = 0.098;
  const ry = 0.112;
  if (y < 0) { const k = (-y) ** 1.4; rx *= 1 - 0.3 * k * (z > -0.2 ? 1 : 0.6); rz *= 1 - 0.12 * k * (z < 0 ? 1.8 : 0); }   // jaw and chin taper, no back of neck
  if (z < -0.1 && y > -0.35) rz *= 1.07;                    // occiput
  if (z > 0.55) rz *= 0.965;                                // flatter face
  out.set(x * rx, y * ry, z * rz);
  const g = (cx: number, cy: number, sx: number, sy: number) => Math.exp(-(((x - cx) / sx) ** 2) - (((y - cy) / sy) ** 2));
  if (z > 0) {
    out.z += 0.018 * g(0, -0.08, 0.14, 0.22) * z;           // nose
    out.z += 0.007 * g(0, -0.13, 0.22, 0.06) * z;           // nose base
    out.z += 0.006 * (g(-0.3, 0.2, 0.25, 0.07) + g(0.3, 0.2, 0.25, 0.07)) * z;   // brow ridge
    out.z -= 0.007 * (g(-0.32, 0.08, 0.13, 0.08) + g(0.32, 0.08, 0.13, 0.08)) * z;  // eye sockets
    out.z += 0.006 * g(0, -0.5, 0.25, 0.1) * z;             // lips
    out.z += 0.009 * g(0, -0.8, 0.28, 0.15) * z;            // chin
    out.x += 0.006 * x * (g(-0.62, -0.1, 0.2, 0.15) + g(0.62, -0.1, 0.2, 0.15));   // cheekbones
  }
  return out.add(HEAD_C);
}

function hairMask(style: number, d: THREE.Vector3): number {
  if (style === 4) return 0;   // shaved
  const front = 0.5 + (style === 2 ? 0.06 : 0);        // forehead hairline
  const side = style === 2 ? 0.12 : 0.02;               // above the ears
  const back = style === 3 ? -0.5 : -0.38;              // nape
  // hairline height as a function of where we look (front -> side -> back)
  const line = d.z > 0 ? front * d.z ** 2 + side * (1 - d.z ** 2) : back * d.z ** 2 + side * (1 - d.z ** 2);
  return smooth01((d.y - line) / 0.16);
}
function hairThickness(style: number, d: THREE.Vector3): number {
  switch (style) {
    case 0: return 0.009 + 0.006 * Math.max(0, d.y);                        // short crop
    case 1: return 0.012 + 0.022 * Math.max(0, d.y) + 0.006 * Math.max(0, -d.z);   // medium, volume on top
    case 2: return 0.004;                                                   // buzz cut
    case 3: return 0.022 + 0.035 * Math.max(0, d.y) ** 0.7;                 // curly volume
    default: return 0;
  }
}

function sphereGeometry(opts: HeadOpts & { phiMax?: number; uv?: (dir: THREE.Vector3) => [number, number] }, surf: (dir: THREE.Vector3, out: THREE.Vector3) => THREE.Vector3, region: (dir: THREE.Vector3) => Region, weight: (p: THREE.Vector3) => [number, number, number, number, number, number, number, number]): THREE.BufferGeometry {
  const pos: number[] = [], uv: number[] = [], reg: number[] = [], si: number[] = [], sw: number[] = [];
  const dir = new THREE.Vector3(), p = new THREE.Vector3();
  for (let i = 0; i <= opts.rings; i += 1) {
    const phi = (i / opts.rings) * Math.PI * (opts.phiMax ?? 1);          // 0 = top
    for (let j = 0; j <= opts.seg; j += 1) {
      const th = (j / opts.seg) * Math.PI * 2;
      dir.set(Math.sin(phi) * Math.sin(th), Math.cos(phi), Math.sin(phi) * Math.cos(th));
      surf(dir, p);
      pos.push(p.x, p.y, p.z); uv.push(...(opts.uv ? opts.uv(dir) : WHITE_UV));
      reg.push(REGIONS.indexOf(region(dir)));
      const w = weight(p);
      si.push(w[0], w[1], w[2], w[3]); sw.push(w[4], w[5], w[6], w[7]);
    }
  }
  const idx: number[] = [];
  const row = opts.seg + 1;
  for (let i = 0; i < opts.rings; i += 1) for (let j = 0; j < opts.seg; j += 1) {
    const a = i * row + j, b = a + 1, c = a + row, d = c + 1;
    if (i > 0) idx.push(a, c, b);
    if (i < opts.rings - 1 || (opts.phiMax ?? 1) < 1) idx.push(b, c, d);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("uv", new THREE.Float32BufferAttribute(uv, 2));
  g.setAttribute("region", new THREE.Float32BufferAttribute(reg, 1));
  g.setAttribute("skinIndex", new THREE.Uint16BufferAttribute(si, 4));
  g.setAttribute("skinWeight", new THREE.Float32BufferAttribute(sw, 4));
  g.setIndex(idx);
  g.computeVertexNormals();
  return g;
}

function ellipsoid(c: V3, r: V3, seg: number, region: Region, bone: BoneName): THREE.BufferGeometry {
  return sphereGeometry({ seg, rings: Math.max(4, Math.round(seg * 0.6)) },
    (d, out) => out.set(c[0] + d.x * r[0], c[1] + d.y * r[1], c[2] + d.z * r[2]), () => region,
    () => [BONE_INDEX[bone], 0, 0, 0, 1, 0, 0, 0]);
}

// ------------------------------------------------------------------ body assembly
const cache = new Map<string, THREE.BufferGeometry>();

export function bodyGeometry(detail: Detail, variant: BodyVariant): THREE.BufferGeometry {
  const key = `${detail}|${variant.keeper ? 1 : 0}|${variant.hair}|${variant.build.toFixed(2)}`;
  const hit = cache.get(key);
  if (hit) return hit;
  const q = detail === "high" ? 1 : detail === "medium" ? 0.68 : 0.45;
  const rad = (n: number) => Math.max(6, Math.round(n * q / 2) * 2);
  const den = (n: number) => n * q;
  const bw = 1 + (variant.build - 0.5) * 0.12;     // slimmer <-> stockier, widths only
  const W = (k: Key): Key => ({ ...k, w: k.w * bw, d: k.d * (1 + (bw - 1) * 0.7) });
  const parts: THREE.BufferGeometry[] = [];

  // Torso: crotch -> neck, one surface. Shirt above the waistband, shorts below.
  const torsoPath: V3[] = [[0, 0.865, 0.0], [0, 1.0, 0.0], [0, 1.28, -0.012], [0, 1.5, -0.022], [0, 1.66, -0.01]];
  const tLens = pathLengths(torsoPath);
  const yToM = (y: number) => {
    for (let i = 1; i < torsoPath.length; i += 1) if (y <= torsoPath[i][1]) return tLens[i - 1] + (y - torsoPath[i - 1][1]) / (torsoPath[i][1] - torsoPath[i - 1][1]) * (tLens[i] - tLens[i - 1]);
    return tLens[tLens.length - 1];
  };
  const torsoKeys: Key[] = [
    { m: yToM(0.865), w: 0.07, d: 0.06, fz: -0.004 },
    { m: yToM(0.895), w: 0.15, d: 0.108, fz: -0.006 },
    { m: yToM(0.95), w: 0.176, d: 0.12, fz: -0.01 },           // hips / glutes
    { m: yToM(1.0), w: 0.168, d: 0.114, fz: -0.006, e: 2.2 },   // waistband
    { m: yToM(1.08), w: 0.15, d: 0.104, e: 2.2 },               // waist
    { m: yToM(1.2), w: 0.158, d: 0.112, fz: 0.004, e: 2.3 },
    { m: yToM(1.32), w: 0.176, d: 0.126, fz: 0.01, e: 2.5 },    // chest
    { m: yToM(1.41), w: 0.186, d: 0.118, fz: 0.004, e: 2.6 },   // armpit line
    { m: yToM(1.465), w: 0.158, d: 0.096, fz: -0.004, e: 2.4 }, // shoulder line (deltoids are on the arms)
    { m: yToM(1.5), w: 0.115, d: 0.08, fz: -0.006 },            // trapezius slope
    { m: yToM(1.53), w: 0.072, d: 0.068, fz: 0.0 },             // neck base (athletes: thick neck)
    { m: yToM(1.6), w: 0.064, d: 0.064, fz: 0.006 },
    { m: yToM(1.66), w: 0.055, d: 0.055, fz: 0.01 },
  ].map(W);
  const shirtUv = (p: THREE.Vector3): [number, number] => {
    const u = Math.atan2(p.x, -p.z) / (Math.PI * 2) + 0.5;   // back centre = 0.5, seam at the front
    const v = Math.max(0, Math.min(1, (p.y - 0.97) / 0.56)) * SHIRT_V;
    return [u, v];
  };
  parts.push(buildLoft({
    path: torsoPath, keys: torsoKeys, depthRef: [0, 0, 1], blend: 0.07, radial: rad(20), density: den(34),
    markers: [{ bone: "hips", m: 0 }, { bone: "spine", m: yToM(1.1) }, { bone: "chest", m: yToM(1.28) }, { bone: "neck", m: yToM(1.52) }, { bone: "head", m: yToM(1.62) }],
    region: (_m, p) => (p.y < 0.985 ? (p.y > 0.965 ? "shortsTrim" : "shorts") : p.y > 1.522 ? "skin" : p.y > 1.488 && Math.abs(p.x) < 0.1 ? "trim" : "shirt"),
    uv: (p) => shirtUv(p),
    extraWeight: (p, wt, idx) => {
      // upper torso sides follow the clavicles (shoulder shrug / arm raise)
      const ax = Math.abs(p.x);
      if (p.y > 1.36 && ax > 0.08) {
        const k = smooth01((ax - 0.08) / 0.1) * smooth01((p.y - 1.36) / 0.08) * 0.65;
        idx[2] = BONE_INDEX[p.x > 0 ? "clavicleL" : "clavicleR"]; wt[2] = k / (1 - k + 1e-6) * (wt[0] + wt[1]);
      }
      // the thigh tops of the shorts follow the legs a little
      if (p.y < 0.93 && ax > 0.05) {
        const k = smooth01((0.93 - p.y) / 0.09) * smooth01((ax - 0.05) / 0.08) * 0.6;
        idx[3] = BONE_INDEX[p.x > 0 ? "thighL" : "thighR"]; wt[3] = k / (1 - k + 1e-6) * (wt[0] + wt[1] + wt[2]);
      }
    },
  }));

  for (const side of [1, -1] as const) {
    const S = side > 0 ? "L" : "R";
    const j = (b: string) => JOINT[`${b}${S}` as BoneName];
    // Leg: from inside the pelvis down to the ankle (the boot covers the foot)
    const legPath: V3[] = [[side * 0.082, 1.0, 0.0], j("thigh"), j("shin"), j("foot")];
    const lLens = pathLengths(legPath);
    const kneeM = lLens[2], ankleM = lLens[3];
    const legKeys: Key[] = [
      { m: 0, w: 0.098, d: 0.1 },
      { m: 0.1, w: 0.096, d: 0.098, fz: 0.004 },
      { m: 0.2, w: 0.086, d: 0.09, fz: 0.01, fx: side * 0.004 },          // quads
      { m: 0.32, w: 0.073, d: 0.078, fz: 0.012 },
      { m: kneeM - 0.06, w: 0.06, d: 0.064, fz: 0.01, fx: -side * 0.006 }, // vastus medialis
      { m: kneeM, w: 0.05, d: 0.054, fz: 0.006 },                          // knee
      { m: kneeM + 0.07, w: 0.05, d: 0.056, fz: -0.008 },
      { m: kneeM + 0.15, w: 0.056, d: 0.062, fz: -0.02 },                  // calf
      { m: kneeM + 0.26, w: 0.043, d: 0.045, fz: -0.01 },
      { m: ankleM - 0.05, w: 0.035, d: 0.037, fz: -0.004 },
      { m: ankleM, w: 0.034, d: 0.036 },
    ].map(W);
    const sockTop = kneeM + 0.07;
    parts.push(buildLoft({
      path: legPath, keys: legKeys, depthRef: [0, 0, 1], blend: 0.06, radial: rad(16), density: den(30),
      markers: [{ bone: "hips", m: 0 }, { bone: `thigh${S}` as BoneName, m: 0.06 }, { bone: `shin${S}` as BoneName, m: kneeM }, { bone: `foot${S}` as BoneName, m: ankleM + 0.02 }],
      region: (m) => (m < 0.2 ? "shorts" : m < 0.215 ? "shortsTrim" : m < sockTop ? "skin" : m < sockTop + 0.035 ? "sockTrim" : "socks"),
    }));
    // Boot: heel -> toe along the foot (its depth axis is vertical)
    const fx = side * 0.1;
    const footPath: V3[] = [[fx, 0.05, -0.085], [fx, 0.062, -0.02], [side * 0.104, 0.036, 0.13], [side * 0.106, 0.034, 0.19]];
    const fLens = pathLengths(footPath);
    parts.push(buildLoft({
      path: footPath, depthRef: [0, 1, 0], blend: 0.025, radial: rad(14), density: den(48),
      keys: [
        { m: 0, w: 0.026, d: 0.03 }, { m: 0.03, w: 0.039, d: 0.05, fz: 0.004 }, { m: 0.075, w: 0.042, d: 0.058, fz: 0.0 },
        { m: 0.14, w: 0.047, d: 0.044, fz: -0.004, e: 2.4 }, { m: 0.2, w: 0.05, d: 0.034, fz: -0.002, e: 2.6 },
        { m: fLens[3] - 0.03, w: 0.042, d: 0.025, e: 2.4 }, { m: fLens[3], w: 0.018, d: 0.012 },
      ],
      markers: [{ bone: `foot${S}` as BoneName, m: 0 }, { bone: `toe${S}` as BoneName, m: fLens[2] - 0.01 }],
      region: (_m, p) => (p.y < 0.011 ? "sole" : "boots"),
    }));
    // boot collar around the ankle
    parts.push(buildLoft({
      path: [[fx, 0.15, -0.012], [fx, 0.06, -0.018]], depthRef: [0, 0, 1], blend: 0.02, radial: rad(12), density: den(40),
      keys: [{ m: 0, w: 0.04, d: 0.043 }, { m: 0.05, w: 0.043, d: 0.047 }, { m: 0.09, w: 0.045, d: 0.05 }],
      markers: [{ bone: `foot${S}` as BoneName, m: 0 }], region: () => "boots",
    }));
    // Arm: deltoid cap -> shoulder -> elbow -> wrist (one surface)
    const sh = j("upperArm"), el = j("foreArm"), wr = j("hand");
    const armPath: V3[] = [[sh[0] - side * 0.012, sh[1] + 0.03, sh[2]], sh, el, wr];
    const aLens = pathLengths(armPath);
    const elbowM = aLens[2], wristM = aLens[3];
    const sleeveEnd = variant.keeper ? wristM - 0.03 : 0.2;
    parts.push(buildLoft({
      path: armPath, depthRef: [0, 0, 1], blend: 0.05, radial: rad(14), density: den(34),
      keys: [
        { m: 0, w: 0.028, d: 0.032 }, { m: 0.022, w: 0.05, d: 0.054, fx: side * 0.004 },
        { m: 0.065, w: 0.056, d: 0.058, fx: side * 0.006 },                  // deltoid
        { m: 0.15, w: 0.049, d: 0.054, fx: side * 0.003, fz: 0.004 },
        { m: 0.24, w: 0.045, d: 0.054, fz: 0.008 },                          // biceps
        { m: elbowM - 0.02, w: 0.04, d: 0.042 },
        { m: elbowM + 0.05, w: 0.043, d: 0.042, fz: 0.002 },                 // forearm
        { m: elbowM + 0.15, w: 0.034, d: 0.03 },
        { m: wristM, w: 0.029, d: 0.021 },
      ].map((k) => ({ ...k, w: k.w * (variant.keeper && k.m < sleeveEnd ? 1.1 : 1), d: k.d * (variant.keeper && k.m < sleeveEnd ? 1.08 : 1) })).map(W),
      markers: [{ bone: `clavicle${S}` as BoneName, m: 0 }, { bone: `upperArm${S}` as BoneName, m: 0.05 }, { bone: `foreArm${S}` as BoneName, m: elbowM }, { bone: `hand${S}` as BoneName, m: wristM }],
      region: (m) => (m < sleeveEnd ? "shirt" : m < sleeveEnd + 0.018 ? "trim" : "skin"),
      uv: () => [0.5, 0.2],    // plain primary colour of the kit texture
    }));
    // Hand: palm faces the thigh (width along Z), fingers slightly curled forward
    const gl = variant.keeper ? 1.22 : 1;
    const handPath: V3[] = [wr, [wr[0] + side * 0.004, wr[1] - 0.085, wr[2] + 0.008], [wr[0] + side * 0.0, wr[1] - 0.16, wr[2] + 0.026]];
    parts.push(buildLoft({
      path: handPath, depthRef: [1, 0, 0], blend: 0.02, radial: rad(10), density: den(56),
      keys: [{ m: 0, w: 0.027 * gl, d: 0.02 * gl }, { m: 0.045, w: 0.042 * gl, d: 0.018 * gl }, { m: 0.1, w: 0.041 * gl, d: 0.016 * gl, e: 2.6 }, { m: 0.142, w: 0.034 * gl, d: 0.014 * gl, e: 2.4 }, { m: 0.162, w: 0.016 * gl, d: 0.009 * gl }],
      markers: [{ bone: `hand${S}` as BoneName, m: 0 }],
      region: () => (variant.keeper ? "gloves" : "skin"),
    }));
    // thumb
    parts.push(buildLoft({
      path: [[wr[0] - side * 0.005, wr[1] - 0.03, wr[2] + 0.028], [wr[0] - side * 0.012, wr[1] - 0.085, wr[2] + 0.05]], depthRef: [1, 0, 0], blend: 0.01, radial: rad(8), density: den(60),
      keys: [{ m: 0, w: 0.015 * gl, d: 0.013 * gl }, { m: 0.06, w: 0.009 * gl, d: 0.008 * gl }],
      markers: [{ bone: `hand${S}` as BoneName, m: 0 }], region: () => (variant.keeper ? "gloves" : "skin"),
    }));
    // ears, eyes, brows (small rigid pieces on the head)
    parts.push(ellipsoid([side * 0.077, 1.7, 0.0], [0.012, 0.027, 0.018], rad(10), "skin", "head"));
  }

  // Head and hair
  const seg = rad(34), rings = Math.max(10, Math.round(seg * 0.72));
  const headWeight = (p: THREE.Vector3): [number, number, number, number, number, number, number, number] => {
    const w = smooth01((p.y - 1.585) / 0.04);
    return [BONE_INDEX.head, BONE_INDEX.neck, 0, 0, w, 1 - w, 0, 0];
  };
  parts.push(sphereGeometry({ seg, rings, uv: faceUv }, headSurface, () => "skin", headWeight));
  if (variant.hair !== 4) {
    const s = new THREE.Vector3();
    parts.push(sphereGeometry({ seg, rings: Math.round(rings * 0.7), phiMax: 0.72 }, (d, out) => {
      headSurface(d, out);
      const m = hairMask(variant.hair, d);
      s.copy(out).sub(HEAD_C).normalize();
      return out.addScaledVector(s, hairThickness(variant.hair, d) * m + 0.0015 * m - 0.006 * (1 - m));
    }, () => "hair", headWeight));
  }

  const merged = mergeGeometries(parts, false)!;
  merged.computeBoundingSphere();
  cache.set(key, merged);
  return merged;
}

export function triangleCount(g: THREE.BufferGeometry): number {
  return g.index ? g.index.count / 3 : g.getAttribute("position").count / 3;
}
