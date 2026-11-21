import * as THREE from "three";
import type { Athlete } from "../../../football/athlete/athlete";
import { lerpPose, mirrorPose, type Pose } from "../../../football/athlete/rig";
import { CLIPS, GK_READY_POSE, measureStride, samplePose } from "../../../football/anim/clips";
import { twoBoneIK } from "../../../football/anim/ik";
import { toThree } from "../props";
import type { KeeperResult, KFrame } from "./sim";

/**
 * Drives a keeper athlete from the physics frames (never the other way round):
 *  - the hips follow the simulated centre of mass; the body roll is the simulated tilt;
 *  - the dive clip only provides the SHAPE, keyed by the simulated dive progress;
 *  - both arms are solved with two-bone IK onto the simulated hand positions, so the
 *    gloves are exactly where the contact test put them.
 */
let shuffleStride: number | null = null;
export class KeeperAnimator {
  private shufflePhase = 0;
  private lastY: number | null = null;
  constructor(public athlete: Athlete) {}

  apply(res: KeeperResult | null, t: number, dt: number): void {
    const a = this.athlete;
    if (!res || t < 0) { this.idle(t); return; }
    const f = frameAt(res.frames, t);
    const first = (ph: KFrame["phase"]) => res.frames.find((x) => x.phase === ph)?.t ?? null;
    const plan = res.plan;
    const mir = (p: Pose) => (f.side < 0 ? mirrorPose(p) : p);
    let pose: Pose;
    let rooted = false;   // true: hips placed on the CoM (airborne / on the ground)
    let roll = 0;
    switch (f.phase) {
      case "react": case "set":
        pose = t < 0.3 ? samplePose(CLIPS.gk_set, t / 0.3) : GK_READY_POSE; break;
      case "shuffle": case "gather": case "claimrun": {
        shuffleStride ??= measureStride(CLIPS.gk_shuffle, "x").stride || 0.9;
        const vy = f.vel.y;
        if (this.lastY !== null) this.shufflePhase = (this.shufflePhase + Math.abs(f.com.y - this.lastY) / shuffleStride) % 1;
        if (f.phase === "claimrun" && Math.hypot(f.vel.x, f.vel.y) > 1.5) pose = samplePose(CLIPS.run, this.shufflePhase * 0.8);
        else {
          const sh = samplePose(CLIPS.gk_shuffle, this.shufflePhase);
          pose = lerpPose(GK_READY_POSE, vy >= 0 ? sh : mirrorPose(sh), Math.min(1, Math.abs(vy) / 1.2));
        }
        // crouch for low balls (the physics lowered the CoM)
        pose = { ...pose, rootY: (pose.rootY ?? 0) + (f.com.z - 0.95) * 0.9, kneeL: (pose.kneeL ?? 0) + (0.95 - f.com.z) * 160, kneeR: (pose.kneeR ?? 0) + (0.95 - f.com.z) * 160, hipFlexL: (pose.hipFlexL ?? 0) + (0.95 - f.com.z) * 90, hipFlexR: (pose.hipFlexR ?? 0) + (0.95 - f.com.z) * 90 };
        break;
      }
      case "load": case "flight": {
        if (plan?.kind === "claim" || plan?.kind === "jump") {
          const tl = first("load") ?? t;
          pose = samplePose(CLIPS.gk_jump, Math.min(1, (t - tl) / 0.55 * 0.42));
          rooted = f.phase === "flight";
        } else if (plan?.kind === "collapse") {
          pose = mir(samplePose(CLIPS.gk_collapse, Math.min(1, f.diveU / 0.62 * 0.5)));
          rooted = f.phase === "flight"; roll = -f.tilt * f.side;
        } else {
          const def = (plan?.at.z ?? 0) > 1.3 ? CLIPS.gk_dive_high : CLIPS.gk_dive_low;
          pose = mir(samplePose(def, f.diveU));
          rooted = f.phase === "flight"; roll = -f.tilt * f.side;
        }
        break;
      }
      case "ground": {
        const def = (plan?.at.z ?? 0) > 1.3 ? CLIPS.gk_dive_high : CLIPS.gk_dive_low;
        pose = mir(samplePose(plan?.kind === "collapse" ? CLIPS.gk_collapse : def, f.diveU));
        rooted = true; roll = -f.tilt * f.side;
        break;
      }
      case "recover": default: {
        const tr = first("recover") ?? t;
        const fromGround = first("ground") !== null;
        pose = fromGround ? mir(samplePose(CLIPS.gk_getup, Math.min(1, (t - tr) / 1.0))) : GK_READY_POSE;
        rooted = false;
        roll = fromGround ? -(Math.PI / 2) * f.side * Math.max(0, 1 - (t - tr) / 0.45) : 0;
        break;
      }
    }
    this.lastY = f.com.y;
    // ---- place the body
    a.group.rotation.set(0, 0, roll);
    a.group.position.set(0, 0, 0);
    a.setPose(pose);
    a.group.updateMatrixWorld(true);
    const com = toThree(f.com);
    if (rooted || Math.abs(roll) > 0.05) {
      const hips = a.rig.bones.hips.getWorldPosition(new THREE.Vector3());
      a.group.position.copy(com).sub(hips);
      if (!rooted) a.group.position.y = Math.max(a.group.position.y, 0);
    } else {
      a.group.position.set(com.x, 0, com.z);
    }
    a.group.updateMatrixWorld(true);
    // ---- arms onto the simulated hands
    if (f.phase !== "react" && f.phase !== "recover" && f.reach > 0.4) {
      const hL = toThree(f.handL), hR = toThree(f.handR);
      const sL = a.rig.bones.upperArmL.getWorldPosition(new THREE.Vector3()), sR = a.rig.bones.upperArmR.getWorldPosition(new THREE.Vector3());
      // assign each simulated hand to the nearer shoulder (no crossed arms)
      const swap = hL.distanceTo(sR) + hR.distanceTo(sL) < hL.distanceTo(sL) + hR.distanceTo(sR);
      const tl = swap ? hR : hL, tr = swap ? hL : hR;
      const w = Math.min(1, (f.reach - 0.4) / 0.25);
      const wrist = (target: THREE.Vector3, shoulder: THREE.Vector3) => target.clone().addScaledVector(target.clone().sub(shoulder).normalize(), -0.07);
      twoBoneIK(a.rig.bones.upperArmL, a.rig.bones.foreArmL, a.rig.bones.handL, wrist(tl, sL), w, false);
      twoBoneIK(a.rig.bones.upperArmR, a.rig.bones.foreArmR, a.rig.bones.handR, wrist(tr, sR), w, false);
    }
    void dt;
  }

  idle(t: number) {
    const a = this.athlete;
    a.group.rotation.set(0, 0, 0);
    a.setPose(samplePose(CLIPS.gk_ready, ((t % 1.2) + 1.2) % 1.2 / 1.2));
  }
}

export function frameAt(frames: KFrame[], t: number): KFrame {
  if (t <= frames[0].t) return frames[0];
  const last = frames[frames.length - 1];
  if (t >= last.t) return last;
  let lo = 0, hi = frames.length - 1;
  while (hi - lo > 1) { const m = (lo + hi) >> 1; if (frames[m].t <= t) lo = m; else hi = m; }
  const A = frames[lo], B = frames[hi];
  const k = (t - A.t) / (B.t - A.t);
  const L = (x: number, y: number) => x + (y - x) * k;
  const V = (p: { x: number; y: number; z: number }, q: { x: number; y: number; z: number }) => ({ x: L(p.x, q.x), y: L(p.y, q.y), z: L(p.z, q.z) });
  return { ...A, t, com: V(A.com, B.com), vel: V(A.vel, B.vel), tilt: L(A.tilt, B.tilt), diveU: L(A.diveU, B.diveU), handL: V(A.handL, B.handL), handR: V(A.handR, B.handR), reach: L(A.reach, B.reach), ball: V(A.ball, B.ball) };
}
