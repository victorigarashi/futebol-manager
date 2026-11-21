import * as THREE from "three";
import { Avatar3D } from "./avatar3d";

import type { InteractiveView } from "../../../../lib/api";
import { predictTarget, type Aim } from "../gesture";
import { VISUAL, hashOf } from "./config";
import type { Scene, ScenePlayer } from "./presentation";
import type { Kit, Overlay } from "./renderer2d";
import { createHuman, type Detail } from "./human";

/**
 * 3D Imersivo renderer (Three.js, loaded on demand). Original low-poly "blocky" art:
 * procedural characters with jointed limbs, a stylised stadium, contextual cameras.
 * It only DRAWS the shared Scene built from the official frames; gestures are turned
 * into pitch coordinates by raycasting onto the grass plane and then follow exactly the
 * same intent maths as the 2D view (direction and power in pitch metres).
 *
 * World axes: X = along the pitch (x·L − L/2), Z = across (y·W − W/2), Y = up.
 */
export type Quality = "low" | "medium" | "high";
export type CameraMode = "auto" | "wide";

const CROWD = { low: 500, medium: 1800, high: 3600 } as const;
const SHADOW = { low: 0, medium: 1024, high: 2048 } as const;
const TEXTURE = { low: 1024, medium: 2048, high: 4096 } as const;
const PLAYER_HEIGHT = 1.85;       // metres (the model is built at real scale)
const BALL_RADIUS = 0.15;         // visual: 1.35x the physics ball (0.11 m) for legibility
const CROSSBAR = 2.44;            // same height the physics uses for lofted balls

type Limb = { upper: THREE.Object3D; lower: THREE.Object3D };
type Joint = THREE.Object3D;
type Rig = {
  root: THREE.Group; body: THREE.Group; chest: Joint; head: Joint; torso: THREE.Mesh;
  armL: Limb; armR: Limb; legL: Limb; legR: Limb; ring: THREE.Mesh; key: string;
};

const geo = {
  box: new THREE.BoxGeometry(1, 1, 1),
  ring: new THREE.RingGeometry(0.55, 0.75, 40),
  disc: new THREE.CircleGeometry(1, 24),
};
geo.ring.rotateX(-Math.PI / 2);
geo.disc.rotateX(-Math.PI / 2);

const materials = new Map<string, THREE.MeshLambertMaterial>();
function mat(color: string): THREE.MeshLambertMaterial {
  let m = materials.get(color);
  if (!m) { m = new THREE.MeshLambertMaterial({ color: new THREE.Color(color) }); materials.set(color, m); }
  return m;
}

function canvasTexture(width: number, height: number, paint: (ctx: CanvasRenderingContext2D) => void): THREE.CanvasTexture {
  const canvas = document.createElement("canvas");
  canvas.width = width; canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (ctx) paint(ctx);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 4;
  return texture;
}

const jerseyTextures = new Map<string, THREE.MeshLambertMaterial>();
function paintPattern(ctx: CanvasRenderingContext2D, trim: string, pattern: string | undefined) {
  ctx.fillStyle = trim;
  if (pattern === "hoops") for (let i = 0; i < 3; i += 1) ctx.fillRect(0, 20 + i * 38, 128, 16);
  else if (pattern === "stripes") for (let i = 0; i < 4; i += 1) ctx.fillRect(10 + i * 32, 0, 14, 128);
  else if (pattern === "sash") { ctx.beginPath(); ctx.moveTo(0, 10); ctx.lineTo(28, 0); ctx.lineTo(128, 100); ctx.lineTo(128, 128); ctx.lineTo(100, 128); ctx.closePath(); ctx.fill(); }
  else ctx.fillRect(0, 0, 128, 12);
}
/** Shirt faces: the back carries the number; both carry the kit pattern. */
function jerseyBack(shirt: string, number: number, trim: string, ink?: string, pattern?: string): THREE.MeshLambertMaterial {
  const key = `B|${shirt}|${number}|${trim}|${ink}|${pattern}`;
  let m = jerseyTextures.get(key);
  if (!m) {
    const tex = canvasTexture(128, 128, (ctx) => {
      ctx.fillStyle = shirt; ctx.fillRect(0, 0, 128, 128);
      paintPattern(ctx, trim, pattern);
      ctx.font = "900 76px 'Barlow Condensed', 'Arial Narrow', sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      const color = ink ?? (new THREE.Color(shirt).getHSL({ h: 0, s: 0, l: 0 }).l > 0.6 ? "#141414" : "#ffffff");
      ctx.lineWidth = 7; ctx.strokeStyle = color === "#FFFFFF" || color === "#ffffff" ? "rgba(0,0,0,0.55)" : "rgba(255,255,255,0.7)";
      ctx.strokeText(String(number || ""), 64, 72); ctx.fillStyle = color; ctx.fillText(String(number || ""), 64, 72);
    });
    m = new THREE.MeshLambertMaterial({ map: tex });
    jerseyTextures.set(key, m);
  }
  return m;
}
function jerseyFront(shirt: string, trim: string, pattern?: string): THREE.MeshLambertMaterial {
  const key = `F|${shirt}|${trim}|${pattern}`;
  let m = jerseyTextures.get(key);
  if (!m) {
    const tex = canvasTexture(128, 128, (ctx) => { ctx.fillStyle = shirt; ctx.fillRect(0, 0, 128, 128); paintPattern(ctx, trim, pattern); });
    m = new THREE.MeshLambertMaterial({ map: tex });
    jerseyTextures.set(key, m);
  }
  return m;
}

function part(parent: THREE.Object3D, color: string | THREE.Material, sx: number, sy: number, sz: number, x: number, y: number, z: number, shadows: boolean): THREE.Mesh {
  const mesh = new THREE.Mesh(geo.box, typeof color === "string" ? mat(color) : color);
  mesh.scale.set(sx, sy, sz); mesh.position.set(x, y, z);
  mesh.castShadow = shadows;
  parent.add(mesh);
  return mesh;
}

function limb(parent: THREE.Object3D, x: number, y: number, upperColor: string, lowerColor: string, endColor: string, upperLen: number, lowerLen: number, w: number, foot: boolean, shadows: boolean): Limb {
  const upper = new THREE.Group(); upper.position.set(x, y, 0); parent.add(upper);
  part(upper, upperColor, w, upperLen, w, 0, -upperLen / 2, 0, shadows);
  const lower = new THREE.Group(); lower.position.set(0, -upperLen, 0); upper.add(lower);
  part(lower, lowerColor, w * 0.92, lowerLen, w * 0.92, 0, -lowerLen / 2, 0, shadows);
  if (foot) part(lower, endColor, w * 1.05, 0.13, w * 1.75, 0, -lowerLen - 0.03, w * 0.35, shadows);
  else part(lower, endColor, w * 0.9, w * 0.9, w * 0.9, 0, -lowerLen - w * 0.35, 0, shadows);
  return { upper, lower };
}

/**
 * Character (metres, ~1.85 m tall): stylised low-poly — slightly big head, athletic body,
 * jointed hips/knees/shoulders/elbows. The upper body is its own group so it can
 * counter-rotate against the hips while running.
 */
function buildRig(p: ScenePlayer, kit: Kit, shadows: boolean): Rig {
  const look = hashOf(p.id);
  const skin = VISUAL.skin[look % VISUAL.skin.length];
  const hair = VISUAL.hair[(look >>> 4) % VISUAL.hair.length];
  const boots = VISUAL.boots[(look >>> 8) % VISUAL.boots.length];
  const style = (look >>> 12) % 5;
  const build = 0.94 + ((look >>> 16) % 13) / 100;     // cosmetic body variation (never physics)
  const wear = p.keeper ? (kit.gk ?? { shirt: VISUAL.keeperKits[p.team], shorts: "#2a2a33", socks: VISUAL.keeperKits[p.team], trim: "#ffffff" }) : kit;
  const shirt = wear.shirt, shorts = wear.shorts, socks = wear.socks;
  const gloves = p.keeper ? "#f2f2f2" : skin;
  const root = new THREE.Group();
  const body = new THREE.Group(); root.add(body);
  body.scale.set(build, 1, build);
  const legL = limb(body, -0.11, 0.9, skin, socks, boots, 0.44, 0.44, 0.15, true, shadows);
  const legR = limb(body, 0.11, 0.9, skin, socks, boots, 0.44, 0.44, 0.15, true, shadows);
  part(body, shorts, 0.42, 0.24, 0.27, 0, 0.94, 0, shadows);
  const chest = new THREE.Group(); chest.position.set(0, 1.04, 0); body.add(chest);
  const front = jerseyFront(shirt, wear.trim, wear.pattern);
  const back = jerseyBack(shirt, p.number, wear.trim, wear.number, wear.pattern);
  // Box faces: +X, -X, +Y, -Y, +Z (front), -Z (back: the number).
  const torso = part(chest, [front, front, front, front, front, back] as unknown as THREE.Material, 0.46, 0.5, 0.26, 0, 0.26, 0, shadows);
  part(chest, wear.trim, 0.47, 0.05, 0.27, 0, 0.5, 0, shadows);           // collar band
  const armL = limb(chest, -0.3, 0.47, shirt, skin, gloves, 0.28, 0.27, 0.11, false, shadows);
  const armR = limb(chest, 0.3, 0.47, shirt, skin, gloves, 0.28, 0.27, 0.11, false, shadows);
  const head = new THREE.Group(); head.position.set(0, 0.52, 0); chest.add(head);
  part(head, skin, 0.11, 0.08, 0.11, 0, 0.03, 0, shadows);                 // neck
  part(head, skin, 0.33, 0.33, 0.31, 0, 0.23, 0, shadows);
  for (const sx of [-1, 1]) {
    part(head, "#1b1b1b", 0.05, 0.06, 0.015, sx * 0.075, 0.24, 0.158, false);   // eyes
    part(head, hair, 0.08, 0.02, 0.015, sx * 0.075, 0.29, 0.158, false);        // brows
    part(head, skin, 0.03, 0.06, 0.04, sx * 0.17, 0.22, 0, false);              // ears
  }
  part(head, "#7a3b2e", 0.08, 0.02, 0.015, 0, 0.14, 0.158, false);
  part(head, skin, 0.05, 0.07, 0.04, 0, 0.2, 0.17, false);                      // nose
  if (style === 0) { part(head, hair, 0.35, 0.07, 0.33, 0, 0.42, 0, shadows); part(head, hair, 0.35, 0.18, 0.04, 0, 0.32, -0.16, shadows); }
  else if (style === 1) { part(head, hair, 0.36, 0.12, 0.34, 0, 0.43, -0.01, shadows); part(head, hair, 0.37, 0.3, 0.05, 0, 0.26, -0.16, shadows); for (const sx of [-1, 1]) part(head, hair, 0.04, 0.2, 0.26, sx * 0.18, 0.32, -0.03, shadows); }
  else if (style === 2) { part(head, hair, 0.09, 0.14, 0.32, 0, 0.45, 0, shadows); part(head, hair, 0.35, 0.03, 0.33, 0, 0.4, 0, shadows); }
  else if (style === 3) { for (let i = 0; i < 5; i += 1) part(head, hair, 0.08, 0.12, 0.08, -0.13 + i * 0.065, 0.44, ((i % 2) - 0.5) * 0.08, shadows); part(head, hair, 0.35, 0.05, 0.33, 0, 0.4, 0, shadows); }
  else { part(head, hair, 0.36, 0.035, 0.34, 0, 0.4, 0, shadows); }
  const ring = new THREE.Mesh(geo.ring, new THREE.MeshBasicMaterial({ color: 0xc6f24e, transparent: true, opacity: 0.9, depthWrite: false }));
  ring.position.y = 0.03; ring.scale.setScalar(0.85); ring.visible = false; root.add(ring);
  return { root, body, chest, head, torso, armL, armR, legL, legR, ring, key: `${p.id}|${shirt}|${kit.shorts}|${kit.pattern ?? ""}` };
}

/** Number on the back of the semi-realistic shirt (transparent decal on the chest bone). */
const numberDecals = new Map<string, THREE.MeshBasicMaterial>();
function numberDecal(number: number, ink: string): THREE.Mesh {
  const key = `${number}|${ink}`;
  let m = numberDecals.get(key);
  if (!m) {
    const tex = canvasTexture(128, 128, (ctx) => {
      ctx.clearRect(0, 0, 128, 128);
      ctx.font = "900 92px 'Barlow Condensed', 'Arial Narrow', sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.lineWidth = 6; ctx.strokeStyle = ink.toLowerCase() === "#ffffff" ? "rgba(0,0,0,0.45)" : "rgba(255,255,255,0.6)";
      ctx.strokeText(String(number || ""), 64, 70); ctx.fillStyle = ink; ctx.fillText(String(number || ""), 64, 70);
    });
    m = new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -2 });
    numberDecals.set(key, m);
  }
  const plane = new THREE.Mesh(new THREE.PlaneGeometry(0.17, 0.17), m);
  return plane;
}

/** Semi-realistic athlete (skinned mesh + humanoid skeleton, see human.ts) wired to the same pose system. */
function buildHumanRig(p: ScenePlayer, kit: Kit, shadows: boolean, detail: Detail): Rig {
  const look = hashOf(p.id);
  const wear = p.keeper ? (kit.gk ?? { shirt: VISUAL.keeperKits[p.team], shorts: "#2a2a33", socks: VISUAL.keeperKits[p.team], trim: "#ffffff" }) : kit;
  const skin = VISUAL.skin[look % VISUAL.skin.length];
  const human = createHuman({
    skin, hair: VISUAL.hair[(look >>> 4) % VISUAL.hair.length], shirt: wear.shirt, trim: wear.trim, shorts: wear.shorts, socks: wear.socks,
    boots: VISUAL.boots[(look >>> 8) % VISUAL.boots.length], hands: p.keeper ? "#f1f1f1" : skin, pattern: wear.pattern,
  }, (look >>> 12) % 4, detail, shadows);
  const root = new THREE.Group();
  const body = new THREE.Group(); root.add(body);
  const build = 0.95 + ((look >>> 16) % 11) / 100;      // cosmetic only
  body.scale.set(build, 1, build);
  body.add(human.mesh);
  const decal = numberDecal(p.number, wear.number ?? "#ffffff");
  decal.position.set(0, 0.075, -0.118); decal.rotation.y = Math.PI;
  human.bones.chest.add(decal);
  const b = human.bones;
  const ring = new THREE.Mesh(geo.ring, new THREE.MeshBasicMaterial({ color: 0xc6f24e, transparent: true, opacity: 0.9, depthWrite: false }));
  ring.position.y = 0.03; ring.scale.setScalar(0.8); ring.visible = false; root.add(ring);
  return { root, body, chest: b.chest, head: b.head, torso: decal, armL: { upper: b.upperArmL, lower: b.foreArmL }, armR: { upper: b.upperArmR, lower: b.foreArmR },
    legL: { upper: b.thighL, lower: b.shinL }, legR: { upper: b.thighR, lower: b.shinR }, ring, key: `H|${p.id}|${wear.shirt}|${kit.shorts}|${kit.pattern ?? ""}` };
}

/**
 * Animation blending: the pose system gives the TARGET pose of this frame; joints move
 * towards it with an exponential crossfade (no snapping between run, kick, save…).
 */
const blendState = new WeakMap<Rig, number[]>();
function blendPose(rig: Rig, p: ScenePlayer, now: number, dt: number) {
  const joints: THREE.Object3D[] = [rig.body, rig.chest, rig.head, rig.armL.upper, rig.armL.lower, rig.armR.upper, rig.armR.lower, rig.legL.upper, rig.legL.lower, rig.legR.upper, rig.legR.lower];
  const prev = blendState.get(rig);
  poseRig(rig, p, now);
  const next: number[] = [];
  for (const j of joints) next.push(j.rotation.x, j.rotation.y, j.rotation.z);
  next.push(rig.body.position.x, rig.body.position.y, rig.body.position.z);
  if (prev) {
    const k = 1 - Math.exp(-dt * (p.pose === "run" || p.pose === "idle" ? 26 : 18));
    for (let i = 0; i < next.length; i += 1) next[i] = prev[i] + (next[i] - prev[i]) * k;
    joints.forEach((j, i) => j.rotation.set(next[i * 3], next[i * 3 + 1], next[i * 3 + 2]));
    const o = joints.length * 3;
    rig.body.position.set(next[o], next[o + 1], next[o + 2]);
  }
  blendState.set(rig, next);
}

function poseRig(rig: Rig, p: ScenePlayer, now: number) {
  const look = hashOf(p.id);
  const run = Math.min(1, p.speed / 7.5);
  const phase = p.stride * Math.PI * 2;
  const moving = p.pose === "run";
  const swing = moving ? Math.sin(phase) * (0.25 + run * 0.5) : 0;
  const b = rig.body, c = rig.chest;
  b.position.set(0, 0, 0); b.rotation.set(0, 0, 0); c.rotation.set(0, 0, 0);
  rig.head.rotation.set(0, 0, 0);
  const set = (l: Limb, ux: number, lx: number, uz = 0) => { l.upper.rotation.set(ux, 0, uz); l.lower.rotation.set(lx, 0, 0); };
  // Legs: thigh swing; the knee folds when the leg recovers behind the body.
  const knee = (thigh: number) => Math.max(0, thigh) * 1.5 + (moving ? 0.2 + run * 0.35 : 0.05);
  set(rig.legL, -swing, knee(swing));
  set(rig.legR, swing, knee(-swing));
  // Arms opposite to the legs, elbows bent more at speed.
  set(rig.armL, swing * 0.85, -0.35 - run * 0.9, 0.1);
  set(rig.armR, -swing * 0.85, -0.35 - run * 0.9, -0.1);
  // Lean into the run, hips sway, shoulders counter-rotate, a bob per stride; idle breathing.
  // Lean comes from the torso (legs stay under the hips), hips sway, shoulders counter-rotate.
  b.rotation.x = run * 0.04;
  c.rotation.x = run * 0.28;
  b.rotation.y = swing * 0.12;
  c.rotation.y = -swing * 0.22;
  b.position.y = moving ? Math.abs(Math.sin(phase)) * 0.07 * run - 0.03 * run : Math.sin(now * 2 + look) * 0.008;
  if (!moving && p.pose === "idle") { set(rig.legL, -0.05, 0.12, 0.04); set(rig.legR, 0.05, 0.12, -0.04); set(rig.armL, 0.05, -0.25, 0.12); set(rig.armR, -0.05, -0.25, -0.12); }
  const k = p.poseK;
  switch (p.pose) {
    case "kick": {
      const back = k < 0.35 ? k / 0.35 : 1 - Math.min(1, (k - 0.35) / 0.25);
      const fwd = k < 0.35 ? 0 : Math.min(1, (k - 0.35) / 0.3);
      set(rig.legR, 0.9 * back - 1.3 * fwd, 1.2 * back + 0.1);
      set(rig.legL, 0.15, 0.3);
      set(rig.armL, -0.3, -0.4, 1.0); set(rig.armR, 0.5, -0.4, -0.8);
      b.rotation.x = -0.12 + 0.3 * fwd; c.rotation.y = 0.35 * (back - fwd);
      break;
    }
    case "tackle": {
      const s2 = Math.min(1, k * 2.5);
      b.rotation.x = -1.1 * s2; b.position.y = 0.22 * s2; b.position.z = 0.6 * k;
      set(rig.legR, -1.35 * s2, 0.1); set(rig.legL, -0.4 * s2, 1.3 * s2);
      set(rig.armL, -0.9, -0.3, 0.9); set(rig.armR, -0.9, -0.3, -0.9);
      break;
    }
    case "header": {
      const j = Math.sin(Math.min(1, k) * Math.PI);
      b.position.y = 0.5 * j; c.rotation.x = 0.4 * j; rig.head.rotation.x = 0.5 * j;
      set(rig.legL, 0.3, 1.1); set(rig.legR, -0.2, 0.8);
      set(rig.armL, -0.4, -0.5, 1.2); set(rig.armR, -0.4, -0.5, -1.2);
      break;
    }
    case "dive": case "save": {
      // poseDir: +1/-1 along the pitch width; converted to the keeper's own side.
      const s2 = Math.min(1, k * 1.6);
      const ry = rig.root.rotation.y;
      const side = Math.sign(-Math.sin(ry) * p.poseDir) || 1;   // local +X in world is (cos ry, 0, -sin ry)
      b.rotation.z = -side * 1.35 * s2; b.position.x = side * 0.9 * s2; b.position.y = 0.55 * Math.sin(Math.min(1, k) * Math.PI) + 0.2 * s2;
      set(rig.armL, 0, 0, side < 0 ? 2.9 : 2.6); set(rig.armR, 0, 0, side < 0 ? -2.6 : -2.9);
      set(rig.legL, 0.2, 0.5, 0.2 * side); set(rig.legR, -0.2, 0.4, 0.2 * side);
      break;
    }
    case "hold": set(rig.armL, -1.4, -0.7, 0.2); set(rig.armR, -1.4, -0.7, -0.2); c.rotation.x = 0.15; break;
    case "ready": set(rig.legL, -0.4, 0.8, 0.15); set(rig.legR, -0.4, 0.8, -0.15); b.position.y = -0.1; c.rotation.x = 0.25; set(rig.armL, -0.6, -0.5, 0.7); set(rig.armR, -0.6, -0.5, -0.7); break;
    case "celebrate": {
      const j = Math.abs(Math.sin(now * 8 + look));
      b.position.y = 0.3 * j;
      set(rig.armL, 0, -0.2, 2.7); set(rig.armR, 0, -0.2, -2.7);
      set(rig.legL, -0.3 * j, 0.7 * j); set(rig.legR, 0.2 * j, 0.5 * j);
      break;
    }
    default: break;
  }
}

export type PickResult = [number, number] | null;

export class Renderer3D {
  readonly canvas: HTMLCanvasElement;
  readonly overlay: HTMLCanvasElement;
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera = new THREE.PerspectiveCamera(42, 1, 0.5, 900);
  private sun: THREE.DirectionalLight;
  private rigs = new Map<string, Rig>();
  private ball: THREE.Mesh;
  private ballShadow: THREE.Mesh;
  private pitchKey = "";
  private pitchGroup = new THREE.Group();
  private nets: { lines: THREE.LineSegments; base: Float32Array; end: 0 | 1 }[] = [];
  private crowd: THREE.Group | null = null;
  private aimGroup = new THREE.Group();
  private trajectory: THREE.Line;
  private target: THREE.Mesh;
  private camPos = new THREE.Vector3(0, 60, 60);
  private camLook = new THREE.Vector3();
  private lastTime = 0;
  private frozen = false;
  private ray = new THREE.Raycaster();
  private ground = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
  private L = 105; private W = 68;
  private cinematic: { until: number; kind: "intro" | "goal"; from: THREE.Vector3 } | null = null;
  private lastOpp = "";
  private framedOpp = "";
  private lastGoal = "";
  quality: Quality;
  cameraMode: CameraMode = "auto";
  /** "human" (semi-realistic, default) or "voxel" (previous blocky style, kept as a fallback/comparison). */
  /** "athlete" (V8 default): skinned human + clip library + matched locomotion. "human"/"voxel": V6 styles, kept for comparison. */
  characterStyle: "athlete" | "human" | "voxel" = (() => { try { const v = localStorage.getItem("bm_3d_style"); return v === "voxel" ? "voxel" : v === "human" ? "human" : "athlete"; } catch { return "athlete"; } })();
  private avatars = new Map<string, Avatar3D>();
  /** Mean planted-foot sliding of the visible athletes (cm/s), for the Lab diagnostics. */
  footSlide = 0;
  lost = false;
  fps = 60;
  private frameTimes: number[] = [];

  constructor(quality: Quality) {
    this.quality = quality;
    this.canvas = document.createElement("canvas");
    this.overlay = document.createElement("canvas");
    this.renderer = new THREE.WebGLRenderer({ canvas: this.canvas, antialias: quality !== "low", powerPreference: "high-performance", preserveDrawingBuffer: false });
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.NoToneMapping;   // saturated, toy-like colours
    this.canvas.addEventListener("webglcontextlost", (event) => { event.preventDefault(); this.lost = true; });
    this.scene.background = new THREE.Color(0x9fd3ff);
    this.scene.fog = new THREE.Fog(0x9fd3ff, 160, 420);
    this.scene.add(new THREE.HemisphereLight(0xeef6ff, 0x46703a, 1.25));
    this.sun = new THREE.DirectionalLight(0xffefd2, 1.9);
    this.sun.position.set(-40, 80, 30);
    this.scene.add(this.sun, this.sun.target);
    this.applyQuality();
    this.scene.add(this.pitchGroup, this.aimGroup);
    // Ball (classic panels) and its blob shadow (always, also without shadow maps).
    const ballTex = canvasTexture(256, 128, (ctx) => {
      ctx.fillStyle = "#ffffff"; ctx.fillRect(0, 0, 256, 128); ctx.fillStyle = "#151515";
      for (let i = 0; i < 6; i += 1) for (let j = 0; j < 3; j += 1) {
        const cx = i * 44 + (j % 2) * 22 + 10, cy = 20 + j * 44; ctx.beginPath();
        for (let k = 0; k < 5; k += 1) { const a = (k * Math.PI * 2) / 5 - Math.PI / 2; ctx.lineTo(cx + Math.cos(a) * 12, cy + Math.sin(a) * 12); }
        ctx.fill();
      }
    });
    this.ball = new THREE.Mesh(new THREE.IcosahedronGeometry(BALL_RADIUS, 2), new THREE.MeshLambertMaterial({ map: ballTex }));
    this.ball.castShadow = true;
    this.ballShadow = new THREE.Mesh(geo.disc, new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.3, depthWrite: false }));
    this.ballShadow.scale.setScalar(BALL_RADIUS);
    this.scene.add(this.ball, this.ballShadow);
    // Aim: one dashed line and a small dot at the predicted destination (nothing else).
    this.trajectory = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineDashedMaterial({ color: 0xffffff, dashSize: 0.7, gapSize: 0.55, transparent: true, opacity: 0.95, depthTest: false }));
    this.trajectory.renderOrder = 5;
    this.target = new THREE.Mesh(new THREE.SphereGeometry(0.16, 12, 8), new THREE.MeshBasicMaterial({ color: 0xffffff, depthTest: false }));
    this.target.renderOrder = 6;
    this.aimGroup.add(this.trajectory, this.target);
    this.aimGroup.visible = false;
  }

  private applyQuality() {
    const q = this.quality;
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, q === "high" ? 2 : q === "medium" ? 1.5 : 1));
    this.renderer.shadowMap.enabled = SHADOW[q] > 0;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.sun.castShadow = SHADOW[q] > 0;
    if (SHADOW[q]) {
      this.sun.shadow.mapSize.set(SHADOW[q], SHADOW[q]);
      const cam = this.sun.shadow.camera;
      cam.left = -70; cam.right = 70; cam.top = 50; cam.bottom = -50; cam.near = 10; cam.far = 220;
      this.sun.shadow.bias = -0.0005;
      cam.updateProjectionMatrix();
    }
  }

  setQuality(q: Quality) {
    if (q === this.quality) return;
    this.quality = q;
    this.applyQuality();
    this.pitchKey = "";             // rebuild textures/crowd at the new level
    for (const rig of this.rigs.values()) this.scene.remove(rig.root);
    this.rigs.clear();
  }

  resize(width: number, height: number) {
    this.renderer.setSize(width, height, false);
    this.canvas.style.width = `${width}px`; this.canvas.style.height = `${height}px`;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    this.overlay.width = Math.round(width * dpr); this.overlay.height = Math.round(height * dpr);
    this.overlay.style.width = `${width}px`; this.overlay.style.height = `${height}px`;
    this.camera.aspect = width / Math.max(1, height);
    this.camera.fov = this.camera.aspect < 0.8 ? 62 : this.camera.aspect < 1.2 ? 52 : 45;
    this.camera.updateProjectionMatrix();
  }

  freeze(on: boolean) { this.frozen = on; if (on) this.cinematic = null; }

  dispose() {
    this.renderer.dispose();
    this.scene.traverse((obj) => { const mesh = obj as THREE.Mesh; if (mesh.geometry && !Object.values(geo).includes(mesh.geometry as never)) mesh.geometry.dispose(); });
  }

  /** Pointer (client px) -> pitch coordinates by raycasting onto the grass plane. */
  pick(clientX: number, clientY: number): PickResult {
    const rect = this.canvas.getBoundingClientRect();
    const ndc = new THREE.Vector2(((clientX - rect.left) / rect.width) * 2 - 1, -((clientY - rect.top) / rect.height) * 2 + 1);
    this.ray.setFromCamera(ndc, this.camera);
    const hit = new THREE.Vector3();
    if (!this.ray.ray.intersectPlane(this.ground, hit)) return null;
    return [(hit.x + this.L / 2) / this.L, (hit.z + this.W / 2) / this.W];
  }

  private world(nx: number, ny: number, y = 0, out = new THREE.Vector3()): THREE.Vector3 {
    return out.set(nx * this.L - this.L / 2, y, ny * this.W - this.W / 2);
  }

  // -------------------------------------------------------------------------- static set
  private buildPitch(view: InteractiveView) {
    const { length: L, width: W, goal, box } = view.pitch;
    this.L = L; this.W = W;
    const key = `${L}x${W}:${goal}:${this.quality}`;
    if (key === this.pitchKey) return;
    this.pitchKey = key;
    this.pitchGroup.clear();
    this.nets = [];
    const shadows = SHADOW[this.quality] > 0;
    const margin = 8 * (L / 105) + 4;
    const fullL = L + margin * 2, fullW = W + margin * 2;
    const res = TEXTURE[this.quality];
    const pxm = res / fullL;
    const tex = canvasTexture(res, Math.round(fullW * pxm), (ctx) => {
      const X = (m: number) => (m + margin) * pxm, Y = (m: number) => (m + margin) * pxm;
      ctx.fillStyle = "#56b046"; ctx.fillRect(0, 0, res, fullW * pxm);
      // Diagonal checkerboard mowing (two greens), like a freshly cut stadium lawn.
      const cell = 6 * (L / 105) * pxm;
      ctx.save(); ctx.translate(X(L / 2), Y(W / 2)); ctx.rotate(Math.PI / 4);
      const span = Math.hypot(fullL, fullW) * pxm;
      const n = Math.ceil(span / cell);
      for (let i = -n; i < n; i += 1) for (let j = -n; j < n; j += 1) {
        ctx.fillStyle = Math.abs(i + j) % 2 === 0 ? "#56b046" : "#54ad44";   // barely-there checker
        ctx.fillRect(i * cell, j * cell, cell + 0.5, cell + 0.5);
      }
      ctx.restore();
      // Soft mowing stripes along the length over the checker, then fine grass grain.
      // Broadcast-style mowing stripes along the length, with a soft gradient inside each stripe.
      for (let i = 0; i < 18; i += 1) {
        const x0 = X((L / 18) * i), w = (L / 18) * pxm;
        const grad = ctx.createLinearGradient(x0, 0, x0 + w, 0);
        const tone = i % 2 ? "rgba(255,255,240,0.075)" : "rgba(0,40,0,0.06)";
        grad.addColorStop(0, tone); grad.addColorStop(0.5, tone); grad.addColorStop(1, i % 2 ? "rgba(255,255,240,0.05)" : "rgba(0,40,0,0.04)");
        ctx.fillStyle = grad; ctx.fillRect(x0, Y(0), w, W * pxm);
      }
      // Large, soft colour patches (natural variation, not a pattern).
      for (let i = 0; i < 40; i += 1) {
        const cx = X(((i * 37) % 100) / 100 * L), cy = Y(((i * 61) % 100) / 100 * W), r = (6 + (i % 5) * 3) * pxm;
        const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, r);
        g.addColorStop(0, i % 3 ? "rgba(70,140,40,0.06)" : "rgba(150,200,80,0.05)"); g.addColorStop(1, "rgba(0,0,0,0)");
        ctx.fillStyle = g; ctx.fillRect(cx - r, cy - r, r * 2, r * 2);
      }
      let seed = 11; const rand = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
      for (let i = 0; i < res * 6; i += 1) { ctx.fillStyle = rand() < 0.5 ? "rgba(255,255,255,0.035)" : "rgba(0,0,0,0.05)"; ctx.fillRect(rand() * res, rand() * fullW * pxm, 2, 3); }
      // Surround (darker) outside the touchlines.
      ctx.fillStyle = "rgba(20,60,20,0.25)";
      ctx.fillRect(0, 0, res, Y(0)); ctx.fillRect(0, Y(W), res, margin * pxm); ctx.fillRect(0, 0, X(0), fullW * pxm); ctx.fillRect(X(L), 0, margin * pxm, fullW * pxm);
      ctx.strokeStyle = "rgba(255,255,255,0.95)"; ctx.lineWidth = Math.max(2, 0.14 * pxm); ctx.lineCap = "round";
      const poly = (pts: [number, number][], close = false) => { ctx.beginPath(); pts.forEach(([x, y], i) => (i ? ctx.lineTo(X(x), Y(y)) : ctx.moveTo(X(x), Y(y)))); if (close) ctx.closePath(); ctx.stroke(); };
      const s = L / 105;
      poly([[0, 0], [L, 0], [L, W], [0, W]], true); poly([[L / 2, 0], [L / 2, W]]);
      ctx.beginPath(); ctx.arc(X(L / 2), Y(W / 2), 9.15 * s * pxm, 0, Math.PI * 2); ctx.stroke();
      const halfBox = Math.min(W * 0.46, box * (20.16 / 16.5)), six = box / 3, halfSix = Math.min(W * 0.3, box * (9.16 / 16.5));
      const spot = box * (11 / 16.5), arcR = box * (9.15 / 16.5);
      ctx.fillStyle = "#ffffff";
      for (const end of [0, 1]) {
        const x = end ? L : 0, d = end ? -1 : 1;
        poly([[x, W / 2 - halfBox], [x + d * box, W / 2 - halfBox], [x + d * box, W / 2 + halfBox], [x, W / 2 + halfBox]]);
        poly([[x, W / 2 - halfSix], [x + d * six, W / 2 - halfSix], [x + d * six, W / 2 + halfSix], [x, W / 2 + halfSix]]);
        ctx.beginPath(); ctx.arc(X(x + d * spot), Y(W / 2), 0.25 * pxm, 0, Math.PI * 2); ctx.fill();
        const lim = Math.acos(Math.min(1, (box - spot) / arcR));
        ctx.beginPath(); if (end) ctx.arc(X(x + d * spot), Y(W / 2), arcR * pxm, Math.PI - lim, Math.PI + lim); else ctx.arc(X(x + d * spot), Y(W / 2), arcR * pxm, -lim, lim); ctx.stroke();
      }
    });
    const grass = new THREE.Mesh(new THREE.PlaneGeometry(fullL, fullW), new THREE.MeshLambertMaterial({ map: tex }));
    grass.rotation.x = -Math.PI / 2; grass.receiveShadow = true;
    this.pitchGroup.add(grass);
    // Running track / concourse.
    const apron = new THREE.Mesh(new THREE.PlaneGeometry(fullL + 40, fullW + 40), mat("#5d7a4c"));
    apron.rotation.x = -Math.PI / 2; apron.position.y = -0.02; apron.receiveShadow = true;
    this.pitchGroup.add(apron);
    // Goals: posts, crossbar and a deep net exactly at the physical mouth.
    const postMat = new THREE.MeshLambertMaterial({ color: 0xffffff });
    const depth = VISUAL.goalDepthMetres;
    for (const end of [0, 1] as const) {
      const gx = end ? L / 2 : -L / 2, d = end ? 1 : -1;
      const group = new THREE.Group();
      const postGeo = new THREE.CylinderGeometry(0.12, 0.12, CROSSBAR, 12);
      for (const z of [-goal / 2, goal / 2]) { const post = new THREE.Mesh(postGeo, postMat); post.position.set(gx, CROSSBAR / 2, z); post.castShadow = shadows; group.add(post); }
      const bar = new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.12, goal + 0.24, 12), postMat); bar.rotation.x = Math.PI / 2; bar.position.set(gx, CROSSBAR, 0); bar.castShadow = shadows; group.add(bar);
      const supportGeo = new THREE.CylinderGeometry(0.05, 0.05, Math.hypot(depth, CROSSBAR), 6);
      for (const z of [-goal / 2, goal / 2]) { const sup = new THREE.Mesh(supportGeo, postMat); sup.position.set(gx + d * depth / 2, CROSSBAR / 2, z); sup.rotation.z = d * Math.atan2(depth, CROSSBAR); group.add(sup); }
      // Net as a line mesh (back, roof, sides) whose vertices ripple on a goal.
      const pts: number[] = [];
      const step = 0.3;
      const seg = (a: number[], b: number[]) => pts.push(...a, ...b);
      for (let z = -goal / 2; z <= goal / 2 + 1e-6; z += step) { seg([gx + d * depth, 0, z], [gx + d * depth * 0.55, CROSSBAR, z]); seg([gx + d * depth * 0.55, CROSSBAR, z], [gx, CROSSBAR, z]); }
      for (let y = 0; y <= CROSSBAR + 1e-6; y += step) { const xb = gx + d * (depth - (depth * 0.45 * y) / CROSSBAR); seg([xb, y, -goal / 2], [xb, y, goal / 2]); for (const z of [-goal / 2, goal / 2]) seg([gx, y, z], [xb, y, z]); }
      for (let x = 0; x <= depth + 1e-6; x += step) { seg([gx + d * x, 0, -goal / 2], [gx + d * Math.min(x, depth * 0.55), x <= depth * 0.55 ? CROSSBAR : CROSSBAR * (depth - x) / (depth * 0.45), -goal / 2]); seg([gx + d * x, 0, goal / 2], [gx + d * Math.min(x, depth * 0.55), x <= depth * 0.55 ? CROSSBAR : CROSSBAR * (depth - x) / (depth * 0.45), goal / 2]); }
      const netGeo = new THREE.BufferGeometry(); netGeo.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
      const lines = new THREE.LineSegments(netGeo, new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.75 }));
      group.add(lines);
      this.nets.push({ lines, base: Float32Array.from(pts), end });
      const floorShadow = new THREE.Mesh(new THREE.PlaneGeometry(depth, goal), new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.12, depthWrite: false }));
      floorShadow.rotation.x = -Math.PI / 2; floorShadow.position.set(gx + d * depth / 2, 0.01, 0); group.add(floorShadow);
      this.pitchGroup.add(group);
    }
    this.buildStadium(fullL, fullW, shadows);
  }

  private buildStadium(fullL: number, fullW: number, shadows: boolean) {
    let seed = 5; const rand = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
    // Ad boards (fictional sponsors only), each side starting at a different board.
    const brands: [string, string, string][] = [["RESENHA FC", "#0f4fa8", "#ffd31a"], ["BRASILEIRÃO MANAGER", "#e8352e", "#ffffff"], ["VAI PRA CIMA", "#14975a", "#ffffff"],
      ["CRAQUE DA RODADA", "#ffd31a", "#111111"], ["BOLA NA REDE", "#7a2bd1", "#ffffff"], ["ARQUIBANCADA", "#ff7a00", "#111111"], ["GOLAÇO", "#111827", "#c6f24e"],
      ["TABELINHA", "#0ea5e9", "#ffffff"], ["CHAPÉU", "#be123c", "#ffffff"], ["PANENKA", "#f8fafc", "#0f172a"]];
    const boardTex = canvasTexture(4096, 64, (ctx) => {
      const w = 4096 / brands.length;
      brands.forEach(([text, bg, fg], i) => { ctx.fillStyle = bg; ctx.fillRect(i * w, 0, w + 1, 64); ctx.fillStyle = fg; ctx.font = "900 34px 'Barlow Condensed', Inter, sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(text, i * w + w / 2, 34); });
    });
    boardTex.wrapS = THREE.RepeatWrapping;
    const boards: [number, number, number, number][] = [[0, -fullW / 2 - 0.5, fullL, 0], [0, fullW / 2 + 0.5, fullL, Math.PI], [-fullL / 2 - 0.5, 0, fullW, Math.PI / 2], [fullL / 2 + 0.5, 0, fullW, -Math.PI / 2]];
    boards.forEach(([x, z, len, ry], i) => {
      const tex = boardTex.clone(); tex.needsUpdate = true; tex.repeat.set(len / 60, 1); tex.offset.x = i * 0.27;
      const board = new THREE.Mesh(new THREE.BoxGeometry(len, 0.9, 0.15), new THREE.MeshLambertMaterial({ map: tex, emissive: 0x1a1a1a }));
      board.position.set(x, 0.45, z); board.rotation.y = ry; board.castShadow = shadows; this.pitchGroup.add(board);
    });
    // Stands: a front wall, stepped tiers (alternating seat colours) and a roof canopy.
    const tiers = this.quality === "low" ? 7 : 12;
    const rise = 0.75, depth = 1.1, front = 4.5;
    const seatColors = ["#1e4fa8", "#d6dbe3", "#1e4fa8", "#f2c230"].map((c) => mat(c));
    const sides = [
      { cx: 0, cz: -fullW / 2 - front, len: fullL + 14, ry: 0, out: [0, -1] }, { cx: 0, cz: fullW / 2 + front, len: fullL + 14, ry: Math.PI, out: [0, 1] },
      { cx: -fullL / 2 - front, cz: 0, len: fullW + 14, ry: Math.PI / 2, out: [-1, 0] }, { cx: fullL / 2 + front, cz: 0, len: fullW + 14, ry: -Math.PI / 2, out: [1, 0] },
    ];
    for (const side of sides) {
      const wall = new THREE.Mesh(new THREE.BoxGeometry(side.len, 1.6, 0.4), mat("#2b3340"));
      wall.position.set(side.cx - side.out[0] * 0.4, 0.8, side.cz - side.out[1] * 0.4); wall.rotation.y = side.ry; this.pitchGroup.add(wall);
      for (let t = 0; t < tiers; t += 1) {
        const step = new THREE.Mesh(new THREE.BoxGeometry(side.len + t * 2 * depth, 1.6 + t * rise, depth), seatColors[Math.floor(t / 3) % seatColors.length]);
        step.position.set(side.cx + side.out[0] * t * depth, (1.6 + t * rise) / 2, side.cz + side.out[1] * t * depth); step.rotation.y = side.ry;
        step.receiveShadow = shadows; this.pitchGroup.add(step);
      }
      if (this.quality !== "low") {
        const roof = new THREE.Mesh(new THREE.BoxGeometry(side.len + tiers * 2 * depth, 0.4, tiers * depth * 0.7), mat("#e5e7eb"));
        roof.position.set(side.cx + side.out[0] * tiers * depth * 0.6, 1.6 + tiers * rise + 4, side.cz + side.out[1] * tiers * depth * 0.6); roof.rotation.y = side.ry; this.pitchGroup.add(roof);
      }
    }
    // Crowd: people silhouettes (shirt body, skin head, some arms raised), one draw call each part.
    const count = CROWD_COUNT(CROWD[this.quality]);
    const bodyMesh = new THREE.InstancedMesh(new THREE.BoxGeometry(0.46, 0.62, 0.3), new THREE.MeshLambertMaterial(), count);
    const headMesh = new THREE.InstancedMesh(new THREE.BoxGeometry(0.26, 0.28, 0.26), new THREE.MeshLambertMaterial(), count);
    const armMesh = new THREE.InstancedMesh(new THREE.BoxGeometry(0.1, 0.5, 0.1), new THREE.MeshLambertMaterial(), count);
    const shirts = ["#e8352e", "#ffd31a", "#ffffff", "#0f4fa8", "#14975a", "#111111", "#ff7a00", "#7a2bd1", "#c6f24e", "#0ea5e9"].map((c) => new THREE.Color(c));
    const skins = VISUAL.skin.map((c) => new THREE.Color(c));
    const dummy = new THREE.Object3D();
    let arms = 0;
    for (let i = 0; i < count; i += 1) {
      const side = sides[i % 4];
      const t = Math.floor(rand() * tiers);
      const along = (rand() - 0.5) * (side.len + t * 2 * depth - 2);
      const x = side.cx + side.out[0] * t * depth + (side.out[1] !== 0 ? along : 0);
      const z = side.cz + side.out[1] * t * depth + (side.out[0] !== 0 ? along : 0);
      const standing = rand() < 0.35;
      const baseY = 1.6 + t * rise + (standing ? 0.42 : 0.28);
      const shirt = shirts[Math.floor(rand() * shirts.length)];
      dummy.position.set(x, baseY, z); dummy.rotation.set(0, side.ry + (rand() - 0.5) * 0.4, 0); dummy.scale.set(1, standing ? 1.15 : 0.9, 1); dummy.updateMatrix();
      bodyMesh.setMatrixAt(i, dummy.matrix); bodyMesh.setColorAt(i, shirt);
      dummy.position.y = baseY + (standing ? 0.52 : 0.45); dummy.scale.set(1, 1, 1); dummy.updateMatrix();
      headMesh.setMatrixAt(i, dummy.matrix); headMesh.setColorAt(i, skins[Math.floor(rand() * skins.length)]);
      if (standing && rand() < 0.5 && arms < count) {
        dummy.position.set(x + Math.cos(side.ry) * 0.2, baseY + 0.55, z - Math.sin(side.ry) * 0.2); dummy.rotation.z = 0.25; dummy.updateMatrix();
        armMesh.setMatrixAt(arms, dummy.matrix); armMesh.setColorAt(arms, shirt); arms += 1;
        dummy.rotation.z = 0;
      }
    }
    armMesh.count = arms;
    for (const m of [bodyMesh, headMesh, armMesh]) { m.instanceMatrix.needsUpdate = true; if (m.instanceColor) m.instanceColor.needsUpdate = true; }
    const crowd = new THREE.Group(); crowd.add(bodyMesh, headMesh, armMesh);
    this.crowd = crowd;
    this.pitchGroup.add(crowd);
    // Flags at the corners, floodlights, benches and tunnel (discreet).
    const flagColors = ["#e8352e", "#ffd31a", "#0f4fa8", "#14975a"];
    [[-1, -1], [1, -1], [-1, 1], [1, 1]].forEach(([x, z], i) => {
      const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.04, 1.6, 6), mat("#f8fafc")); pole.position.set(x * (fullL / 2 - 0.2), 0.8, z * (fullW / 2 - 0.2)); this.pitchGroup.add(pole);
      const flag = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.35, 0.02), mat(flagColors[i])); flag.position.set(x * (fullL / 2 - 0.2) + 0.25, 1.4, z * (fullW / 2 - 0.2)); this.pitchGroup.add(flag);
      const tower = new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.7, 38, 8), mat("#9aa1ab")); tower.position.set(x * (fullL / 2 + 20), 19, z * (fullW / 2 + 20)); this.pitchGroup.add(tower);
      const lamp = new THREE.Mesh(new THREE.BoxGeometry(8, 4, 1), new THREE.MeshBasicMaterial({ color: 0xfffbe6 })); lamp.position.set(x * (fullL / 2 + 20), 39, z * (fullW / 2 + 20)); lamp.lookAt(0, 0, 0); this.pitchGroup.add(lamp);
    });
    for (const sgn of [-1, 1]) {
      const bench = new THREE.Mesh(new THREE.BoxGeometry(7, 1.4, 1.4), new THREE.MeshLambertMaterial({ color: 0x1b2a44, transparent: true, opacity: 0.85 }));
      bench.position.set(sgn * 10, 0.7, fullW / 2 + 2.2); this.pitchGroup.add(bench);
    }
    const tunnel = new THREE.Mesh(new THREE.BoxGeometry(5, 2.6, 2), mat("#30343b")); tunnel.position.set(0, 1.3, fullW / 2 + 3.4); this.pitchGroup.add(tunnel);
  }

  // -------------------------------------------------------------------------- frame
  render(view: InteractiveView, scene: Scene | null, kits: { attack: Kit; defend: Kit }, overlay: Overlay, now: number) {
    if (this.lost) return;
    const t0 = performance.now();
    this.buildPitch(view);
    const dt = this.lastTime ? Math.min(0.1, now - this.lastTime) : 0.016;
    this.lastTime = now;
    const opp = view.opportunity;
    const seen = new Set<string>();
    if (scene && this.characterStyle === "athlete") {
      let slideSum = 0, slideN = 0;
      for (const p of scene.players) {
        const kit = p.team === "A" ? kits.attack : kits.defend;
        const key = `A|${p.id}|${p.keeper ? kit.gk?.shirt ?? VISUAL.keeperKits[p.team] : kit.shirt}|${kit.shorts}|${kit.pattern ?? ""}|${this.quality}`;
        let av = this.avatars.get(p.id);
        if (!av || av.key !== key) {
          if (av) { this.scene.remove(av.root); av.dispose(); }
          av = new Avatar3D(p, kit, this.quality, SHADOW[this.quality] > 0, geo.ring, key);
          this.avatars.set(p.id, av);
          this.scene.add(av.root);
        }
        seen.add(p.id);
        av.root.visible = true;
        this.world(p.x, p.y, 0, av.root.position);
        const targetRy = Math.atan2(Math.cos(p.facing), Math.sin(p.facing));
        let diff = targetRy - av.root.rotation.y; diff = Math.atan2(Math.sin(diff), Math.cos(diff));
        av.root.rotation.y += diff * Math.min(1, dt * 12);
        av.root.updateMatrixWorld(true);
        av.update(p, scene.step, scene.t, dt, now, scene.playing);
        if (p.speed > 1 && av.slide > 0) { slideSum += av.slide; slideN += 1; }
        av.ring.visible = p.carrier && view.state === "DECISION";
        (av.ring.material as THREE.MeshBasicMaterial).color.set(overlay.yourTurn ? 0xc6f24e : 0xffffff);
        av.ring.scale.setScalar(0.85 + Math.sin(now * 6) * 0.04);
      }
      this.footSlide = slideN ? slideSum / slideN : 0;
    }
    if (scene && this.characterStyle !== "athlete") {
      for (const p of scene.players) {
        const kit = p.team === "A" ? kits.attack : kits.defend;
        const style = this.characterStyle === "voxel" ? "" : "H|";
        const key = `${style}${p.id}|${p.keeper ? kit.gk?.shirt ?? VISUAL.keeperKits[p.team] : kit.shirt}|${kit.shorts}|${kit.pattern ?? ""}`;
        let rig = this.rigs.get(p.id);
        if (!rig || rig.key !== key) {
          if (rig) this.scene.remove(rig.root);
          rig = this.characterStyle === "voxel" ? buildRig(p, kit, SHADOW[this.quality] > 0) : buildHumanRig(p, kit, SHADOW[this.quality] > 0, this.quality as Detail);
          this.rigs.set(p.id, rig);
          this.scene.add(rig.root);
        }
        seen.add(p.id);
        rig.root.visible = true;
        this.world(p.x, p.y, 0, rig.root.position);
        const fx = Math.cos(p.facing), fz = Math.sin(p.facing);
        const targetRy = Math.atan2(fx, fz);
        let diff = targetRy - rig.root.rotation.y; diff = Math.atan2(Math.sin(diff), Math.cos(diff));
        rig.root.rotation.y += diff * Math.min(1, dt * 12);   // smooth turning, no snapping
        blendPose(rig, p, now, dt);
        rig.ring.visible = p.carrier && view.state === "DECISION";
        (rig.ring.material as THREE.MeshBasicMaterial).color.set(overlay.yourTurn ? 0xc6f24e : 0xffffff);
        rig.ring.scale.setScalar(0.85 + Math.sin(now * 6) * 0.04);
      }
    }
    if (scene) {
      const b = scene.ball;
      this.world(b.x, b.y, BALL_RADIUS + b.z, this.ball.position);
      this.ball.visible = !b.held;
      this.ball.rotation.set(b.roll / BALL_RADIUS * 0.5, 0, b.roll / BALL_RADIUS * 0.3);
      this.world(b.x, b.y, 0.02, this.ballShadow.position);
      this.ballShadow.scale.setScalar(BALL_RADIUS * (1 - Math.min(0.5, b.z * 0.08)));
      (this.ballShadow.material as THREE.MeshBasicMaterial).opacity = Math.max(0.1, 0.32 - b.z * 0.04);
      this.ballShadow.visible = !b.held;
      // Net ripple at the goal where the ball went in.
      for (const net of this.nets) {
        const pos = net.lines.geometry.getAttribute("position") as THREE.BufferAttribute;
        const arr = pos.array as Float32Array;
        const r = scene.ripple && scene.ripple.end === net.end && scene.ripple.age < VISUAL.netRippleSeconds ? scene.ripple : null;
        if (!r && arr[0] === net.base[0] && !(net.lines.userData.dirty)) continue;
        const d = net.end ? 1 : -1, zc = r ? r.y * this.W - this.W / 2 : 0;
        const k = r ? (1 - r.age / VISUAL.netRippleSeconds) * Math.abs(Math.sin(r.age * 16)) : 0;
        for (let i = 0; i < arr.length; i += 3) {
          const bx = net.base[i], by = net.base[i + 1], bz = net.base[i + 2];
          const depthK = Math.abs(bx - d * this.L / 2) / VISUAL.goalDepthMetres;
          const near = Math.exp(-(((bz - zc) / 1.8) ** 2) - (((by - 1) / 1.4) ** 2));
          arr[i] = bx + d * near * depthK * k * 0.9; arr[i + 1] = by; arr[i + 2] = bz;
        }
        net.lines.userData.dirty = Boolean(r);
        pos.needsUpdate = true;
      }
    }
    for (const [id, rig] of this.rigs) if (!seen.has(id) || this.characterStyle === "athlete") rig.root.visible = false;
    for (const [id, av] of this.avatars) if (!seen.has(id) || this.characterStyle !== "athlete") av.root.visible = false;
    if (this.crowd) this.crowd.position.y = scene?.ripple && scene.ripple.age < 2 ? Math.abs(Math.sin(now * 10)) * 0.25 : 0;
    this.updateAim(view, scene, overlay, now);
    this.updateCamera(view, scene, overlay, dt, now);
    this.renderer.render(this.scene, this.camera);
    this.drawOverlay(scene, overlay);
    // Performance probe (used for adaptive quality / 2D fallback).
    this.frameTimes.push(performance.now() - t0 + 0);
    if (this.frameTimes.length > 90) this.frameTimes.shift();
    if (opp && opp.id !== this.lastOpp) {
      this.lastOpp = opp.id;
      if (["PENALTY", "FREE_KICK", "ONE_ON_ONE", "CORNER"].includes(opp.kind) && !overlay.yourTurn) this.cinematic = { until: now + 1.4, kind: "intro", from: this.camPos.clone() };
    }
    const goalKey = scene?.step?.cues?.find((c) => c.kind === "GOAL") && scene.ripple ? `${opp?.id}:${scene.step?.starts_at}` : "";
    if (goalKey && goalKey !== this.lastGoal && !this.frozen) { this.lastGoal = goalKey; this.cinematic = { until: now + 2.2, kind: "goal", from: this.camPos.clone() }; }
  }

  /** Average CPU time of a frame (ms) — the browser FPS is measured by the caller. */
  frameCost(): number { return this.frameTimes.length ? this.frameTimes.reduce((a, b) => a + b, 0) / this.frameTimes.length : 0; }

  private carrierPos(scene: Scene | null, overlay: Overlay): [number, number] | null {
    if (!scene || overlay.carrierIndex < 0) return null;
    const c = scene.players[overlay.carrierIndex];
    return c ? [c.x, c.y] : null;
  }

  /** Minimal aim: one dashed line from the ball (on the grass, or along the real loft apex) and a small dot. */
  private updateAim(view: InteractiveView, scene: Scene | null, overlay: Overlay, now: number) {
    const aim = overlay.aim;
    const from = this.carrierPos(scene, overlay);
    if (!aim || !from) { this.aimGroup.visible = false; return; }
    this.aimGroup.visible = true;
    const valid = overlay.aimValid;
    const ballP = this.world(from[0], from[1]);
    const target = predictTarget(view, from, aim);
    const tp = this.world(target[0], target[1]);
    const pts: THREE.Vector3[] = [];
    for (let i = 0; i <= 32; i += 1) {
      const k = i / 32;
      const h = aim.type === "LOFT" ? 4 * 3.2 * k * (1 - k) : 0;
      pts.push(new THREE.Vector3(ballP.x + (tp.x - ballP.x) * k, h + 0.04, ballP.z + (tp.z - ballP.z) * k));
    }
    this.trajectory.geometry.dispose();
    this.trajectory.geometry = new THREE.BufferGeometry().setFromPoints(pts);
    this.trajectory.computeLineDistances();
    const color = valid ? 0xffffff : 0xff6e6e;
    (this.trajectory.material as THREE.LineDashedMaterial).color.set(color);
    (this.target.material as THREE.MeshBasicMaterial).color.set(color);
    this.target.position.set(tp.x, 0.08, tp.z);
    void now;
  }

  private updateCamera(view: InteractiveView, scene: Scene | null, overlay: Overlay, dt: number, now: number) {
    if (this.frozen) { this.camera.position.copy(this.camPos); this.camera.lookAt(this.camLook); return; }
    const opp = view.opportunity;
    const pos = new THREE.Vector3(), look = new THREE.Vector3();
    const portrait = this.camera.aspect < 0.9;
    if (!scene || !opp) {
      // Fast simulation: broadcast camera from the main stand.
      look.set(0, 0, 0); pos.set(0, this.L * 0.42, this.W * 0.5 + this.L * 0.45);
    } else {
      const dir = opp.right === false ? -1 : 1;
      const ball = this.world(scene.ball.x, scene.ball.y);
      const goalX = dir * this.L / 2;
      const toGoal = Math.abs(goalX - ball.x);
      const s = this.L / 105;
      const setPiece = (opp.kind === "PENALTY" || opp.kind === "FREE_KICK") && view.state === "DECISION";
      if (setPiece) {
        // Behind the taker, ball low in the frame, wall/keeper/goal ahead.
        const ahead = new THREE.Vector3(goalX - ball.x, 0, -ball.z).normalize();
        const k = Math.max(0.6, s);
        pos.set(ball.x - ahead.x * 9 * k, 6.5 * k, ball.z - ahead.z * 9 * k);
        look.set(goalX - dir * 3 * k, 1.0, ball.z * 0.3);
      } else if (this.cameraMode === "wide") {
        // Manual wide view: the whole pitch, tactical tilt.
        look.set(dir * this.L * 0.06, 0, 0);
        pos.set(-dir * this.L * 0.5, this.L * (portrait ? 0.95 : 0.62), 0);
      } else {
        // Build-up/finishing: elevated and tilted behind the ball carrier (ball in the lower third,
        // team-mates and the goal ahead), the goal kept in frame when close to it.
        const k = Math.max(0.55, s);
        // Wide enough to read the play: ~35 m of pitch ahead, team-mates and markers in view.
        // V7: steeper (~36°) — the pitch fills the screen instead of the stands (audit item 11).
        const back = (portrait ? 16 : 11.5) * k, height = (portrait ? 19 : 13.5) * k;
        // Far from goal: look down the pitch. Close to it (crosses, byline, box): turn towards
        // the goal mouth so the goal never leaves the frame.
        const near = Math.max(0, Math.min(1, 1 - (toGoal - 12 * k) / (22 * k)));
        let ax = dir, az = 0;
        const gx = goalX - ball.x, gz = -ball.z, gl = Math.hypot(gx, gz) || 1;
        ax = ax * (1 - near) + (gx / gl) * near; az = (gz / gl) * near;
        const al = Math.hypot(ax, az) || 1; ax /= al; az /= al;
        // Short lead: the carrier sits in the lower-middle of the screen, above the action bar.
        const lead = Math.min(6 * k, Math.max(1.5 * k, gl * 0.3));
        look.set(ball.x + ax * lead, 0, ball.z + az * lead);
        pos.set(ball.x - ax * back, height, ball.z - az * back);
      }
      const c = this.cinematic;
      if (c && now < c.until) {
        const k = 1 - (c.until - now) / (c.kind === "goal" ? 2.2 : 1.4);
        if (c.kind === "goal") {
          look.set(goalX, 1.2, ball.z); pos.set(goalX - dir * (7 + k * 3), 1.6 + k * 1.5, ball.z + (6 - k * 8));
        } else {
          look.set(ball.x, 0.6, ball.z); const a = k * 1.2 - 0.6;
          pos.set(ball.x - dir * 4 * Math.cos(a), 1.2 + k * 2, ball.z + 4 * Math.sin(a));
        }
        this.camPos.copy(pos); this.camLook.copy(look);
      } else this.cinematic = null;
    }
    // A new opportunity (or the first frame) cuts straight to its framing; then it follows smoothly.
    const cut = Boolean(opp && opp.id !== this.framedOpp);
    if (opp) this.framedOpp = opp.id;
    const smooth = cut ? 1 : 1 - Math.exp(-dt * 3.2);
    this.camPos.lerp(pos, this.cinematic ? 1 : smooth);
    this.camLook.lerp(look, this.cinematic ? 1 : smooth);
    this.camera.position.copy(this.camPos);
    this.camera.lookAt(this.camLook);
    void overlay;
  }

  /** Skip the cinematic and settle the gameplay camera immediately (a gesture is starting). */
  settle(view: InteractiveView, scene: Scene | null, overlay: Overlay) {
    this.cinematic = null;
    for (let i = 0; i < 40; i += 1) this.updateCamera(view, scene, overlay, 0.5, 0);
  }

  /** Client (page) coordinates of a pitch point on the grass (playtest hook and overlays). */
  clientOf(x: number, y: number): [number, number] | null {
    const v = this.world(x, y, 0).project(this.camera);
    if (v.z > 1) return null;
    const rect = this.canvas.getBoundingClientRect();
    return [rect.left + ((v.x + 1) / 2) * rect.width, rect.top + ((1 - v.y) / 2) * rect.height];
  }

  private project(x: number, y: number, h: number): [number, number] | null {
    const v = this.world(x, y, h).project(this.camera);
    if (v.z > 1) return null;
    const w = this.overlay.width, hh = this.overlay.height;
    return [((v.x + 1) / 2) * w, ((1 - v.y) / 2) * hh];
  }

  private drawOverlay(scene: Scene | null, overlay: Overlay) {
    const ctx = this.overlay.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, this.overlay.width, this.overlay.height);
    if (!scene) return;
    const dpr = this.overlay.width / Math.max(1, this.overlay.getBoundingClientRect().width || this.overlay.width);
    if (overlay.label && overlay.carrierIndex >= 0) {
      const c = scene.players[overlay.carrierIndex];
      const s = this.project(c.x, c.y, PLAYER_HEIGHT + 0.45);
      if (s) {
        const text = `${c.number || ""} ${c.name.split(" ").slice(-1)[0]}`.trim();
        ctx.font = `800 ${Math.round(13 * dpr)}px Inter, system-ui, sans-serif`;
        const w = ctx.measureText(text).width + 16 * dpr, h = 22 * dpr;
        ctx.fillStyle = "rgba(10,14,20,0.82)"; ctx.beginPath(); ctx.roundRect(s[0] - w / 2, s[1] - h, w, h, h / 2); ctx.fill();
        ctx.fillStyle = "#ffffff"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(text, s[0], s[1] - h / 2);
      }
    }
  }
}

function CROWD_COUNT(n: number) { return Math.max(100, n); }

export function webglAvailable(): boolean {
  try {
    const canvas = document.createElement("canvas");
    return Boolean(canvas.getContext("webgl2") ?? canvas.getContext("webgl"));
  } catch { return false; }
}

export type { Aim };

/**
 * Athlete showcase (Gameplay Lab, #lab-atleta): one athlete on the grass with a turntable
 * camera, cycling through idle / run / kick / dive, to review the model and its animation
 * from the front, back, side and close up. Purely visual; no match state involved.
 */
export function mountAthleteShowcase(host: HTMLElement, opts: { keeper?: boolean; style?: "human" | "voxel"; angle?: number; zoom?: number; pose?: string; autoRotate?: boolean }): () => void {
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.shadowMap.enabled = true;
  host.append(renderer.domElement);
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x9fd3ff);
  scene.add(new THREE.HemisphereLight(0xeef6ff, 0x46703a, 1.25));
  const sun = new THREE.DirectionalLight(0xffefd2, 1.9); sun.position.set(-3, 8, 4); sun.castShadow = true; sun.shadow.mapSize.set(1024, 1024);
  scene.add(sun);
  const grass = new THREE.Mesh(new THREE.CircleGeometry(6, 48), new THREE.MeshLambertMaterial({ color: 0x56b046 }));
  grass.rotation.x = -Math.PI / 2; grass.receiveShadow = true; scene.add(grass);
  const kit: Kit = { shirt: "#C8102E", shorts: "#111111", socks: "#C8102E", trim: "#111111", number: "#FFFFFF", pattern: "plain", gk: { shirt: "#F5B83D", shorts: "#1E1E24", socks: "#F5B83D", trim: "#1E1E24", number: "#111111" } };
  const player: ScenePlayer = { id: "showcase-10", name: "Atleta", number: 10, team: "A", role: opts.keeper ? "GK" : "MF", club: "LAB", x: 0, y: 0, vx: 0, vy: 0, speed: 0, facing: 0,
    stride: 0, pose: "idle", poseK: 0, poseDir: 1, carrier: false, keeper: Boolean(opts.keeper), act: -1 };
  const rig = opts.style === "voxel" ? buildRig(player, kit, true) : buildHumanRig(player, kit, true, "high");
  rig.root.traverse((o) => { o.castShadow = true; });
  scene.add(rig.root);
  const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 100);
  let raf = 0; const start = performance.now();
  const sequence = opts.pose ? [opts.pose] : ["idle", "run", "kick", "run", opts.keeper ? "dive" : "celebrate"];
  const loop = () => {
    raf = requestAnimationFrame(loop);
    const w = host.clientWidth, h = host.clientHeight;
    if (renderer.domElement.width !== Math.round(w * renderer.getPixelRatio())) { renderer.setSize(w, h); camera.aspect = w / Math.max(1, h); camera.updateProjectionMatrix(); }
    const t = (performance.now() - start) / 1000;
    const seg = sequence[Math.floor(t / 2.4) % sequence.length];
    const k = (t % 2.4) / 2.4;
    player.pose = seg as ScenePlayer["pose"];
    player.speed = seg === "run" ? 6.5 : 0;
    player.stride = seg === "run" ? t * 2.6 : 0;
    player.poseK = seg === "kick" || seg === "dive" ? Math.min(1, k * 1.6) : k;
    blendPose(rig, player, t, 1 / 60);
    const angle = (opts.angle ?? 0) + (opts.autoRotate === false ? 0 : t * 0.5);
    const dist = (seg === "dive" ? 6.5 : 4.2) / (opts.zoom ?? 1);
    camera.position.set(Math.sin(angle) * dist, 1.25 + 0.2 / (opts.zoom ?? 1), Math.cos(angle) * dist);
    camera.lookAt(seg === "dive" ? 0.9 : 0, opts.zoom && opts.zoom > 1.5 ? 1.5 : seg === "dive" ? 0.5 : 0.95, 0);
    renderer.render(scene, camera);
  };
  loop();
  return () => { cancelAnimationFrame(raf); renderer.dispose(); renderer.domElement.remove(); };
}
