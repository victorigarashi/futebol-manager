import * as THREE from "three";
import { applyPose, createSkeleton, type Pose, type Rig } from "../athlete/rig";

/**
 * Forward kinematics on a headless rig (no renderer): ground contact points and body
 * landmarks for a pose. Used to ground authored poses, to measure stride length (root
 * motion extraction) and to verify contacts in tests.
 */
let shared: Rig | null = null;
export function fkRig(): Rig { return (shared ??= createSkeleton()); }

// Sole points in the foot bone frame (ankle at y = 0.085 in the bind pose) and in the toe frame.
const HEEL = new THREE.Vector3(0, -0.082, -0.08);
const BALL = new THREE.Vector3(0, -0.022, 0.0);     // under the toe joint, in the toe frame
const TIP = new THREE.Vector3(0, -0.012, 0.065);    // toe tip, in the toe frame

export type Contacts = { heelL: THREE.Vector3; ballL: THREE.Vector3; tipL: THREE.Vector3; heelR: THREE.Vector3; ballR: THREE.Vector3; tipR: THREE.Vector3 };
export function contactPoints(rig: Rig, out?: Contacts): Contacts {
  rig.root.updateMatrixWorld(true);
  const o = out ?? { heelL: new THREE.Vector3(), ballL: new THREE.Vector3(), tipL: new THREE.Vector3(), heelR: new THREE.Vector3(), ballR: new THREE.Vector3(), tipR: new THREE.Vector3() };
  o.heelL.copy(HEEL).applyMatrix4(rig.bones.footL.matrixWorld);
  o.ballL.copy(BALL).applyMatrix4(rig.bones.toeL.matrixWorld);
  o.tipL.copy(TIP).applyMatrix4(rig.bones.toeL.matrixWorld);
  o.heelR.copy(HEEL).applyMatrix4(rig.bones.footR.matrixWorld);
  o.ballR.copy(BALL).applyMatrix4(rig.bones.toeR.matrixWorld);
  o.tipR.copy(TIP).applyMatrix4(rig.bones.toeR.matrixWorld);
  return o;
}

/** Lowest sole point and which one it is (comparisons across samples must use the same point). */
export function lowestWithId(c: Contacts, side: "L" | "R"): { p: THREE.Vector3; id: number } {
  const pts = side === "L" ? [c.heelL, c.ballL, c.tipL] : [c.heelR, c.ballR, c.tipR];
  let id = 0;
  for (let i = 1; i < 3; i += 1) if (pts[i].y < pts[id].y - 0.004) id = i;
  return { p: pts[id], id };
}
/** Lowest sole point of one foot (the point that would carry the weight). */
export function lowestOf(c: Contacts, side: "L" | "R"): THREE.Vector3 {
  const pts = side === "L" ? [c.heelL, c.ballL, c.tipL] : [c.heelR, c.ballR, c.tipR];
  return pts.reduce((a, b) => (b.y < a.y ? b : a));
}

const tmp = new THREE.Vector3();
export function worldOf(rig: Rig, bone: keyof Rig["bones"], local?: THREE.Vector3): THREE.Vector3 {
  rig.root.updateMatrixWorld(true);
  return tmp.copy(local ?? new THREE.Vector3()).applyMatrix4(rig.bones[bone].matrixWorld).clone();
}

/** Height offset that puts the requested foot (or the lowest of both) on y = 0. */
export function groundOffset(p: Pose, mode: "L" | "R" | "lowest"): number {
  const rig = fkRig();
  applyPose(rig, p);
  const c = contactPoints(rig);
  const y = mode === "lowest" ? Math.min(lowestOf(c, "L").y, lowestOf(c, "R").y) : lowestOf(c, mode).y;
  return -y;
}
