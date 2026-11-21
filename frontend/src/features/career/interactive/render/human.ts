import * as THREE from "three";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";

/**
 * Semi-realistic athlete (original, generated in code — no third-party model or animation).
 *
 * One skinned mesh per player on a reusable humanoid skeleton:
 *   hips ─ spine ─ chest ─ neck ─ head
 *               └ chest ─ upperArm(L/R) ─ foreArm(L/R)
 *   hips ─ thigh(L/R) ─ shin(L/R)
 * Body parts are tapered capsules/ellipsoids weighted to their bone and blended with the
 * parent bone around each joint, so knees, elbows, hips and shoulders bend smoothly.
 *
 * Geometry, normals and skin data are built ONCE per (hair style, detail level) and shared
 * by every player; each player only owns its colour attribute (kit, skin, hair) and its own
 * skeleton, so all 22 animate independently.
 *
 * Units: metres, feet on y = 0, facing +Z, ~1.82 m tall (real scale, never physics).
 */
export type Detail = "low" | "medium" | "high";
export type Region = "skin" | "shirt" | "trim" | "shorts" | "socks" | "boots" | "hair" | "eye" | "lips" | "hands";
const REGIONS: Region[] = ["skin", "shirt", "trim", "shorts", "socks", "boots", "hair", "eye", "lips", "hands"];

export const BONES = ["hips", "spine", "chest", "neck", "head", "upperArmL", "foreArmL", "upperArmR", "foreArmR", "thighL", "shinL", "thighR", "shinR"] as const;
type BoneName = typeof BONES[number];
const B = Object.fromEntries(BONES.map((b, i) => [b, i])) as Record<BoneName, number>;

/** Bind pose joint positions (model space). Parents follow the hierarchy above. */
const JOINT: Record<BoneName, [number, number, number]> = {
  hips: [0, 0.95, 0], spine: [0, 1.08, 0], chest: [0, 1.28, 0], neck: [0, 1.5, 0], head: [0, 1.58, 0],
  upperArmL: [-0.2, 1.44, 0], foreArmL: [-0.225, 1.165, 0], upperArmR: [0.2, 1.44, 0], foreArmR: [0.225, 1.165, 0],
  thighL: [-0.095, 0.93, 0], shinL: [-0.1, 0.5, 0.005], thighR: [0.095, 0.93, 0], shinR: [0.1, 0.5, 0.005],
};
const PARENT: Record<BoneName, BoneName | null> = {
  hips: null, spine: "hips", chest: "spine", neck: "chest", head: "neck",
  upperArmL: "chest", foreArmL: "upperArmL", upperArmR: "chest", foreArmR: "upperArmR",
  thighL: "hips", shinL: "thighL", thighR: "hips", shinR: "thighR",
};

type Weight = (p: THREE.Vector3) => [number, number, number];  // [boneA, boneB, weight of A]

/** Weight a vertex to `bone`, blending into `parent` around the joint at height `jointY` (limbs hang down). */
function jointBlend(bone: number, parent: number, jointY: number, blend = 0.05): Weight {
  return (p) => {
    const below = jointY - p.y;
    const w = Math.max(0, Math.min(1, 0.5 + below / (2 * blend)));
    return [bone, parent, w];
  };
}
/** Torso pieces: blend upwards (the joint is at the bottom of the piece). */
function upBlend(bone: number, parent: number, jointY: number, blend = 0.05): Weight {
  return (p) => {
    const above = p.y - jointY;
    const w = Math.max(0, Math.min(1, 0.5 + above / (2 * blend)));
    return [bone, parent, w];
  };
}
const rigid = (bone: number): Weight => () => [bone, bone, 1];

type Piece = { geo: THREE.BufferGeometry; region: Region | ((p: THREE.Vector3) => Region); weight: Weight };

function tube(rTop: number, rBottom: number, top: [number, number, number], bottom: [number, number, number], radial: number, rings: number, depth = 1): THREE.BufferGeometry {
  const a = new THREE.Vector3(...top), b = new THREE.Vector3(...bottom);
  const len = a.distanceTo(b);
  const g = new THREE.CylinderGeometry(rTop, rBottom, len, radial, rings, false);
  g.scale(1, 1, depth);
  const dir = new THREE.Vector3().subVectors(a, b).normalize();
  const q = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir);
  g.applyQuaternion(q);
  const mid = a.clone().add(b).multiplyScalar(0.5);
  g.translate(mid.x, mid.y, mid.z);
  return g;
}
function blob(r: number, at: [number, number, number], scale: [number, number, number], ws: number, hs: number, thetaLen = Math.PI): THREE.BufferGeometry {
  const g = new THREE.SphereGeometry(r, ws, hs, 0, Math.PI * 2, 0, thetaLen);
  g.scale(...scale);
  g.translate(...at);
  return g;
}

const cache = new Map<string, THREE.BufferGeometry>();

/** Shared body geometry for a hair style and detail level (positions, normals, skin data, region ids). */
export function bodyGeometry(hairStyle: number, detail: Detail): THREE.BufferGeometry {
  const key = `${hairStyle}|${detail}`;
  const hit = cache.get(key);
  if (hit) return hit;
  const R = detail === "high" ? 16 : detail === "medium" ? 12 : 7;
  const H = detail === "low" ? 1 : 4;
  const S = detail === "high" ? 18 : detail === "medium" ? 14 : 9;
  const pieces: Piece[] = [];
  const add = (geo: THREE.BufferGeometry, region: Piece["region"], weight: Weight) => pieces.push({ geo, region, weight });
  // ---- torso (ellipse cross-sections: depth ~0.62 of width)
  add(tube(0.158, 0.172, [0, 1.08, 0], [0, 0.9, 0], R, H, 0.72), "shorts", upBlend(B.hips, B.hips, 0.9));
  add(tube(0.152, 0.17, [0, 1.27, 0.005], [0, 1.04, 0], R, H, 0.68), "shirt", upBlend(B.spine, B.hips, 1.1));
  add(tube(0.188, 0.152, [0, 1.47, 0.0], [0, 1.25, 0.005], R, H, 0.62), "shirt", upBlend(B.chest, B.spine, 1.29));
  add(blob(0.062, [-0.17, 1.43, 0], [1, 0.75, 0.9], R, 8), "shirt", rigid(B.chest));   // deltoids
  add(blob(0.062, [0.17, 1.43, 0], [1, 0.75, 0.9], R, 8), "shirt", rigid(B.chest));
  add(tube(0.082, 0.07, [0, 1.49, 0], [0, 1.465, 0], R, 1, 0.8), "trim", rigid(B.chest));  // collar
  // ---- neck and head
  add(tube(0.06, 0.07, [0, 1.585, 0.005], [0, 1.49, 0], R, 2), "skin", upBlend(B.neck, B.chest, 1.5, 0.03));
  add(blob(0.15, [0, 1.462, -0.01], [1.3, 0.42, 0.66], R, 8), "shirt", rigid(B.chest));          // trapezius: sloped shoulders
  add(blob(0.1, [0, 1.665, 0.012], [0.9, 1.12, 1.0], S, S), "skin", rigid(B.head));
  add(blob(0.018, [0, 1.655, 0.108], [0.9, 1.3, 1.1], 8, 6), "skin", rigid(B.head));           // nose
  for (const sx of [-1, 1]) {
    add(blob(0.013, [sx * 0.035, 1.682, 0.1], [1.2, 0.85, 0.6], 8, 6), "eye", rigid(B.head));
    add(blob(0.013, [sx * 0.092, 1.67, 0.0], [0.6, 1.4, 1.0], 6, 6), "skin", rigid(B.head));  // ears
    add(tube(0.006, 0.006, [sx * 0.052, 1.704, 0.099], [sx * 0.018, 1.701, 0.106], 4, 1), "hair", rigid(B.head));  // brows
  }
  add(tube(0.0055, 0.0055, [-0.022, 1.618, 0.101], [0.022, 1.618, 0.101], 4, 1), "lips", rigid(B.head));
  // hair styles
  const hairTheta = [1.25, 1.55, 0.9, 1.4][hairStyle % 4];
  const hairScale: [number, number, number] = [[0.98, 1.16, 1.06], [1.0, 1.24, 1.08], [0.95, 1.12, 1.03], [1.02, 1.3, 1.1]][hairStyle % 4] as [number, number, number];
  add(blob(0.108, [0, 1.672, -0.008], hairScale, S, Math.max(6, S - 4), hairTheta), "hair", rigid(B.head));
  if (hairStyle % 4 === 3) add(blob(0.05, [0, 1.775, -0.02], [1, 1.2, 1.4], 10, 8), "hair", rigid(B.head));   // top volume
  // ---- arms (hanging, slight abduction)
  for (const side of [-1, 1]) {
    const up = side < 0 ? B.upperArmL : B.upperArmR, fo = side < 0 ? B.foreArmL : B.foreArmR;
    const sh: [number, number, number] = [side * 0.2, 1.46, 0];
    const el: [number, number, number] = [side * 0.225, 1.165, 0];
    const wr: [number, number, number] = [side * 0.24, 0.92, 0.02];
    add(tube(0.06, 0.052, sh, [side * 0.21, 1.31, 0], R, 2), "shirt", jointBlend(up, B.chest, 1.43, 0.06));            // sleeve
    add(tube(0.061, 0.056, [side * 0.21, 1.315, 0], [side * 0.212, 1.3, 0], R, 1), "trim", rigid(up));                 // cuff
    add(tube(0.046, 0.04, [side * 0.21, 1.31, 0], el, R, 2), "skin", jointBlend(up, B.chest, 1.43));
    add(blob(0.043, el, [1, 1, 1], R, 8), "skin", jointBlend(fo, up, 1.165, 0.04));                                   // elbow
    add(tube(0.041, 0.031, el, wr, R, 3), "skin", jointBlend(fo, up, 1.165, 0.05));
    add(blob(0.034, [wr[0], wr[1] - 0.045, wr[2]], [0.8, 1.15, 0.65], 10, 8), "hands", rigid(fo));
  }
  // ---- legs
  for (const side of [-1, 1]) {
    const th = side < 0 ? B.thighL : B.thighR, sh = side < 0 ? B.shinL : B.shinR;
    const hip: [number, number, number] = [side * 0.095, 0.93, 0];
    const knee: [number, number, number] = [side * 0.1, 0.5, 0.005];
    const ankle: [number, number, number] = [side * 0.102, 0.085, -0.01];
    add(tube(0.1, 0.092, [side * 0.095, 0.95, 0], [side * 0.097, 0.76, 0], R, 2), "shorts", jointBlend(th, B.hips, 0.9, 0.08));
    add(tube(0.088, 0.062, [side * 0.097, 0.77, 0], knee, R, 3), "skin", jointBlend(th, B.hips, 0.9, 0.08));
    add(blob(0.062, knee, [1, 1.05, 1], R, 8), "skin", jointBlend(sh, th, 0.5, 0.04));                                  // knee
    add(tube(0.06, 0.058, knee, [side * 0.101, 0.44, 0.0], R, 1), "skin", jointBlend(sh, th, 0.5, 0.05));
    add(tube(0.062, 0.04, [side * 0.101, 0.44, 0.0], ankle, R, 4), "socks", jointBlend(sh, th, 0.5, 0.05));
    add(blob(0.05, [side * 0.101, 0.33, -0.02], [1, 1.9, 1.05], R, 8), "socks", rigid(sh));                                // calf
    add(blob(0.055, [side * 0.104, 0.045, 0.05], [0.85, 0.75, 2.0], 10, 8), "boots", rigid(sh));
    void hip;
  }
  // ---- merge with region + skin attributes
  const parts: THREE.BufferGeometry[] = [];
  const p = new THREE.Vector3();
  for (const piece of pieces) {
    const g = piece.geo;          // indexed: smooth shading inside every piece
    g.deleteAttribute("uv");
    g.computeVertexNormals();
    const pos = g.getAttribute("position") as THREE.BufferAttribute;
    const n = pos.count;
    const region = new Float32Array(n), skinIndex = new Uint16Array(n * 4), skinWeight = new Float32Array(n * 4);
    for (let i = 0; i < n; i += 1) {
      p.fromBufferAttribute(pos, i);
      const r = typeof piece.region === "function" ? piece.region(p) : piece.region;
      region[i] = REGIONS.indexOf(r);
      const [a, b, w] = piece.weight(p);
      skinIndex.set([a, b, 0, 0], i * 4);
      skinWeight.set([w, 1 - w, 0, 0], i * 4);
    }
    g.setAttribute("region", new THREE.BufferAttribute(region, 1));
    g.setAttribute("skinIndex", new THREE.Uint16BufferAttribute(skinIndex, 4));
    g.setAttribute("skinWeight", new THREE.BufferAttribute(skinWeight, 4));
    parts.push(g);
  }
  const merged = mergeGeometries(parts, false);
  merged.computeBoundingSphere();
  cache.set(key, merged);
  return merged;
}

export type Look = { skin: string; hair: string; shirt: string; trim: string; shorts: string; socks: string; boots: string; hands: string; pattern?: string };

/** Per-player colours over the shared geometry (the only per-player buffer). */
export function colouredGeometry(shared: THREE.BufferGeometry, look: Look): THREE.BufferGeometry {
  const g = new THREE.BufferGeometry();
  for (const name of ["position", "normal", "skinIndex", "skinWeight"]) g.setAttribute(name, shared.getAttribute(name));
  g.setIndex(shared.index);
  g.boundingSphere = shared.boundingSphere;
  const region = shared.getAttribute("region") as THREE.BufferAttribute;
  const pos = shared.getAttribute("position") as THREE.BufferAttribute;
  const colours: Record<Region, THREE.Color> = {
    skin: new THREE.Color(look.skin), shirt: new THREE.Color(look.shirt), trim: new THREE.Color(look.trim), shorts: new THREE.Color(look.shorts),
    socks: new THREE.Color(look.socks), boots: new THREE.Color(look.boots), hair: new THREE.Color(look.hair), eye: new THREE.Color("#1a1412"),
    lips: new THREE.Color(look.skin).multiplyScalar(0.72), hands: new THREE.Color(look.hands),
  };
  const out = new Float32Array(region.count * 3);
  for (let i = 0; i < region.count; i += 1) {
    const r = REGIONS[Math.round(region.getX(i))];
    let c = colours[r];
    if (r === "shirt" && look.pattern && look.pattern !== "plain") {
      const x = pos.getX(i), y = pos.getY(i);
      const band = look.pattern === "hoops" ? Math.floor((y - 1.06) / 0.07) % 2 === 1
        : look.pattern === "stripes" ? Math.floor((x + 0.3) / 0.075) % 2 === 1
          : Math.abs(y - 1.1 - (x + 0.2) * 0.9) < 0.05;   // sash
      if (band) c = colours.trim;
    }
    out.set([c.r, c.g, c.b], i * 3);
  }
  g.setAttribute("color", new THREE.BufferAttribute(out, 3));
  return g;
}

export type HumanParts = { mesh: THREE.SkinnedMesh; bones: Record<BoneName, THREE.Bone> };

/** A skinned athlete with its own skeleton (bones keep identity rotations in the bind pose). */
export function createHuman(look: Look, hairStyle: number, detail: Detail, shadows: boolean): HumanParts {
  const shared = bodyGeometry(hairStyle, detail);
  const geo = colouredGeometry(shared, look);
  const bones = {} as Record<BoneName, THREE.Bone>;
  for (const name of BONES) {
    const bone = new THREE.Bone(); bone.name = name;
    const parent = PARENT[name];
    const [x, y, z] = JOINT[name];
    if (parent) { const [px, py, pz] = JOINT[parent]; bone.position.set(x - px, y - py, z - pz); }
    else bone.position.set(x, y, z);
    bones[name] = bone;
  }
  for (const name of BONES) { const parent = PARENT[name]; if (parent) bones[parent].add(bones[name]); }
  const material = humanMaterial();
  const mesh = new THREE.SkinnedMesh(geo, material);
  mesh.add(bones.hips);
  mesh.updateMatrixWorld(true);
  const skeleton = new THREE.Skeleton(BONES.map((n) => bones[n]));
  mesh.bind(skeleton);
  mesh.castShadow = shadows;
  mesh.frustumCulled = false;
  return { mesh, bones };
}

let material: THREE.MeshStandardMaterial | null = null;
function humanMaterial(): THREE.MeshStandardMaterial {
  if (!material) material = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.72, metalness: 0.0 });
  return material;
}
