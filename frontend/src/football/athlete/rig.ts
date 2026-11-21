import * as THREE from "three";

/**
 * Football Lab humanoid rig (research prototype, original, generated in code).
 *
 * 21 bones, bind pose with identity rotations (only offsets), so a pose is just a set of
 * local rotations. Conventions (documented in docs/research/football-lab/RIG.md):
 *   - metres, Y up, the athlete faces +Z, feet on y = 0, 1.82 m tall;
 *   - "L" is the athlete's own left, which is +X when facing +Z;
 *   - every angle in the pose API is anatomical (flexion, abduction...) in degrees and is
 *     converted to bone rotations by `applyPose`, so authoring never deals with signs.
 *
 * Proportions follow Drillis & Contini segment ratios for H = 1.82 m
 * (thigh 0.245H, shank 0.246H, upper arm 0.186H, forearm 0.146H, biacromial 0.259H).
 */
export const BONES = [
  "hips", "spine", "chest", "neck", "head",
  "clavicleL", "upperArmL", "foreArmL", "handL",
  "clavicleR", "upperArmR", "foreArmR", "handR",
  "thighL", "shinL", "footL", "toeL",
  "thighR", "shinR", "footR", "toeR",
] as const;
export type BoneName = typeof BONES[number];
export const BONE_INDEX = Object.fromEntries(BONES.map((b, i) => [b, i])) as Record<BoneName, number>;

export const PARENT: Record<BoneName, BoneName | null> = {
  hips: null, spine: "hips", chest: "spine", neck: "chest", head: "neck",
  clavicleL: "chest", upperArmL: "clavicleL", foreArmL: "upperArmL", handL: "foreArmL",
  clavicleR: "chest", upperArmR: "clavicleR", foreArmR: "upperArmR", handR: "foreArmR",
  thighL: "hips", shinL: "thighL", footL: "shinL", toeL: "footL",
  thighR: "hips", shinR: "thighR", footR: "shinR", toeR: "footR",
};

type V3 = [number, number, number];
const L = (x: number, y: number, z: number): V3 => [x, y, z];
const mirror = ([x, y, z]: V3): V3 => [-x, y, z];

const left: Partial<Record<BoneName, V3>> = {
  clavicleL: L(0.035, 1.455, 0.0),
  upperArmL: L(0.188, 1.462, -0.018),
  foreArmL: L(0.212, 1.13, -0.03),
  handL: L(0.232, 0.87, -0.005),
  thighL: L(0.088, 0.955, 0.0),
  shinL: L(0.094, 0.52, 0.012),
  footL: L(0.098, 0.085, -0.012),
  toeL: L(0.104, 0.022, 0.138),
};

/** Bind joint positions in model space. */
export const JOINT: Record<BoneName, V3> = {
  hips: L(0, 0.99, 0.0),
  spine: L(0, 1.1, -0.004),
  chest: L(0, 1.28, -0.012),
  neck: L(0, 1.505, -0.022),
  head: L(0, 1.6, -0.006),
  ...(left as Record<string, V3>),
  clavicleR: mirror(left.clavicleL!), upperArmR: mirror(left.upperArmL!), foreArmR: mirror(left.foreArmL!), handR: mirror(left.handL!),
  thighR: mirror(left.thighL!), shinR: mirror(left.shinL!), footR: mirror(left.footL!), toeR: mirror(left.toeL!),
} as Record<BoneName, V3>;

export const HEIGHT = 1.82;

/** Pose parameters (degrees unless noted). Anything missing is 0 = bind pose. */
export const SIDE_PARAMS = ["clav", "clavFwd", "shFlex", "shAbd", "shTwist", "elbow", "wrist", "hipFlex", "hipAbd", "hipTwist", "knee", "ankle", "toe"] as const;
export const CORE_PARAMS = [
  "rootX", "rootY", "rootZ",            // metres, hips offset (rootY < 0 = crouch)
  "pelvisFlex", "pelvisYaw", "pelvisRoll",
  "spineFlex", "spineYaw", "spineRoll",
  "chestFlex", "chestYaw", "chestRoll",
  "neckFlex", "headFlex", "headYaw", "headRoll",
] as const;
export type SideParam = typeof SIDE_PARAMS[number];
export type PoseParam = typeof CORE_PARAMS[number] | `${SideParam}L` | `${SideParam}R`;
export type Pose = Partial<Record<PoseParam, number>>;
export const ALL_PARAMS: PoseParam[] = [...CORE_PARAMS, ...SIDE_PARAMS.flatMap((p) => [`${p}L`, `${p}R`] as PoseParam[])];

/** Swap left and right (and negate lateral rotations): mirrored poses author gait cycles. */
export function mirrorPose(p: Pose): Pose {
  const out: Pose = {};
  for (const [k, v] of Object.entries(p) as [PoseParam, number][]) {
    if (k.endsWith("L") && SIDE_PARAMS.includes(k.slice(0, -1) as SideParam)) out[`${k.slice(0, -1)}R` as PoseParam] = v;
    else if (k.endsWith("R") && SIDE_PARAMS.includes(k.slice(0, -1) as SideParam)) out[`${k.slice(0, -1)}L` as PoseParam] = v;
    else if (/Yaw|Roll|rootX/.test(k)) out[k] = -v;
    else out[k] = v;
  }
  return out;
}

export function lerpPose(a: Pose, b: Pose, t: number): Pose {
  const out: Pose = {};
  for (const k of new Set([...Object.keys(a), ...Object.keys(b)]) as Set<PoseParam>) out[k] = (a[k] ?? 0) * (1 - t) + (b[k] ?? 0) * t;
  return out;
}

export function addPose(a: Pose, b: Pose, w = 1): Pose {
  const out: Pose = { ...a };
  for (const [k, v] of Object.entries(b) as [PoseParam, number][]) out[k] = (out[k] ?? 0) + v * w;
  return out;
}

const D = Math.PI / 180;
const e = new THREE.Euler();

/** Local rotation of every bone for a pose (order ZXY: twist, then flexion, then abduction). */
export function poseRotations(p: Pose, out: Map<BoneName, THREE.Quaternion>): void {
  const g = (k: PoseParam) => (p[k] ?? 0) * D;
  const set = (bone: BoneName, x: number, y: number, z: number) => {
    e.set(x, y, z, "ZXY");
    const dst = out.get(bone) ?? new THREE.Quaternion();
    dst.setFromEuler(e);
    out.set(bone, dst);
  };
  set("hips", g("pelvisFlex"), g("pelvisYaw"), -g("pelvisRoll"));
  set("spine", g("spineFlex"), g("spineYaw"), -g("spineRoll"));
  set("chest", g("chestFlex"), g("chestYaw"), -g("chestRoll"));
  set("neck", g("neckFlex"), 0, 0);
  set("head", g("headFlex"), g("headYaw"), -g("headRoll"));
  for (const [s, side] of [["L", 1], ["R", -1]] as const) {
    const sp = (k: SideParam) => g(`${k}${s}` as PoseParam);
    // clavicle points sideways: elevation about Z, protraction about Y
    set(`clavicle${s}`, 0, -side * sp("clavFwd"), side * sp("clav"));
    // limbs hang down: flexion forward = -X, abduction outwards = +side Z
    set(`upperArm${s}`, -sp("shFlex"), side * sp("shTwist"), side * sp("shAbd"));
    set(`foreArm${s}`, -sp("elbow"), 0, 0);
    set(`hand${s}`, sp("wrist"), 0, 0);
    set(`thigh${s}`, -sp("hipFlex"), side * sp("hipTwist"), side * sp("hipAbd"));
    set(`shin${s}`, sp("knee"), 0, 0);
    set(`foot${s}`, sp("ankle"), 0, 0);       // + plantarflexion (toes down)
    set(`toe${s}`, -sp("toe"), 0, 0);         // + toe extension (toes up)
  }
}

export type Rig = { root: THREE.Bone; bones: Record<BoneName, THREE.Bone>; skeleton: THREE.Skeleton };

export function createSkeleton(): Rig {
  const bones = {} as Record<BoneName, THREE.Bone>;
  for (const name of BONES) {
    const bone = new THREE.Bone();
    bone.name = name;
    const parent = PARENT[name];
    const [x, y, z] = JOINT[name];
    if (parent) { const [px, py, pz] = JOINT[parent]; bone.position.set(x - px, y - py, z - pz); } else bone.position.set(x, y, z);
    bones[name] = bone;
  }
  for (const name of BONES) { const parent = PARENT[name]; if (parent) bones[parent].add(bones[name]); }
  return { root: bones.hips, bones, skeleton: new THREE.Skeleton(BONES.map((n) => bones[n])) };
}

const scratch = new Map<BoneName, THREE.Quaternion>();
/** Write a pose onto a rig (hips translation from rootX/Y/Z on top of the bind offset). */
export function applyPose(rig: Rig, p: Pose): void {
  poseRotations(p, scratch);
  for (const name of BONES) rig.bones[name].quaternion.copy(scratch.get(name)!);
  const [x, y, z] = JOINT.hips;
  rig.root.position.set(x + (p.rootX ?? 0), y + (p.rootY ?? 0), z + (p.rootZ ?? 0));
}

