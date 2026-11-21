import * as THREE from "three";
import { addPose, lerpPose, type Pose, type Rig } from "../athlete/rig";
import { CLIPS, measureStride, samplePose, type ClipDef } from "./clips";
import { twoBoneIK } from "./ik";

/**
 * Locomotion layer (research prototype): the official engine moves the root; this only
 * chooses the body pose so the feet agree with that motion.
 *
 *  - "naive":     each gait clip plays at its authored rate (what most quick integrations do)
 *  - "synced":    one gait phase for all clips, advanced at speed / stride(speed), where the
 *                 stride of each clip was measured by FK (root motion extraction)
 *  - "synced+ik": synced + foot locking: a planted foot is pinned to the grass with two-bone
 *                 IK until it lifts, then released smoothly.
 * Leans come from the root's own kinematics: forward lean ∝ acceleration, bank ∝ v·ω.
 */
export type LocoMode = "naive" | "synced" | "synced+ik";
export type Body = { group: THREE.Object3D; rig: Rig; setPose: (p: Pose) => void };

type Gait = { def: ClipDef; stride: number; centre: number };
let gaits: Gait[] | null = null;
export function gaitTable(): Gait[] {
  return (gaits ??= [
    { def: CLIPS.walk, stride: measureStride(CLIPS.walk).stride, centre: 1.5 },
    { def: CLIPS.run, stride: measureStride(CLIPS.run).stride, centre: 4.2 },
    { def: CLIPS.sprint, stride: measureStride(CLIPS.sprint).stride, centre: 8.0 },
  ]);
}
let dribbleStride: number | null = null;

/** Blend weights for idle / walk / run / sprint at a speed (piecewise linear, sum = 1). */
export function gaitWeights(speed: number): { idle: number; walk: number; run: number; sprint: number } {
  const ramp = (x: number, a: number, b: number) => Math.max(0, Math.min(1, (x - a) / (b - a)));
  const idle = 1 - ramp(speed, 0.15, 0.9);
  const toRun = ramp(speed, 2.0, 3.0), toSprint = ramp(speed, 5.2, 7.2);
  const moving = 1 - idle;
  return { idle, walk: moving * (1 - toRun), run: moving * toRun * (1 - toSprint), sprint: moving * toRun * toSprint };
}

const SOLE = { heel: new THREE.Vector3(0, -0.082, -0.08), ball: new THREE.Vector3(0, -0.022, 0) };
type Lock = { active: boolean; pos: THREE.Vector3; w: number; contactPrev: boolean; id: number; delta: THREE.Vector3 };

export class Locomotion {
  mode: LocoMode = "synced+ik";
  dribble = false;
  phase = 0;
  private idleT = 0;
  private naiveT: Record<string, number> = { walk: 0, run: 0, sprint: 0, dribble: 0 };
  private lastYaw: number | null = null;
  private lastSpeed = 0;
  private lean = { fwd: 0, bank: 0 };
  private locks: Record<"L" | "R", Lock> = {
    L: { active: false, pos: new THREE.Vector3(), w: 0, contactPrev: false, id: 0, delta: new THREE.Vector3() },
    R: { active: false, pos: new THREE.Vector3(), w: 0, contactPrev: false, id: 0, delta: new THREE.Vector3() },
  };
  // sliding meter (world, sole points of a planted foot)
  private prevSole: Record<"L" | "R", { y: number; id: number; pts: THREE.Vector3[] } | null> = { L: null, R: null };
  slide = { sum: 0, time: 0, max: 0, samples: 0 };
  lastStride = 0;
  lastCadence = 0;
  /** Event hook: the dribble touch (phase crossing the clip's contact u). */
  onTouch: (() => void) | null = null;
  footPlants: { side: "L" | "R"; at: THREE.Vector3 }[] = [];

  resetMeter() { this.slide = { sum: 0, time: 0, max: 0, samples: 0 }; this.prevSole = { L: null, R: null }; }

  update(body: Body, dt: number, speed: number, yaw: number): Pose {
    // ---- kinematics of the root (for leans)
    const yawRate = this.lastYaw === null ? 0 : wrap(yaw - this.lastYaw) / Math.max(dt, 1e-4);
    this.lastYaw = yaw;
    const accel = (speed - this.lastSpeed) / Math.max(dt, 1e-4);
    this.lastSpeed = speed;
    const k = Math.min(1, dt * 6);
    this.lean.fwd += (Math.max(-6, Math.min(6, accel)) * 1.6 - this.lean.fwd) * k;
    this.lean.bank += (Math.atan2(speed * yawRate, 9.81) * 57.3 * 0.8 - this.lean.bank) * k;

    // ---- gait pose
    const g = gaitTable();
    const w = gaitWeights(speed);
    const useDribble = this.dribble && speed > 1.2;
    const dribbleDef = CLIPS.dribble;
    if (useDribble && dribbleStride === null) dribbleStride = measureStride(dribbleDef).stride;
    const strideNow = useDribble ? dribbleStride! : (w.walk * g[0].stride + w.run * g[1].stride + w.sprint * g[2].stride) / Math.max(1e-6, w.walk + w.run + w.sprint);
    const prevPhase = this.phase;
    let pose: Pose;
    if (this.mode === "naive") {
      // every clip at its own authored rate, independent of the real speed
      for (const name of ["walk", "run", "sprint", "dribble"]) this.naiveT[name] += dt / CLIPS[name].meta.duration;
      const p = (name: string) => samplePose(CLIPS[name], this.naiveT[name]);
      pose = useDribble ? p("dribble") : blend([[p("walk"), w.walk], [p("run"), w.run], [p("sprint"), w.sprint]]);
      this.phase = useDribble ? this.naiveT.dribble % 1 : this.naiveT.run % 1;
      this.lastCadence = 1 / CLIPS.run.meta.duration;
    } else {
      const rate = speed > 0.05 ? speed / Math.max(0.3, strideNow) : 0;
      this.phase = (this.phase + rate * dt) % 1;
      this.lastCadence = rate;
      pose = useDribble ? samplePose(dribbleDef, this.phase) : blend([[samplePose(g[0].def, this.phase), w.walk], [samplePose(g[1].def, this.phase), w.run], [samplePose(g[2].def, this.phase), w.sprint]]);
    }
    this.lastStride = strideNow;
    if (w.idle > 0) {
      this.idleT += dt / CLIPS.idle.meta.duration;
      pose = w.idle >= 0.999 ? samplePose(CLIPS.idle, this.idleT) : lerpPose(pose, samplePose(CLIPS.idle, this.idleT), w.idle);
    }
    if (useDribble && dribbleDef.meta.contact) {
      const cu = dribbleDef.meta.contact.u;
      if ((prevPhase < cu && this.phase >= cu) || (prevPhase > this.phase && (prevPhase < cu || this.phase >= cu))) this.onTouch?.();
    }
    // leans (degrees): accelerate -> forward, brake -> back; bank into turns
    pose = addPose(pose, { spineFlex: this.lean.fwd * 0.6, pelvisFlex: this.lean.fwd * 0.25, spineRoll: this.lean.bank * 0.6, pelvisRoll: this.lean.bank * 0.4, headRoll: -this.lean.bank * 0.5 });
    body.setPose(pose);
    body.group.updateMatrixWorld(true);

    // ---- foot locking
    if (this.mode === "synced+ik") {
      for (const side of ["L", "R"] as const) this.footLock(body, side, dt, speed);
    }
    this.meter(body, dt);
    return pose;
  }

  private footLock(body: Body, side: "L" | "R", dt: number, speed: number) {
    const lock = this.locks[side];
    const thigh = body.rig.bones[`thigh${side}`], shin = body.rig.bones[`shin${side}`], foot = body.rig.bones[`foot${side}`];
    const pts = solePoints(body.rig, side);
    const id = pts[0].y < pts[1].y - 0.004 ? 0 : 1;
    const contact = pts[id].y < 0.025 && speed > 0.1;
    if (contact && !lock.contactPrev) {
      // new plant: pin the sole point that touches the grass (heel or ball)
      lock.active = true; lock.id = id; lock.pos.copy(pts[id]); lock.delta.set(0, 0, 0);
      this.footPlants.push({ side, at: pts[id].clone() });
      if (this.footPlants.length > 60) this.footPlants.shift();
    } else if (contact && id !== lock.id) {
      // roll-over heel -> ball: re-anchor on the new point where it already is (after correction)
      lock.pos.copy(pts[id]).add(lock.delta); lock.id = id;
    }
    if (!contact) lock.active = false;
    lock.contactPrev = contact;
    lock.w += ((lock.active ? 1 : 0) - lock.w) * Math.min(1, dt * (lock.active ? 40 : 12));
    if (lock.active) lock.delta.set(lock.pos.x - pts[lock.id].x, 0, lock.pos.z - pts[lock.id].z);
    if (lock.w > 0.01 && lock.delta.lengthSq() > 1e-8) {
      const dl = lock.delta.length();
      if (dl > 0.4) {   // soft clamp: the anchor drifts instead of snapping (bounded slip, never over-stretch)
        const k = (dl - 0.4) / dl;
        lock.pos.addScaledVector(lock.delta, -k); lock.delta.multiplyScalar(1 - k);
      }
      const ankle = foot.getWorldPosition(new THREE.Vector3());
      twoBoneIK(thigh, shin, foot, ankle.addScaledVector(lock.delta, lock.w), 1, true);
    }
  }

  private meter(body: Body, dt: number) {
    for (const side of ["L", "R"] as const) {
      const pts = solePoints(body.rig, side);
      const id = pts[0].y < pts[1].y - 0.004 ? 0 : 1;
      const prev = this.prevSole[side];
      if (prev && pts[id].y < 0.02 && prev.y < 0.02) {
        // same sole point as the previous sample: rolling from heel to ball is not sliding
        const pid = prev.id;
        const v = Math.hypot(pts[pid].x - prev.pts[pid].x, pts[pid].z - prev.pts[pid].z) / Math.max(dt, 1e-4);
        this.slide.sum += v * dt; this.slide.time += dt; this.slide.samples += 1;
        if (v > this.slide.max) this.slide.max = v;
      }
      this.prevSole[side] = { y: pts[id].y, id, pts };
    }
  }

  /** Mean sliding speed of planted soles (cm/s). */
  slideMean(): number { return this.slide.time > 0 ? (this.slide.sum / this.slide.time) * 100 : 0; }
}

const tmpV = new THREE.Vector3();
function solePoints(rig: Rig, side: "L" | "R"): THREE.Vector3[] {
  return [tmpV.copy(SOLE.heel).applyMatrix4(rig.bones[`foot${side}`].matrixWorld).clone(), tmpV.copy(SOLE.ball).applyMatrix4(rig.bones[`toe${side}`].matrixWorld).clone()];
}
export function lowestSole(rig: Rig, side: "L" | "R"): THREE.Vector3 {
  const heel = tmpV.copy(SOLE.heel).applyMatrix4(rig.bones[`foot${side}`].matrixWorld).clone();
  const ball = tmpV.copy(SOLE.ball).applyMatrix4(rig.bones[`toe${side}`].matrixWorld).clone();
  return heel.y < ball.y ? heel : ball;
}

function blend(items: [Pose, number][]): Pose {
  let total = 0;
  let out: Pose = {};
  for (const [p, w] of items) {
    if (w <= 1e-4) continue;
    total += w;
    out = total === w ? { ...p } : lerpPose(out, p, w / total);
  }
  return out;
}
const wrap = (a: number) => Math.atan2(Math.sin(a), Math.cos(a));

/** A simple "engine stand-in": accelerate/brake/turn with physical limits (like PLAYER_ACCEL). */
export type PathKind = "straight" | "circle" | "figure8" | "zigzag" | "stopgo";
export class RootDriver {
  pos = new THREE.Vector3();
  yaw = 0;
  speed = 0;
  t = 0;
  constructor(public kind: PathKind, public maxSpeed: number, public accel = 7, public decel = 9) {}
  reset() { this.pos.set(0, 0, 0); this.yaw = 0; this.speed = 0; this.t = 0; }
  step(dt: number) {
    this.t += dt;
    let wantSpeed = this.maxSpeed, wantYaw = this.yaw;
    const T = this.t;
    switch (this.kind) {
      case "straight": { const ph = T % 10; wantSpeed = ph < 4 ? this.maxSpeed : ph < 5 ? 0 : ph < 9 ? this.maxSpeed : 0; wantYaw = ph < 5 ? 0 : Math.PI; break; }
      case "circle": break;
      case "figure8": wantYaw = this.yaw + Math.sign(Math.sin(T * 0.35)) * 0.6; break;
      case "zigzag": wantYaw = (Math.floor(T / 1.2) % 2 ? 0.7 : -0.7); break;
      case "stopgo": { const ph = T % 4; wantSpeed = ph < 2.2 ? this.maxSpeed : 0; wantYaw = Math.floor(T / 4) * 0.8; break; }
    }
    // steer home when far from the origin (no teleport: it would corrupt the sliding meter)
    if (this.kind !== "straight" && this.pos.length() > 16) wantYaw = Math.atan2(-this.pos.x, -this.pos.z);
    // turning rate limited by lateral grip (a_lat = v * yawRate <= 7 m/s^2) and a max yaw rate
    const maxYawRate = Math.min(4, 7 / Math.max(1, this.speed));
    if (this.kind === "circle" && this.pos.length() <= 16) this.yaw += Math.min(maxYawRate, this.speed / 6) * dt;   // r = 6 m
    else this.yaw += Math.max(-maxYawRate * dt, Math.min(maxYawRate * dt, wrap(wantYaw - this.yaw)));
    const dv = wantSpeed - this.speed;
    this.speed += Math.max(-this.decel * dt, Math.min(this.accel * dt, dv));
    this.pos.x += Math.sin(this.yaw) * this.speed * dt;
    this.pos.z += Math.cos(this.yaw) * this.speed * dt;
  }
}
