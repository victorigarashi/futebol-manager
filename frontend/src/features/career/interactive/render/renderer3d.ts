import * as THREE from "three";

import type { InteractiveView } from "../../../../lib/api";
import { predictTarget, type Aim } from "../gesture";
import { VISUAL, hashOf } from "./config";
import type { Scene, ScenePlayer } from "./presentation";
import type { Kit, Overlay } from "./renderer2d";

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
const BODY_SCALE = 1.12;          // stylised: players read big, like a mobile football game
const BALL_RADIUS = 0.3;          // visual only (the physics ball is 0.11 m)
const CROSSBAR = 2.44;            // same height the physics uses for lofted balls

type Limb = { upper: THREE.Group; lower: THREE.Group };
type Rig = {
  root: THREE.Group; body: THREE.Group; head: THREE.Group; torso: THREE.Mesh;
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

const numberTextures = new Map<string, THREE.MeshLambertMaterial>();
function jerseyBack(shirt: string, number: number, trim: string): THREE.MeshLambertMaterial {
  const key = `${shirt}|${number}|${trim}`;
  let m = numberTextures.get(key);
  if (!m) {
    const tex = canvasTexture(128, 128, (ctx) => {
      ctx.fillStyle = shirt; ctx.fillRect(0, 0, 128, 128);
      ctx.fillStyle = trim; ctx.fillRect(0, 0, 128, 14);
      ctx.font = "900 78px 'Barlow Condensed', 'Arial Narrow', sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      const light = new THREE.Color(shirt).getHSL({ h: 0, s: 0, l: 0 }).l > 0.6;
      ctx.lineWidth = 6; ctx.strokeStyle = light ? "rgba(255,255,255,0.8)" : "rgba(0,0,0,0.5)";
      ctx.strokeText(String(number || ""), 64, 74);
      ctx.fillStyle = light ? "#141414" : "#ffffff"; ctx.fillText(String(number || ""), 64, 74);
    });
    m = new THREE.MeshLambertMaterial({ map: tex });
    numberTextures.set(key, m);
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

function buildRig(p: ScenePlayer, kit: Kit, shadows: boolean): Rig {
  const look = hashOf(p.id);
  const skin = VISUAL.skin[look % VISUAL.skin.length];
  const hair = VISUAL.hair[(look >> 4) % VISUAL.hair.length];
  const boots = VISUAL.boots[(look >> 8) % VISUAL.boots.length];
  const style = (look >> 12) % 5;
  const shirt = p.keeper ? VISUAL.keeperKits[p.team] : kit.shirt;
  const shorts = p.keeper ? "#2a2a33" : kit.shorts;
  const socks = p.keeper ? shirt : kit.socks;
  const root = new THREE.Group();
  const body = new THREE.Group(); root.add(body);
  body.scale.setScalar(BODY_SCALE);
  const legL = limb(body, -0.15, 0.92, skin, socks, boots, 0.46, 0.44, 0.22, true, shadows);
  const legR = limb(body, 0.15, 0.92, skin, socks, boots, 0.46, 0.44, 0.22, true, shadows);
  part(body, shorts, 0.6, 0.27, 0.36, 0, 0.98, 0, shadows);
  const front = mat(shirt);
  const back = jerseyBack(shirt, p.number, p.keeper ? "#ffffff" : kit.trim);
  // Box faces: +X, -X, +Y, -Y, +Z (front), -Z (back: the number).
  const torso = part(body, [front, front, front, front, front, back] as unknown as THREE.Material, 0.64, 0.6, 0.36, 0, 1.4, 0, shadows);
  part(body, p.keeper ? "#ffffff" : kit.trim, 0.66, 0.08, 0.38, 0, 1.68, 0, shadows);
  const armL = limb(body, -0.42, 1.66, shirt, skin, p.keeper ? "#f2f2f2" : skin, 0.32, 0.32, 0.16, false, shadows);
  const armR = limb(body, 0.42, 1.66, shirt, skin, p.keeper ? "#f2f2f2" : skin, 0.32, 0.32, 0.16, false, shadows);
  const head = new THREE.Group(); head.position.set(0, 1.74, 0); body.add(head);
  part(head, skin, 0.16, 0.1, 0.16, 0, 0.03, 0, shadows);
  part(head, skin, 0.52, 0.52, 0.48, 0, 0.32, 0, shadows);
  // Face (simple, original): eyes, brows, mouth.
  for (const s of [-1, 1]) {
    part(head, "#1b1b1b", 0.07, 0.09, 0.02, s * 0.12, 0.34, 0.245, false);
    part(head, hair, 0.12, 0.03, 0.02, s * 0.12, 0.42, 0.245, false);
  }
  part(head, "#7a3b2e", 0.12, 0.03, 0.02, 0, 0.2, 0.245, false);
  part(head, skin, 0.08, 0.1, 0.06, 0, 0.28, 0.26, false);
  // Hair styles.
  if (style === 0) { part(head, hair, 0.56, 0.12, 0.52, 0, 0.62, 0, shadows); part(head, hair, 0.56, 0.3, 0.06, 0, 0.47, -0.24, shadows); }
  else if (style === 1) { part(head, hair, 0.56, 0.2, 0.52, 0, 0.64, -0.02, shadows); part(head, hair, 0.58, 0.46, 0.08, 0, 0.36, -0.24, shadows); for (const s of [-1, 1]) part(head, hair, 0.06, 0.3, 0.4, s * 0.28, 0.48, -0.04, shadows); }
  else if (style === 2) { part(head, hair, 0.14, 0.22, 0.5, 0, 0.66, 0, shadows); part(head, hair, 0.56, 0.06, 0.52, 0, 0.58, 0, shadows); }
  else if (style === 3) { for (let i = 0; i < 5; i += 1) part(head, hair, 0.12, 0.18, 0.12, -0.2 + i * 0.1, 0.65, ((i % 2) - 0.5) * 0.12, shadows); part(head, hair, 0.56, 0.08, 0.52, 0, 0.58, 0, shadows); }
  else { part(head, hair, 0.58, 0.06, 0.54, 0, 0.58, 0, shadows); }
  const ring = new THREE.Mesh(geo.ring, new THREE.MeshBasicMaterial({ color: 0xc6f24e, transparent: true, opacity: 0.9, depthWrite: false }));
  ring.position.y = 0.03; ring.visible = false; root.add(ring);
  return { root, body, head, torso, armL, armR, legL, legR, ring, key: `${p.id}|${shirt}|${kit.shorts}` };
}

function poseRig(rig: Rig, p: ScenePlayer, now: number) {
  const look = hashOf(p.id);
  const run = Math.min(1, p.speed / 7.5);
  const phase = (p.stride / VISUAL.strideMetres) * Math.PI * 2;
  const swing = p.pose === "run" ? Math.sin(phase) * (0.35 + run * 0.75) : 0;
  const b = rig.body;
  b.position.set(0, 0, 0); b.rotation.set(0, 0, 0);
  rig.head.rotation.set(0, 0, 0);
  const set = (l: Limb, ux: number, lx: number, uz = 0) => { l.upper.rotation.set(ux, 0, uz); l.lower.rotation.set(lx, 0, 0); };
  set(rig.legL, -swing, Math.max(0, swing) * 1.1);
  set(rig.legR, swing, Math.max(0, -swing) * 1.1);
  set(rig.armL, swing * 0.9, -0.3 - run * 0.5, 0.12);
  set(rig.armR, -swing * 0.9, -0.3 - run * 0.5, -0.12);
  b.rotation.x = run * 0.18;
  b.position.y = p.pose === "run" ? Math.abs(Math.sin(phase)) * 0.08 * run : Math.sin(now * 2 + look) * 0.01;
  const k = p.poseK;
  switch (p.pose) {
    case "kick": {
      const back = k < 0.35 ? k / 0.35 : 1 - Math.min(1, (k - 0.35) / 0.25);
      const fwd = k < 0.35 ? 0 : Math.min(1, (k - 0.35) / 0.3);
      set(rig.legR, 0.9 * back - 1.25 * fwd, 0.9 * back);
      set(rig.legL, 0.1, 0.15);
      set(rig.armL, -0.3, -0.2, 0.9); set(rig.armR, 0.4, -0.2, -0.9);
      b.rotation.x = -0.1 + 0.25 * fwd;
      break;
    }
    case "tackle": {
      const s = Math.min(1, k * 2.5);
      b.rotation.x = -1.05 * s; b.position.y = 0.25 * s; b.position.z = 0.6 * k;
      set(rig.legR, -1.3 * s, 0.1); set(rig.legL, -0.4 * s, 1.2 * s);
      set(rig.armL, -0.8, -0.2, 0.9); set(rig.armR, -0.8, -0.2, -0.9);
      break;
    }
    case "header": {
      const j = Math.sin(Math.min(1, k) * Math.PI);
      b.position.y = 0.55 * j; b.rotation.x = 0.35 * j; rig.head.rotation.x = 0.4 * j;
      set(rig.legL, 0.3, 0.9); set(rig.legR, -0.2, 0.6);
      set(rig.armL, -0.3, -0.2, 1.1); set(rig.armR, -0.3, -0.2, -1.1);
      break;
    }
    case "dive": case "save": {
      // poseDir: +1/-1 along the pitch width; converted to the keeper's own side.
      const s = Math.min(1, k * 1.6);
      const ry = rig.root.rotation.y;
      const side = Math.sign(-Math.sin(ry) * p.poseDir) || 1;   // local +X in world is (cos ry, 0, -sin ry)
      b.rotation.z = -side * 1.35 * s; b.position.x = side * 0.9 * s; b.position.y = 0.6 * Math.sin(Math.min(1, k) * Math.PI) + 0.2 * s;
      set(rig.armL, 0, 0, side < 0 ? 2.9 : 2.6); set(rig.armR, 0, 0, side < 0 ? -2.6 : -2.9);
      set(rig.legL, 0.2, 0.4, 0.2 * side); set(rig.legR, -0.2, 0.3, 0.2 * side);
      break;
    }
    case "hold": set(rig.armL, -1.4, -0.6, 0.2); set(rig.armR, -1.4, -0.6, -0.2); break;
    case "ready": set(rig.legL, -0.35, 0.7, 0.15); set(rig.legR, -0.35, 0.7, -0.15); b.position.y = -0.1; set(rig.armL, -0.5, -0.4, 0.7); set(rig.armR, -0.5, -0.4, -0.7); break;
    case "celebrate": {
      const j = Math.abs(Math.sin(now * 8 + look));
      b.position.y = 0.35 * j;
      set(rig.armL, 0, -0.2, 2.7); set(rig.armR, 0, -0.2, -2.7);
      set(rig.legL, -0.3 * j, 0.6 * j); set(rig.legR, 0.2 * j, 0.4 * j);
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
  private crowd: THREE.InstancedMesh | null = null;
  private aimGroup = new THREE.Group();
  private arrow: THREE.Mesh;
  private trajectory: THREE.Line;
  private sectorDots: THREE.InstancedMesh;
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
  private lastGoal = "";
  quality: Quality;
  cameraMode: CameraMode = "auto";
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
    this.scene.add(new THREE.HemisphereLight(0xf2f8ff, 0x4d7a32, 1.05));
    this.sun = new THREE.DirectionalLight(0xfff1d6, 1.55);
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
    // Aim: a thick 3D arrow lying on the grass, dashed trajectory, sector dots and a target ring.
    const shape = new THREE.Shape();
    shape.moveTo(-0.32, 0); shape.lineTo(0.32, 0); shape.lineTo(0.32, 0.72); shape.lineTo(0.75, 0.72); shape.lineTo(0, 1); shape.lineTo(-0.75, 0.72); shape.lineTo(-0.32, 0.72); shape.closePath();
    const arrowGeo = new THREE.ExtrudeGeometry(shape, { depth: 0.22, bevelEnabled: true, bevelThickness: 0.05, bevelSize: 0.05, bevelSegments: 1 });
    arrowGeo.rotateX(-Math.PI / 2); // lies on the ground, pointing to -Z... reoriented per frame
    this.arrow = new THREE.Mesh(arrowGeo, new THREE.MeshLambertMaterial({ color: 0xffd31a, emissive: 0x5a4300 }));
    this.arrow.castShadow = true;
    this.trajectory = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineDashedMaterial({ color: 0xffffff, dashSize: 0.9, gapSize: 0.6, transparent: true, opacity: 0.95 }));
    this.sectorDots = new THREE.InstancedMesh(geo.box, new THREE.MeshBasicMaterial({ color: 0xe6ff8c }), 80);
    this.target = new THREE.Mesh(geo.ring, new THREE.MeshBasicMaterial({ color: 0xffd31a, transparent: true, opacity: 0.9, depthWrite: false }));
    this.aimGroup.add(this.arrow, this.trajectory, this.sectorDots, this.target);
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
    this.camera.fov = this.camera.aspect < 0.8 ? 58 : this.camera.aspect < 1.2 ? 50 : 42;
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
      ctx.fillStyle = "#55b441"; ctx.fillRect(0, 0, res, fullW * pxm);
      // Diagonal checkerboard mowing (two greens), like a freshly cut stadium lawn.
      const cell = 6 * (L / 105) * pxm;
      ctx.save(); ctx.translate(X(L / 2), Y(W / 2)); ctx.rotate(Math.PI / 4);
      const span = Math.hypot(fullL, fullW) * pxm;
      const n = Math.ceil(span / cell);
      for (let i = -n; i < n; i += 1) for (let j = -n; j < n; j += 1) {
        ctx.fillStyle = Math.abs(i + j) % 2 === 0 ? "#6cc94f" : "#4fa83c";
        ctx.fillRect(i * cell, j * cell, cell + 0.5, cell + 0.5);
      }
      ctx.restore();
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
    // Ad boards (fictional sponsors only) around the pitch.
    const brands = ["RESENHA FC", "BRASILEIRÃO MANAGER", "VAI PRA CIMA", "CRAQUE DA RODADA", "BOLA NA REDE", "ARQUIBANCADA"];
    const colors = [["#0f4fa8", "#ffd31a"], ["#e8352e", "#ffffff"], ["#14975a", "#ffffff"], ["#ffd31a", "#111111"], ["#7a2bd1", "#ffffff"], ["#ff7a00", "#111111"]];
    const boardTex = canvasTexture(2048, 64, (ctx) => {
      for (let i = 0; i < 6; i += 1) {
        const [bg, fg] = colors[i]; ctx.fillStyle = bg; ctx.fillRect(i * 341, 0, 342, 64);
        ctx.fillStyle = fg; ctx.font = "900 34px 'Barlow Condensed', Inter, sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(brands[i], i * 341 + 170, 34);
      }
    });
    tex2Repeat(boardTex, 2);
    const boardMat = new THREE.MeshLambertMaterial({ map: boardTex, emissive: 0x222222 });
    const boards: [number, number, number, number][] = [[0, -fullW / 2 - 0.5, fullL, 0], [0, fullW / 2 + 0.5, fullL, Math.PI], [-fullL / 2 - 0.5, 0, fullW, Math.PI / 2], [fullL / 2 + 0.5, 0, fullW, -Math.PI / 2]];
    for (const [x, z, len, ry] of boards) {
      const board = new THREE.Mesh(new THREE.BoxGeometry(len, 1.0, 0.2), boardMat);
      board.position.set(x, 0.5, z); board.rotation.y = ry; board.castShadow = shadows; this.pitchGroup.add(board);
    }
    // Stands: stepped tiers on the four sides, crowd instanced (one draw call).
    const tiers = this.quality === "low" ? 6 : 10;
    const standMat = mat("#c9ccd2"), seatMat = mat("#2a5fb0");
    const crowdCount = CROSSWALK(CROWD[this.quality]);
    const crowdGeo = new THREE.BoxGeometry(0.55, 0.9, 0.45);
    const crowd = new THREE.InstancedMesh(crowdGeo, new THREE.MeshLambertMaterial(), crowdCount);
    const dummy = new THREE.Object3D();
    const palette = ["#e8352e", "#ffd31a", "#ffffff", "#0f4fa8", "#14975a", "#111111", "#ff7a00", "#7a2bd1"].map((c) => new THREE.Color(c));
    let placed = 0;
    let seed = 5; const rand = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
    const sides: { cx: number; cz: number; len: number; ry: number; out: [number, number] }[] = [
      { cx: 0, cz: -fullW / 2 - 4, len: fullL + 10, ry: 0, out: [0, -1] }, { cx: 0, cz: fullW / 2 + 4, len: fullL + 10, ry: Math.PI, out: [0, 1] },
      { cx: -fullL / 2 - 4, cz: 0, len: fullW + 10, ry: Math.PI / 2, out: [-1, 0] }, { cx: fullL / 2 + 4, cz: 0, len: fullW + 10, ry: -Math.PI / 2, out: [1, 0] },
    ];
    for (const side of sides) {
      for (let t = 0; t < tiers; t += 1) {
        const stepMesh = new THREE.Mesh(new THREE.BoxGeometry(side.len + t * 3, 1.2 + t * 1.2, 1.6), t % 3 === 0 ? seatMat : standMat);
        stepMesh.position.set(side.cx + side.out[0] * t * 1.6, (1.2 + t * 1.2) / 2, side.cz + side.out[1] * t * 1.6); stepMesh.rotation.y = side.ry;
        stepMesh.receiveShadow = shadows; this.pitchGroup.add(stepMesh);
      }
    }
    while (placed < crowdCount) {
      const side = sides[placed % 4];
      const t = Math.floor(rand() * tiers);
      const along = (rand() - 0.5) * (side.len + t * 3 - 2);
      const x = side.cx + side.out[0] * t * 1.6 + (side.out[1] !== 0 ? along : 0);
      const z = side.cz + side.out[1] * t * 1.6 + (side.out[0] !== 0 ? along : 0);
      dummy.position.set(x, 1.2 + t * 1.2 + 0.45, z); dummy.rotation.y = side.ry; dummy.scale.set(1, 0.85 + rand() * 0.35, 1); dummy.updateMatrix();
      crowd.setMatrixAt(placed, dummy.matrix); crowd.setColorAt(placed, palette[Math.floor(rand() * palette.length)]);
      placed += 1;
    }
    crowd.instanceMatrix.needsUpdate = true;
    this.crowd = crowd;
    this.pitchGroup.add(crowd);
    // Heads on the crowd (a second instanced mesh, same transforms raised).
    const heads = new THREE.InstancedMesh(new THREE.BoxGeometry(0.4, 0.4, 0.4), new THREE.MeshLambertMaterial(), crowdCount);
    const m = new THREE.Matrix4(), lift = new THREE.Matrix4().makeTranslation(0, 0.68, 0);
    const skins = VISUAL.skin.map((c) => new THREE.Color(c));
    for (let i = 0; i < crowdCount; i += 1) { crowd.getMatrixAt(i, m); heads.setMatrixAt(i, m.multiply(lift)); heads.setColorAt(i, skins[i % skins.length]); }
    heads.instanceMatrix.needsUpdate = true;
    crowd.add(heads);
    // Floodlights, benches and tunnels (discreet).
    for (const [x, z] of [[-1, -1], [1, -1], [-1, 1], [1, 1]] as const) {
      const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.7, 36, 8), mat("#9aa1ab")); pole.position.set(x * (fullL / 2 + 16), 18, z * (fullW / 2 + 16)); this.pitchGroup.add(pole);
      const lamp = new THREE.Mesh(new THREE.BoxGeometry(7, 4, 1), new THREE.MeshBasicMaterial({ color: 0xfffbe6 })); lamp.position.set(x * (fullL / 2 + 16), 37, z * (fullW / 2 + 16)); lamp.lookAt(0, 0, 0); this.pitchGroup.add(lamp);
    }
    for (const s of [-1, 1]) {
      const bench = new THREE.Mesh(new THREE.BoxGeometry(8, 1.6, 1.6), new THREE.MeshLambertMaterial({ color: 0x1b2a44, transparent: true, opacity: 0.85 }));
      bench.position.set(s * 12, 0.8, fullW / 2 + 2); this.pitchGroup.add(bench);
    }
    const tunnel = new THREE.Mesh(new THREE.BoxGeometry(6, 3, 4), mat("#30343b")); tunnel.position.set(0, 1.5, fullW / 2 + 5); this.pitchGroup.add(tunnel);
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
    if (scene) {
      for (const p of scene.players) {
        const kit = p.team === "A" ? kits.attack : kits.defend;
        const key = `${p.id}|${p.keeper ? VISUAL.keeperKits[p.team] : kit.shirt}|${kit.shorts}`;
        let rig = this.rigs.get(p.id);
        if (!rig || rig.key !== key) {
          if (rig) this.scene.remove(rig.root);
          rig = buildRig(p, kit, SHADOW[this.quality] > 0);
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
        poseRig(rig, p, now);
        const receiver = overlay.receivers.has(p.id);
        rig.ring.visible = p.carrier || receiver;
        (rig.ring.material as THREE.MeshBasicMaterial).color.set(p.carrier ? (overlay.yourTurn ? 0xc6f24e : 0xffffff) : 0x7cc8ff);
        rig.ring.scale.setScalar(p.carrier ? 1.25 + Math.sin(now * 6) * 0.06 : 1);
      }
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
    for (const [id, rig] of this.rigs) if (!seen.has(id)) rig.root.visible = false;
    if (this.crowd) this.crowd.position.y = scene?.ripple && scene.ripple.age < 2 ? Math.abs(Math.sin(now * 10)) * 0.25 : 0;
    this.updateAim(view, scene, overlay, now);
    this.updateCamera(view, scene, overlay, dt, now);
    this.renderer.render(this.scene, this.camera);
    this.drawOverlay(view, scene, overlay);
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

  private updateAim(view: InteractiveView, scene: Scene | null, overlay: Overlay, now: number) {
    const aim = overlay.aim ?? overlay.pending;
    const from = this.carrierPos(scene, overlay);
    if (!aim || !from) { this.aimGroup.visible = false; return; }
    this.aimGroup.visible = true;
    const valid = overlay.aim ? overlay.aimValid : true;
    const angle = Math.atan2(aim.uy * view.pitch.width, aim.ux * view.pitch.length);
    const dirX = Math.cos(angle), dirZ = Math.sin(angle);
    const ballP = this.world(from[0], from[1]);
    // Arrow: starts at the ball, length grows with power.
    const length = 2 + aim.power * 5.5;
    this.arrow.scale.set(1.4, 1, length);
    this.arrow.position.set(ballP.x + dirX * 0.7, 0.06, ballP.z + dirZ * 0.7);
    this.arrow.rotation.set(0, Math.atan2(dirX, dirZ) + Math.PI, 0);
    (this.arrow.material as THREE.MeshLambertMaterial).color.set(valid ? 0xffd31a : 0xff4d4f);
    (this.arrow.material as THREE.MeshLambertMaterial).opacity = overlay.pending && !overlay.aim ? 0.5 : 1;
    // Predicted path (the same forecast the 2D draws); a lofted ball rises to the physics apex.
    const target = predictTarget(view, from, aim);
    const tp = this.world(target[0], target[1]);
    const pts: THREE.Vector3[] = [];
    for (let i = 0; i <= 32; i += 1) {
      const k = i / 32;
      const h = aim.type === "LOFT" ? 4 * 3.2 * k * (1 - k) : aim.type === "SHOT" ? 0.3 : 0.15;
      pts.push(new THREE.Vector3(ballP.x + (tp.x - ballP.x) * k, h + 0.1, ballP.z + (tp.z - ballP.z) * k));
    }
    this.trajectory.geometry.dispose();
    this.trajectory.geometry = new THREE.BufferGeometry().setFromPoints(pts);
    this.trajectory.computeLineDistances();
    (this.trajectory.material as THREE.LineDashedMaterial).color.set(valid ? VISUAL.aim[aim.type] : VISUAL.aim.invalid);
    this.target.position.set(tp.x, 0.05, tp.z);
    this.target.scale.setScalar(1.3 + Math.sin(now * 7) * 0.1);
    // Dotted assistance sector: the real angular window used by the engine to find a receiver.
    const sector = view.physics.assist_angle ?? 0.24;
    const reach = Math.hypot(tp.x - ballP.x, tp.z - ballP.z);
    const dummy = new THREE.Object3D();
    let n = 0;
    if ((aim.type === "PASS" || aim.type === "LOFT") && valid) {
      for (const s of [-1, 1]) for (let i = 1; i <= 40 && n < 80; i += 1) {
        const d = (reach * i) / 40;
        const a = angle + s * sector;
        dummy.position.set(ballP.x + Math.cos(a) * d, 0.04, ballP.z + Math.sin(a) * d);
        dummy.scale.set(0.25, 0.04, 0.25); dummy.updateMatrix();
        this.sectorDots.setMatrixAt(n, dummy.matrix); n += 1;
      }
    }
    this.sectorDots.count = n;
    this.sectorDots.instanceMatrix.needsUpdate = true;
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
        pos.set(ball.x - ahead.x * 11 * k, 10 * k, ball.z - ahead.z * 11 * k);
        look.set(goalX - dir * 3 * k, 1.0, ball.z * 0.3);
      } else if (this.cameraMode === "wide") {
        look.set(ball.x + dir * 12 * s, 0, ball.z * 0.5);
        pos.set(look.x - dir * 30 * Math.max(0.6, s), 30 * Math.max(0.6, s) + 4, look.z);
      } else {
        // Build-up/finishing: elevated and tilted behind the ball carrier (ball in the lower third,
        // team-mates and the goal ahead), the goal kept in frame when close to it.
        const k = Math.max(0.6, s);
        const lead = Math.min(9 * k, toGoal * 0.45);
        look.set(ball.x + dir * lead, 0, ball.z * 0.92);
        const back = (portrait ? 17 : 15) * k, height = (portrait ? 17 : 14) * k;
        pos.set(ball.x - dir * back, height, ball.z * 0.97);
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
    const smooth = 1 - Math.exp(-dt * 3.2);
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

  private project(x: number, y: number, h: number): [number, number] | null {
    const v = this.world(x, y, h).project(this.camera);
    if (v.z > 1) return null;
    const w = this.overlay.width, hh = this.overlay.height;
    return [((v.x + 1) / 2) * w, ((1 - v.y) / 2) * hh];
  }

  private drawOverlay(view: InteractiveView, scene: Scene | null, overlay: Overlay) {
    const ctx = this.overlay.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, this.overlay.width, this.overlay.height);
    if (!scene) return;
    const dpr = this.overlay.width / Math.max(1, this.overlay.getBoundingClientRect().width || this.overlay.width);
    const aim = overlay.aim;
    const from = this.carrierPos(scene, overlay);
    if (aim && from) {
      // Power % above the arrow head, live while dragging.
      const angle = Math.atan2(aim.uy * view.pitch.width, aim.ux * view.pitch.length);
      const length = 2 + aim.power * 5.5;
      const L = view.pitch.length, W = view.pitch.width;
      const hx = from[0] + (Math.cos(angle) * (length + 1.6)) / L, hy = from[1] + (Math.sin(angle) * (length + 1.6)) / W;
      const s = this.project(hx, hy, 1.2);
      if (s) {
        ctx.font = `900 ${Math.round(26 * dpr)}px "Barlow Condensed", Inter, sans-serif`; ctx.textAlign = "center"; ctx.textBaseline = "middle";
        ctx.lineWidth = 5 * dpr; ctx.strokeStyle = "rgba(60,40,0,0.75)"; ctx.strokeText(`${Math.round(aim.power * 100)}%`, s[0], s[1]);
        ctx.fillStyle = "#ffe36b"; ctx.fillText(`${Math.round(aim.power * 100)}%`, s[0], s[1]);
      }
    }
    if (overlay.label && overlay.carrierIndex >= 0) {
      const c = scene.players[overlay.carrierIndex];
      const s = this.project(c.x, c.y, 3.6 * BODY_SCALE * 0.75);
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

function tex2Repeat(tex: THREE.Texture, n: number) { tex.wrapS = THREE.RepeatWrapping; tex.repeat.set(n, 1); }
function CROSSWALK(n: number) { return Math.max(100, n); }

export function webglAvailable(): boolean {
  try {
    const canvas = document.createElement("canvas");
    return Boolean(canvas.getContext("webgl2") ?? canvas.getContext("webgl"));
  } catch { return false; }
}

export type { Aim };
