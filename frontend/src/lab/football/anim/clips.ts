import * as THREE from "three";
import { ALL_PARAMS, applyPose, BONES, mirrorPose, poseRotations, type BoneName, type Pose, type PoseParam } from "../athlete/rig";
import { contactPoints, fkRig, groundOffset, lowestWithId, worldOf } from "./fk";

/**
 * Football animation library (original, authored in code as anatomical keyframes).
 *
 * Every clip is a list of keys (normalised time u in [0, 1]) with a pose in degrees and a
 * grounding rule: `ground: "L" | "R" | "lowest"` puts that foot on the grass by forward
 * kinematics, `lift` raises the body above it (flight phases, jumps). Gait cycles are
 * authored for the left-foot half and mirrored. Sampling is Catmull-Rom per parameter;
 * `bakeClip` produces a THREE.AnimationClip (quaternions per bone + hips position) at 30 fps
 * for AnimationMixer / GLB export.
 *
 * Metadata (`ClipMeta`) is the contract for integration with the official engine:
 * contact time and body part, plant, recovery, measured stride and foot contact windows.
 */
export type Ground = "L" | "R" | "lowest" | "none";
export type Key = { u: number; p: Pose; ground?: Ground; lift?: number };
export type ContactPart = "footL" | "footR" | "head" | "chest" | "hands" | "handL" | "handR" | "thighR";
export type ClipMeta = {
  name: string;
  label: string;
  category: "locomotion" | "ball" | "keeper" | "duel" | "reaction" | "celebration";
  duration: number;            // seconds at time scale 1
  loop: boolean;
  contact?: { u: number; time: number; part: ContactPart };   // the frame the body touches the ball
  plant?: { time: number; foot: "L" | "R" };                  // support foot planted
  recovery?: number;           // seconds after contact before another action can blend in
  speed?: [number, number];    // root speed (m/s) the clip is authored for
  direction: "forward" | "lateral" | "backward" | "any" | "in-place";
  rootDriven?: boolean;        // translation/rotation comes from the physics (keeper dives)
  stride?: number;             // metres per cycle (measured by FK, see measureStride)
  stance?: { L: [number, number]; R: [number, number] };     // foot contact windows (u)
  notes?: string;
};
export type ClipDef = { meta: ClipMeta; keys: Key[] };

// ------------------------------------------------------------------ authoring helpers
const P = (...parts: Pose[]): Pose => Object.assign({}, ...parts);
/** Ankle angle that keeps a foot flat on the ground given hip/knee/pelvis flexion. */
function flat(p: Pose, side: "L" | "R", extra = 0): Pose {
  const hip = p[`hipFlex${side}`] ?? 0, knee = p[`knee${side}`] ?? 0, pelvis = p.pelvisFlex ?? 0;
  return { ...p, [`ankle${side}`]: hip - pelvis - knee + extra };
}
const both = (p: Pose) => flat(flat(p, "L"), "R");
/** Mirror a half-cycle (left-foot half) into a full gait cycle. */
function gait(half: Key[]): Key[] {
  const out = [...half];
  for (const k of half) out.push({ u: k.u + 0.5, p: mirrorPose(k.p), ground: k.ground === "L" ? "R" : k.ground === "R" ? "L" : k.ground, lift: k.lift });
  return out.sort((a, b) => a.u - b.u);
}
const secs = (keys: { t: number; p: Pose; ground?: Ground; lift?: number }[], duration: number): Key[] => keys.map((k) => ({ u: k.t / duration, p: k.p, ground: k.ground, lift: k.lift }));

const ARMS_RELAXED: Pose = { shAbdL: 11, shAbdR: 11, elbowL: 24, elbowR: 21, shFlexL: 5, shFlexR: 3, shTwistL: -12, shTwistR: -12, wristL: -6, wristR: -6, clavL: -3, clavR: -3 };
const ATHLETIC: Pose = both(P(ARMS_RELAXED, { pelvisFlex: 3, spineFlex: 4, chestFlex: 2, neckFlex: -3, headFlex: 1, hipFlexL: 9, hipFlexR: 7, kneeL: 13, kneeR: 11, hipAbdL: 3, hipAbdR: 3, hipTwistL: 6, hipTwistR: 6 }));

// ------------------------------------------------------------------ locomotion
const idle: ClipDef = {
  meta: { name: "idle", label: "Idle", category: "locomotion", duration: 3.2, loop: true, direction: "in-place", speed: [0, 0.3] },
  keys: [
    { u: 0, p: ATHLETIC, ground: "lowest" },
    { u: 0.5, p: P(ATHLETIC, both({ ...ATHLETIC, kneeL: 16, kneeR: 9, rootX: 0.012, pelvisRoll: 1.5, spineRoll: -1, chestFlex: 3.5, headYaw: 6, shAbdL: 10 })), ground: "lowest" },
    { u: 1, p: ATHLETIC, ground: "lowest" },
  ],
};

// Walk (~1.5 m/s). Phase 0 = left heel strike.
const walk: ClipDef = {
  meta: { name: "walk", label: "Caminhada", category: "locomotion", duration: 1.05, loop: true, direction: "forward", speed: [0.6, 2.2], stance: { L: [0, 0.6], R: [0.5, 1.1] } },
  keys: gait([
    { u: 0, ground: "lowest", p: P({ spineFlex: 3, pelvisYaw: -4, chestYaw: 5, hipFlexL: 24, kneeL: 3, ankleL: -10, hipFlexR: -12, kneeR: 12, ankleR: 14, toeR: 18, shFlexL: -16, elbowL: 16, shFlexR: 18, elbowR: 26, shAbdL: 8, shAbdR: 8, headFlex: 2 }) },
    { u: 0.12, ground: "lowest", p: P(flat({ hipFlexL: 18, kneeL: 15 }, "L"), { spineFlex: 3, pelvisYaw: -2, chestYaw: 3, hipFlexR: -14, kneeR: 38, ankleR: 22, toeR: 10, shFlexL: -10, shFlexR: 12, elbowL: 16, elbowR: 24, shAbdL: 8, shAbdR: 8, pelvisRoll: -2 }) },
    { u: 0.27, ground: "lowest", p: P(flat({ hipFlexL: 2, kneeL: 6 }, "L"), { spineFlex: 3, pelvisYaw: 0, hipFlexR: 22, kneeR: 58, ankleR: -2, shFlexL: 0, shFlexR: 0, elbowL: 18, elbowR: 18, shAbdL: 8, shAbdR: 8, pelvisRoll: -3, rootX: 0.015 }) },
    { u: 0.42, ground: "lowest", p: P({ spineFlex: 3, pelvisYaw: 3, chestYaw: -3, hipFlexL: -10, kneeL: 6, ankleL: 8, hipFlexR: 28, kneeR: 16, ankleR: -6, shFlexL: 12, elbowL: 24, shFlexR: -12, elbowR: 16, shAbdL: 8, shAbdR: 8, pelvisRoll: -1, rootX: 0.008 }) },
  ]),
};

// Jog/run (~4 m/s). Stance ~26 % of the cycle, short flight.
const run: ClipDef = {
  meta: { name: "run", label: "Corrida", category: "locomotion", duration: 0.66, loop: true, direction: "forward", speed: [2.5, 6], stance: { L: [0, 0.26], R: [0.5, 0.76] } },
  keys: gait([
    { u: 0, ground: "L", p: P({ pelvisFlex: 4, spineFlex: 8, chestFlex: 2, neckFlex: -6, pelvisYaw: -7, chestYaw: 10, hipFlexL: 28, kneeL: 16, ankleL: -6, hipFlexR: -12, kneeR: 72, ankleR: 22, shFlexL: -34, elbowL: 72, shFlexR: 38, elbowR: 92, shAbdL: 12, shAbdR: 12 }) },
    { u: 0.12, ground: "L", p: P(flat({ hipFlexL: 6, kneeL: 40, pelvisFlex: 4 }, "L"), { pelvisFlex: 4, spineFlex: 9, chestFlex: 2, neckFlex: -6, pelvisYaw: -1, chestYaw: 2, hipFlexR: 32, kneeR: 108, ankleR: 12, shFlexL: -8, elbowL: 82, shFlexR: 10, elbowR: 88, shAbdL: 12, shAbdR: 12, pelvisRoll: -3 }) },
    { u: 0.25, ground: "L", p: P({ pelvisFlex: 4, spineFlex: 9, chestFlex: 2, neckFlex: -6, pelvisYaw: 6, chestYaw: -9, hipFlexL: -20, kneeL: 20, ankleL: 32, toeL: 25, hipFlexR: 58, kneeR: 92, ankleR: 2, shFlexL: 36, elbowL: 90, shFlexR: -32, elbowR: 72, shAbdL: 12, shAbdR: 12 }) },
    { u: 0.38, ground: "lowest", lift: 0.07, p: P({ pelvisFlex: 4, spineFlex: 9, chestFlex: 2, neckFlex: -6, pelvisYaw: 4, chestYaw: -6, hipFlexL: -14, kneeL: 62, ankleL: 26, hipFlexR: 44, kneeR: 44, ankleR: 2, shFlexL: 30, elbowL: 88, shFlexR: -30, elbowR: 74, shAbdL: 12, shAbdR: 12 }) },
  ]),
};

// Sprint (~8.5 m/s): more lean, high knee drive, big arm action, stance ~21 %.
const sprint: ClipDef = {
  meta: { name: "sprint", label: "Sprint", category: "locomotion", duration: 0.46, loop: true, direction: "forward", speed: [6, 9.5], stance: { L: [0, 0.21], R: [0.5, 0.71] } },
  keys: gait([
    { u: 0, ground: "L", p: P({ pelvisFlex: 7, spineFlex: 13, chestFlex: 3, neckFlex: -10, pelvisYaw: -11, chestYaw: 14, hipFlexL: 40, kneeL: 18, ankleL: -2, hipFlexR: -10, kneeR: 96, ankleR: 22, shFlexL: -55, elbowL: 80, shFlexR: 62, elbowR: 96, shAbdL: 10, shAbdR: 10 }) },
    { u: 0.1, ground: "L", p: P(flat({ hipFlexL: 14, kneeL: 42, pelvisFlex: 7 }, "L", 6), { pelvisFlex: 7, spineFlex: 13, chestFlex: 3, neckFlex: -10, pelvisYaw: -2, chestYaw: 3, hipFlexR: 46, kneeR: 128, ankleR: 10, shFlexL: -15, elbowL: 88, shFlexR: 18, elbowR: 92, shAbdL: 10, shAbdR: 10, pelvisRoll: -3 }) },
    { u: 0.21, ground: "L", p: P({ pelvisFlex: 7, spineFlex: 13, chestFlex: 3, neckFlex: -10, pelvisYaw: 11, chestYaw: -13, hipFlexL: -32, kneeL: 22, ankleL: 40, toeL: 32, hipFlexR: 80, kneeR: 100, ankleR: 0, shFlexL: 58, elbowL: 96, shFlexR: -52, elbowR: 78, shAbdL: 10, shAbdR: 10 }) },
    { u: 0.36, ground: "lowest", lift: 0.1, p: P({ pelvisFlex: 7, spineFlex: 13, chestFlex: 3, neckFlex: -10, pelvisYaw: 5, chestYaw: -7, hipFlexL: -10, kneeL: 92, ankleL: 24, hipFlexR: 62, kneeR: 56, ankleR: 0, shFlexL: 46, elbowL: 92, shFlexR: -45, elbowR: 80, shAbdL: 10, shAbdR: 10 }) },
  ]),
};

// Dribble: jog with shorter strides, head over the ball; the right foot touches the ball at u = 0.47.
const dribble: ClipDef = {
  meta: { name: "dribble", label: "Condução", category: "ball", duration: 0.72, loop: true, direction: "forward", speed: [2, 5.5], stance: { L: [0, 0.3], R: [0.5, 0.8] },
    contact: { u: 0.46, time: 0.33, part: "footR" }, notes: "Um toque por ciclo com o peito do pé direito (u≈0,46). A bola é empurrada pelo motor; a animação só marca o instante do toque." },
  keys: [
    { u: 0, ground: "L", p: P({ pelvisFlex: 4, spineFlex: 14, chestFlex: 4, neckFlex: 6, headFlex: 14, pelvisYaw: -5, chestYaw: 7, hipFlexL: 24, kneeL: 18, ankleL: -6, hipFlexR: -10, kneeR: 62, ankleR: 18, shFlexL: -24, elbowL: 62, shFlexR: 28, elbowR: 74, shAbdL: 20, shAbdR: 20 }) },
    { u: 0.14, ground: "L", p: P(flat({ hipFlexL: 4, kneeL: 36, pelvisFlex: 4 }, "L"), { pelvisFlex: 4, spineFlex: 14, chestFlex: 4, neckFlex: 6, headFlex: 14, hipFlexR: 26, kneeR: 92, ankleR: 14, shFlexL: -6, elbowL: 70, shFlexR: 8, elbowR: 72, shAbdL: 22, shAbdR: 22, pelvisRoll: -3 }) },
    { u: 0.3, ground: "L", p: P({ pelvisFlex: 4, spineFlex: 14, chestFlex: 4, neckFlex: 6, headFlex: 14, pelvisYaw: 5, chestYaw: -6, hipFlexL: -16, kneeL: 22, ankleL: 28, toeL: 20, hipFlexR: 34, kneeR: 64, ankleR: 22, shFlexL: 24, elbowL: 72, shFlexR: -22, elbowR: 62, shAbdL: 20, shAbdR: 20 }) },
    // touch: knee extends, toes pointed down and slightly in (laces / outside of the foot)
    { u: 0.46, ground: "lowest", lift: 0.03, p: P({ pelvisFlex: 4, spineFlex: 15, chestFlex: 4, neckFlex: 8, headFlex: 16, pelvisYaw: 6, chestYaw: -6, hipFlexL: -12, kneeL: 58, ankleL: 24, hipFlexR: 30, kneeR: 34, ankleR: 34, hipTwistR: -8, shFlexL: 22, elbowL: 74, shFlexR: -20, elbowR: 64, shAbdL: 22, shAbdR: 22 }) },
    { u: 0.5, ground: "R", p: P(mirrorPose({ pelvisFlex: 4, spineFlex: 14, chestFlex: 4, neckFlex: 6, headFlex: 14, pelvisYaw: -5, chestYaw: 7, hipFlexL: 22, kneeL: 18, ankleL: -4, hipFlexR: -10, kneeR: 62, ankleR: 18, shFlexL: -24, elbowL: 62, shFlexR: 28, elbowR: 74, shAbdL: 20, shAbdR: 20 })) },
    { u: 0.64, ground: "R", p: mirrorPose(P(flat({ hipFlexL: 4, kneeL: 36, pelvisFlex: 4 }, "L"), { pelvisFlex: 4, spineFlex: 14, chestFlex: 4, neckFlex: 6, headFlex: 14, hipFlexR: 26, kneeR: 92, ankleR: 14, shFlexL: -6, elbowL: 70, shFlexR: 8, elbowR: 72, shAbdL: 22, shAbdR: 22, pelvisRoll: -3 })) },
    { u: 0.8, ground: "R", p: mirrorPose(P({ pelvisFlex: 4, spineFlex: 14, chestFlex: 4, neckFlex: 6, headFlex: 14, pelvisYaw: 5, chestYaw: -6, hipFlexL: -16, kneeL: 22, ankleL: 28, toeL: 20, hipFlexR: 34, kneeR: 64, ankleR: 10, shFlexL: 24, elbowL: 72, shFlexR: -22, elbowR: 62, shAbdL: 20, shAbdR: 20 })) },
    { u: 0.92, ground: "lowest", lift: 0.04, p: mirrorPose(P({ pelvisFlex: 4, spineFlex: 14, chestFlex: 4, neckFlex: 6, headFlex: 14, pelvisYaw: 3, chestYaw: -4, hipFlexL: -10, kneeL: 64, ankleL: 22, hipFlexR: 36, kneeR: 30, ankleR: -4, shFlexL: 22, elbowL: 72, shFlexR: -22, elbowR: 64, shAbdL: 20, shAbdR: 20 })) },
  ],
};

// Braking from a run: long last step, lean back, absorb, settle into the athletic stance.
const brake: ClipDef = {
  meta: { name: "brake", label: "Frenagem", category: "locomotion", duration: 0.8, loop: false, direction: "forward", speed: [6, 0], recovery: 0.2,
    notes: "A raiz desacelera pelo motor (~6 → 0 m/s em 0,6 s ≈ 10 m/s²). O passo longo do pé direito marca o início da frenagem." },
  keys: secs([
    { t: 0, ground: "L", p: run.keys[0].p },
    { t: 0.16, ground: "R", p: P(flat({ hipFlexR: 42, kneeR: 22, pelvisFlex: -2 }, "R", -8), { pelvisFlex: -2, spineFlex: -6, chestFlex: -2, neckFlex: 2, hipFlexL: -18, kneeL: 40, ankleL: 24, toeL: 20, shFlexL: 20, shAbdL: 30, elbowL: 60, shFlexR: -10, shAbdR: 28, elbowR: 50 }) },
    { t: 0.34, ground: "lowest", p: both(P({ pelvisFlex: 2, spineFlex: -2, hipFlexR: 30, kneeR: 42, hipFlexL: 6, kneeL: 34, shFlexL: 14, shAbdL: 26, elbowL: 50, shFlexR: 4, shAbdR: 24, elbowR: 44, rootZ: 0.04 })) },
    { t: 0.55, ground: "lowest", p: both(P({ pelvisFlex: 4, spineFlex: 8, hipFlexR: 22, kneeR: 34, hipFlexL: 18, kneeL: 30, hipAbdL: 6, hipAbdR: 6, shFlexL: 8, shAbdL: 18, elbowL: 40, shFlexR: 8, shAbdR: 18, elbowR: 40 })) },
    { t: 0.8, ground: "lowest", p: ATHLETIC },
  ], 0.8),
};

// 45-90° cut to the athlete's left off the right foot (plant wide, lean in, push off).
const cut: ClipDef = {
  meta: { name: "cut", label: "Mudança de direção", category: "locomotion", duration: 0.62, loop: false, direction: "lateral", speed: [3, 7], plant: { time: 0.14, foot: "R" }, recovery: 0.18,
    notes: "Plantar o pé direito aberto, inclinar o tronco para dentro da curva e girar a pélvis para a nova direção. A raiz faz a curva pelo motor." },
  keys: secs([
    { t: 0, ground: "L", p: run.keys[0].p },
    { t: 0.14, ground: "R", p: P(flat({ hipFlexR: 18, kneeR: 46, pelvisFlex: 4 }, "R"), { pelvisFlex: 4, hipAbdR: 26, hipTwistR: 10, spineFlex: 10, spineRoll: 16, pelvisRoll: 10, chestRoll: 6, pelvisYaw: 18, chestYaw: 22, headYaw: 30, hipFlexL: 28, kneeL: 70, hipAbdL: 8, shAbdR: 40, shFlexR: -10, elbowR: 60, shFlexL: 30, elbowL: 80, shAbdL: 14, rootX: -0.04 }) },
    { t: 0.3, ground: "R", p: P({ pelvisFlex: 6, hipAbdR: 14, hipFlexR: -18, kneeR: 22, ankleR: 34, toeR: 25, spineFlex: 12, spineRoll: 10, pelvisRoll: 4, pelvisYaw: 36, chestYaw: 30, headYaw: 30, hipFlexL: 50, kneeL: 80, hipAbdL: 14, shFlexR: 40, elbowR: 88, shFlexL: -36, elbowL: 70, shAbdR: 14, shAbdL: 14 }) },
    { t: 0.46, ground: "L", lift: 0.05, p: P({ pelvisFlex: 5, spineFlex: 10, pelvisYaw: 45, chestYaw: 42, headYaw: 40, hipFlexL: 34, kneeL: 30, hipFlexR: -12, kneeR: 70, ankleR: 22, shFlexL: -30, elbowL: 72, shFlexR: 34, elbowR: 88, shAbdL: 12, shAbdR: 12 }) },
    { t: 0.62, ground: "L", p: P(run.keys[0].p, { pelvisYaw: 38, chestYaw: 52, headYaw: 45 }) },
  ], 0.62),
};

// ------------------------------------------------------------------ ball actions (right foot; mirror for left)
const approach = run.keys[0].p;
function kick(name: string, label: string, d: number, o: { back: number; knee: number; contact: number; follow: number; lean: number; twist: number; ankle: number; across?: number; tc: number; notes: string; part?: ContactPart }): ClipDef {
  const tb = o.tc * 0.55;
  return {
    meta: { name, label, category: "ball", duration: d, loop: false, direction: "forward", speed: [0, 4], contact: { u: o.tc / d, time: o.tc, part: o.part ?? "footR" }, plant: { time: tb, foot: "L" }, recovery: Math.max(0.2, d - o.tc - 0.15), notes: o.notes },
    keys: secs([
      { t: 0, ground: "L", p: P(approach, { headFlex: 10 }) },
      // plant + backswing: support foot beside the ball, kicking leg cocked
      { t: tb, ground: "L", p: P(flat({ hipFlexL: 14, kneeL: 30, pelvisFlex: 4 }, "L"), { pelvisFlex: 4, spineFlex: 8, spineRoll: 9, chestRoll: 4, neckFlex: 6, headFlex: 14, pelvisYaw: -18 + o.twist * 0.2, chestYaw: 12, hipFlexR: -o.back, kneeR: o.knee, ankleR: o.ankle, hipTwistR: o.twist, shAbdL: 62, shFlexL: 24, elbowL: 30, shFlexR: -30, shAbdR: 30, elbowR: 40, rootX: 0.03 }) },
      // contact: knee snaps through, foot locked, body over the ball
      { t: o.tc, ground: "L", p: P(flat({ hipFlexL: 6, kneeL: 26, pelvisFlex: 4 }, "L", 4), { pelvisFlex: 4, spineFlex: 12 + o.lean, spineRoll: 7, neckFlex: 8, headFlex: 16, pelvisYaw: 12, chestYaw: -6, hipFlexR: o.contact, kneeR: o.knee * 0.28, ankleR: o.ankle, hipTwistR: o.twist, hipAbdR: -(o.across ?? 0) * 0.3, shAbdL: 54, shFlexL: 38, elbowL: 34, shFlexR: -20, shAbdR: 34, elbowR: 36, rootX: 0.03 }) },
      // follow-through: leg continues up/across, support foot rises onto the toes
      { t: o.tc + 0.16, ground: "L", p: P({ pelvisFlex: 2, spineFlex: 4 + o.lean * 0.5, spineRoll: 4, neckFlex: 4, headFlex: 8, pelvisYaw: 22, chestYaw: -10, hipFlexL: -6, kneeL: 22, ankleL: 30, toeL: 25, hipFlexR: o.follow, kneeR: 22, ankleR: o.ankle * 0.8, hipTwistR: o.twist * 0.6, hipAbdR: -(o.across ?? 0), shAbdL: 50, shFlexL: 30, elbowL: 40, shFlexR: 10, shAbdR: 40, elbowR: 40 }) },
      // land on the kicking foot and recover
      { t: o.tc + 0.34, ground: "R", p: P(flat({ hipFlexR: 22, kneeR: 28, pelvisFlex: 4 }, "R"), { pelvisFlex: 4, spineFlex: 8, pelvisYaw: 8, hipFlexL: -14, kneeL: 46, ankleL: 22, shFlexL: 10, shAbdL: 30, elbowL: 50, shFlexR: -10, shAbdR: 24, elbowR: 50, rootZ: 0.08 }) },
      { t: d, ground: "lowest", p: P(ATHLETIC, { rootZ: 0.1 }) },
    ], d),
  };
}
const shot = kick("shot", "Chute", 0.95, { back: 38, knee: 108, contact: 22, follow: 82, lean: 2, twist: 0, ankle: 42, tc: 0.3, notes: "Chute de peito do pé. Velocidade do pé no contato medida por FK (ver tabela do Animation Lab)." });
const passShort = kick("pass_short", "Passe curto", 0.7, { back: 22, knee: 58, contact: 18, follow: 36, lean: 0, twist: 42, ankle: -6, tc: 0.24, notes: "Parte interna: quadril em rotação externa (~42°), tornozelo travado, pouca preparação." });
const passLong = kick("pass_long", "Passe longo", 0.95, { back: 34, knee: 100, contact: 26, follow: 92, lean: -12, twist: 14, ankle: 30, tc: 0.32, notes: "Lançamento: tronco inclinado para trás no contato para levantar a bola; contato abaixo do centro." });
const cross = kick("cross", "Cruzamento", 0.95, { back: 30, knee: 98, contact: 24, follow: 70, lean: -8, twist: 24, ankle: 34, across: 26, tc: 0.32, notes: "Contato com o peito/parte interna e finalização cruzando o corpo (adução), gerando curva." });
const firstTime = kick("first_time", "Chute de primeira", 0.7, { back: 26, knee: 86, contact: 20, follow: 70, lean: 4, twist: 0, ankle: 40, tc: 0.18, notes: "Sem domínio: preparação curta (0,1 s) porque a bola chega em movimento." });

const receive: ClipDef = {
  meta: { name: "receive", label: "Recepção", category: "ball", duration: 0.62, loop: false, direction: "any", speed: [0, 4], contact: { u: 0.26 / 0.62, time: 0.26, part: "footR" }, recovery: 0.2,
    notes: "Parte interna oferecida à frente e recolhida no contato (amortecimento): a bola perde velocidade em vez de quicar." },
  keys: secs([
    { t: 0, ground: "lowest", p: ATHLETIC },
    { t: 0.16, ground: "L", p: P(flat({ hipFlexL: 12, kneeL: 26, pelvisFlex: 3 }, "L"), { pelvisFlex: 3, spineFlex: 10, headFlex: 18, neckFlex: 8, hipFlexR: 28, kneeR: 22, hipTwistR: 46, ankleR: -8, shAbdL: 30, shAbdR: 30, elbowL: 30, elbowR: 30 }) },
    { t: 0.26, ground: "L", p: P(flat({ hipFlexL: 12, kneeL: 28, pelvisFlex: 3 }, "L"), { pelvisFlex: 3, spineFlex: 11, headFlex: 20, neckFlex: 8, hipFlexR: 14, kneeR: 26, hipTwistR: 44, ankleR: -6, shAbdL: 32, shAbdR: 32, elbowL: 30, elbowR: 30 }) },
    { t: 0.42, ground: "lowest", p: both(P({ pelvisFlex: 3, spineFlex: 8, headFlex: 14, hipFlexL: 12, kneeL: 24, hipFlexR: 2, kneeR: 16, hipTwistR: 20, shAbdL: 22, shAbdR: 22, elbowL: 24, elbowR: 24 })) },
    { t: 0.62, ground: "lowest", p: ATHLETIC },
  ], 0.62),
};

const chestControl: ClipDef = {
  meta: { name: "chest_control", label: "Domínio de peito", category: "ball", duration: 0.9, loop: false, direction: "in-place", contact: { u: 0.3 / 0.9, time: 0.3, part: "chest" }, recovery: 0.35,
    notes: "Tronco recua e o peito 'abre' para a bola; logo depois o tronco flexiona e a bola cai à frente dos pés." },
  keys: secs([
    { t: 0, ground: "lowest", p: ATHLETIC },
    { t: 0.22, ground: "lowest", p: both(P({ pelvisFlex: -4, spineFlex: -14, chestFlex: -10, neckFlex: 10, headFlex: 18, hipFlexL: 6, kneeL: 22, hipFlexR: 6, kneeR: 22, hipAbdL: 6, hipAbdR: 6, shAbdL: 58, shAbdR: 58, shFlexL: 10, shFlexR: 10, elbowL: 40, elbowR: 40, clavL: 8, clavR: 8 })) },
    { t: 0.3, ground: "lowest", p: both(P({ pelvisFlex: -4, spineFlex: -16, chestFlex: -8, neckFlex: 12, headFlex: 22, hipFlexL: 6, kneeL: 26, hipFlexR: 6, kneeR: 26, hipAbdL: 6, hipAbdR: 6, shAbdL: 56, shAbdR: 56, shFlexL: 6, shFlexR: 6, elbowL: 46, elbowR: 46, rootZ: -0.02 })) },
    { t: 0.55, ground: "lowest", p: both(P({ pelvisFlex: 4, spineFlex: 14, chestFlex: 6, neckFlex: 10, headFlex: 20, hipFlexL: 14, kneeL: 30, hipFlexR: 14, kneeR: 30, hipAbdL: 5, hipAbdR: 5, shAbdL: 30, shAbdR: 30, elbowL: 34, elbowR: 34 })) },
    { t: 0.9, ground: "lowest", p: ATHLETIC },
  ], 0.9),
};

const header: ClipDef = {
  meta: { name: "header", label: "Cabeceio", category: "ball", duration: 1.0, loop: false, direction: "in-place", contact: { u: 0.46, time: 0.46, part: "head" }, recovery: 0.4,
    notes: "Impulsão com os dois pés (0,22 s), arco do tronco para trás no ápice e golpe da cabeça para a frente no contato." },
  keys: secs([
    { t: 0, ground: "lowest", p: ATHLETIC },
    { t: 0.18, ground: "lowest", p: both(P({ pelvisFlex: 8, spineFlex: 22, neckFlex: -6, hipFlexL: 52, kneeL: 72, hipFlexR: 52, kneeR: 72, shFlexL: -40, shFlexR: -40, elbowL: 30, elbowR: 30, shAbdL: 14, shAbdR: 14 })) },
    { t: 0.28, ground: "lowest", lift: 0.12, p: P({ pelvisFlex: 2, spineFlex: 2, hipFlexL: -4, kneeL: 6, ankleL: 38, toeL: 10, hipFlexR: -4, kneeR: 6, ankleR: 38, toeR: 10, shFlexL: 90, shFlexR: 90, shAbdL: 28, shAbdR: 28, elbowL: 50, elbowR: 50, headFlex: -10 }) },
    { t: 0.4, ground: "lowest", lift: 0.42, p: P({ pelvisFlex: -6, spineFlex: -18, chestFlex: -8, neckFlex: -12, headFlex: -16, hipFlexL: 20, kneeL: 62, ankleL: 30, hipFlexR: 8, kneeR: 74, ankleR: 30, shFlexL: 70, shFlexR: 70, shAbdL: 60, shAbdR: 60, elbowL: 60, elbowR: 60 }) },
    { t: 0.46, ground: "lowest", lift: 0.44, p: P({ pelvisFlex: 4, spineFlex: 16, chestFlex: 8, neckFlex: 10, headFlex: 18, hipFlexL: 30, kneeL: 50, ankleL: 30, hipFlexR: 16, kneeR: 56, ankleR: 30, shFlexL: 30, shFlexR: 30, shAbdL: 50, shAbdR: 50, elbowL: 70, elbowR: 70 }) },
    { t: 0.66, ground: "lowest", lift: 0.03, p: P({ pelvisFlex: 4, spineFlex: 10, hipFlexL: 24, kneeL: 30, ankleL: 20, hipFlexR: 18, kneeR: 28, ankleR: 22, shFlexL: 20, shFlexR: 20, shAbdL: 40, shAbdR: 40, elbowL: 50, elbowR: 50 }) },
    { t: 0.76, ground: "lowest", p: both(P({ pelvisFlex: 6, spineFlex: 16, hipFlexL: 40, kneeL: 62, hipFlexR: 40, kneeR: 62, shFlexL: 20, shFlexR: 20, shAbdL: 30, shAbdR: 30, elbowL: 40, elbowR: 40 })) },
    { t: 1.0, ground: "lowest", p: ATHLETIC },
  ], 1.0),
};

const slideTackle: ClipDef = {
  meta: { name: "slide_tackle", label: "Desarme (carrinho)", category: "duel", duration: 1.5, loop: false, direction: "forward", speed: [3, 7], contact: { u: 0.4 / 1.5, time: 0.4, part: "footL" }, recovery: 0.8,
    notes: "Desce pelo lado direito (quadril e coxa no chão), perna esquerda estendida na bola. A raiz desliza pelo motor (~2 m)." },
  keys: secs([
    { t: 0, ground: "L", p: run.keys[0].p },
    { t: 0.15, ground: "R", p: P(flat({ hipFlexR: 20, kneeR: 50, pelvisFlex: 4 }, "R"), { pelvisFlex: 4, spineFlex: 6, hipFlexL: 50, kneeL: 30, pelvisRoll: 8, spineRoll: -6, shAbdL: 40, shAbdR: 50, shFlexR: -20, elbowL: 50, elbowR: 30 }) },
    { t: 0.32, ground: "lowest", p: P({ pelvisFlex: -38, pelvisRoll: 30, spineFlex: 22, spineRoll: -14, chestFlex: 8, neckFlex: 10, headFlex: 14, hipFlexL: 52, kneeL: 6, ankleL: -6, hipFlexR: 30, kneeR: 112, hipAbdR: 14, ankleR: 20, shAbdR: 60, shFlexR: -40, elbowR: 10, shAbdL: 50, shFlexL: 40, elbowL: 50 }) },
    { t: 0.4, ground: "lowest", p: P({ pelvisFlex: -48, pelvisRoll: 34, spineFlex: 30, spineRoll: -16, chestFlex: 8, neckFlex: 12, headFlex: 14, hipFlexL: 62, kneeL: 4, ankleL: -10, hipFlexR: 38, kneeR: 116, hipAbdR: 14, ankleR: 20, shAbdR: 66, shFlexR: -44, elbowR: 8, shAbdL: 46, shFlexL: 46, elbowL: 56 }) },
    { t: 0.85, ground: "lowest", p: P({ pelvisFlex: -46, pelvisRoll: 32, spineFlex: 30, spineRoll: -14, chestFlex: 8, neckFlex: 10, headFlex: 12, hipFlexL: 50, kneeL: 20, ankleL: 0, hipFlexR: 40, kneeR: 112, hipAbdR: 14, ankleR: 20, shAbdR: 60, shFlexR: -40, elbowR: 14, shAbdL: 40, shFlexL: 30, elbowL: 56 }) },
    { t: 1.15, ground: "lowest", p: P({ pelvisFlex: 20, pelvisRoll: 10, spineFlex: 30, hipFlexL: 80, kneeL: 110, hipFlexR: 60, kneeR: 120, ankleR: -10, shFlexR: 40, shAbdR: 30, elbowR: 30, shFlexL: 40, shAbdL: 30, elbowL: 30 }) },
    { t: 1.5, ground: "lowest", p: ATHLETIC },
  ], 1.5),
};

const standTackle: ClipDef = {
  meta: { name: "stand_tackle", label: "Desarme (em pé)", category: "duel", duration: 0.7, loop: false, direction: "forward", speed: [0, 4], contact: { u: 0.26 / 0.7, time: 0.26, part: "footR" }, recovery: 0.3,
    notes: "Bote: avanço com a perna direita estendida e o corpo baixo, sem ir ao chão." },
  keys: secs([
    { t: 0, ground: "lowest", p: ATHLETIC },
    { t: 0.12, ground: "L", p: P(flat({ hipFlexL: 22, kneeL: 46, pelvisFlex: 6 }, "L"), { pelvisFlex: 6, spineFlex: 14, hipFlexR: 10, kneeR: 40, hipTwistR: 30, shAbdL: 30, shAbdR: 36, elbowL: 40, elbowR: 40 }) },
    { t: 0.26, ground: "L", p: P(flat({ hipFlexL: 30, kneeL: 62, pelvisFlex: 6 }, "L"), { pelvisFlex: 6, spineFlex: 20, spineRoll: 10, hipFlexR: 54, kneeR: 8, hipTwistR: 36, ankleR: -10, hipAbdR: 6, shAbdL: 46, shFlexL: 20, shAbdR: 40, shFlexR: -20, elbowL: 40, elbowR: 30, rootZ: 0.06 }) },
    { t: 0.45, ground: "lowest", p: both(P({ pelvisFlex: 6, spineFlex: 14, hipFlexL: 24, kneeL: 44, hipFlexR: 26, kneeR: 34, hipTwistR: 20, shAbdL: 30, shAbdR: 30, elbowL: 40, elbowR: 40, rootZ: 0.08 })) },
    { t: 0.7, ground: "lowest", p: P(ATHLETIC, { rootZ: 0.08 }) },
  ], 0.7),
};

const fall: ClipDef = {
  meta: { name: "fall", label: "Queda", category: "reaction", duration: 1.6, loop: false, direction: "forward", speed: [2, 7], recovery: 1.0,
    notes: "Tropeço: perde o apoio, mãos à frente para amortecer, rola de frente no chão e fica deitado." },
  keys: secs([
    { t: 0, ground: "L", p: run.keys[0].p },
    { t: 0.18, ground: "L", p: P({ pelvisFlex: 12, spineFlex: 26, chestFlex: 8, neckFlex: -14, hipFlexL: 10, kneeL: 30, ankleL: 10, hipFlexR: -30, kneeR: 40, ankleR: 30, shFlexL: 50, shFlexR: 30, shAbdL: 30, shAbdR: 30, elbowL: 20, elbowR: 30 }) },
    { t: 0.38, ground: "lowest", p: P({ pelvisFlex: 48, spineFlex: 24, chestFlex: 6, neckFlex: -26, headFlex: -10, hipFlexL: 30, kneeL: 40, ankleL: 30, hipFlexR: -6, kneeR: 50, ankleR: 30, shFlexL: 110, shFlexR: 100, shAbdL: 20, shAbdR: 20, elbowL: 30, elbowR: 30 }) },
    { t: 0.55, ground: "lowest", p: P({ pelvisFlex: 82, spineFlex: 6, chestFlex: 4, neckFlex: -30, headFlex: -14, hipFlexL: 6, kneeL: 20, ankleL: 40, hipFlexR: 0, kneeR: 30, ankleR: 40, shFlexL: 150, shFlexR: 140, shAbdL: 30, shAbdR: 30, elbowL: 60, elbowR: 60 }) },
    { t: 0.9, ground: "lowest", p: P({ pelvisFlex: 90, spineFlex: 0, chestFlex: 0, neckFlex: -30, headFlex: -10, headYaw: 30, hipFlexL: 0, kneeL: 10, ankleL: 50, hipFlexR: 0, kneeR: 40, hipAbdR: 10, ankleR: 50, shFlexL: 160, shFlexR: 90, shAbdL: 40, shAbdR: 60, elbowL: 80, elbowR: 90 }) },
    { t: 1.6, ground: "lowest", p: P({ pelvisFlex: 90, spineFlex: 0, neckFlex: -30, headFlex: -4, headYaw: 40, hipFlexL: 0, kneeL: 14, ankleL: 50, hipFlexR: 0, kneeR: 50, hipAbdR: 12, ankleR: 50, shFlexL: 160, shFlexR: 80, shAbdL: 40, shAbdR: 70, elbowL: 80, elbowR: 100 }) },
  ], 1.6),
};

const celebrate: ClipDef = {
  meta: { name: "celebrate", label: "Comemoração", category: "celebration", duration: 2.0, loop: true, direction: "in-place",
    notes: "Salto com socos no ar alternados. Sem gestos de marcas/atletas reais." },
  keys: secs([
    { t: 0, ground: "lowest", p: both(P({ pelvisFlex: 6, spineFlex: 10, hipFlexL: 34, kneeL: 56, hipFlexR: 34, kneeR: 56, shFlexL: 30, shFlexR: 30, shAbdL: 30, shAbdR: 30, elbowL: 120, elbowR: 120 })) },
    { t: 0.28, ground: "lowest", lift: 0.32, p: P({ pelvisFlex: -2, spineFlex: -14, chestFlex: -8, neckFlex: -10, headFlex: -14, hipFlexL: 30, kneeL: 70, ankleL: 30, hipFlexR: 4, kneeR: 40, ankleR: 30, shFlexL: 170, shAbdL: 20, elbowL: 10, shFlexR: 60, shAbdR: 60, elbowR: 110 }) },
    { t: 0.55, ground: "lowest", p: both(P({ pelvisFlex: 6, spineFlex: 12, hipFlexL: 30, kneeL: 48, hipFlexR: 30, kneeR: 48, shFlexL: 50, shFlexR: 40, shAbdL: 30, shAbdR: 40, elbowL: 120, elbowR: 110 })) },
    { t: 0.85, ground: "lowest", p: both(P({ pelvisFlex: 2, spineFlex: -6, chestFlex: -6, hipFlexL: 10, kneeL: 16, hipFlexR: 10, kneeR: 16, shFlexL: 70, shAbdL: 70, elbowL: 115, shFlexR: 170, shAbdR: 20, elbowR: 10, headFlex: -18 })) },
    { t: 1.15, ground: "lowest", p: both(P({ pelvisFlex: 2, spineFlex: -6, hipFlexL: 10, kneeL: 16, hipFlexR: 10, kneeR: 16, shFlexL: 70, shAbdL: 70, elbowL: 125, shFlexR: 120, shAbdR: 40, elbowR: 100, headFlex: -12 })) },
    { t: 1.45, ground: "lowest", p: both(P({ pelvisFlex: 2, spineFlex: -6, hipFlexL: 10, kneeL: 16, hipFlexR: 10, kneeR: 16, shFlexL: 70, shAbdL: 70, elbowL: 115, shFlexR: 170, shAbdR: 20, elbowR: 10, headFlex: -18 })) },
    { t: 2.0, ground: "lowest", p: both(P({ pelvisFlex: 6, spineFlex: 10, hipFlexL: 34, kneeL: 56, hipFlexR: 34, kneeR: 56, shFlexL: 30, shFlexR: 30, shAbdL: 30, shAbdR: 30, elbowL: 120, elbowR: 120 })) },
  ], 2.0),
};

// ------------------------------------------------------------------ goalkeeper
export const GK_READY_POSE: Pose = both(P({ pelvisFlex: 10, spineFlex: 16, chestFlex: 4, neckFlex: -14, headFlex: -2, hipFlexL: 34, kneeL: 42, hipFlexR: 34, kneeR: 42, hipAbdL: 11, hipAbdR: 11, hipTwistL: 8, hipTwistR: 8, shFlexL: 34, shFlexR: 34, shAbdL: 34, shAbdR: 34, elbowL: 62, elbowR: 62, wristL: -18, wristR: -18, shTwistL: 20, shTwistR: 20 }));
const gkReady: ClipDef = {
  meta: { name: "gk_ready", label: "GK: postura de espera", category: "keeper", duration: 1.2, loop: true, direction: "in-place",
    notes: "Base larga, joelhos a ~40°, peso na ponta dos pés, mãos à frente na altura da cintura com as palmas para a frente." },
  keys: [
    { u: 0, ground: "lowest", p: GK_READY_POSE },
    { u: 0.5, ground: "lowest", p: P(GK_READY_POSE, flat(flat({ ...GK_READY_POSE, kneeL: 46, kneeR: 46, ankleL: 0, ankleR: 0 }, "L", 6), "R", 6), { shFlexL: 36, shFlexR: 36 }) },
    { u: 1, ground: "lowest", p: GK_READY_POSE },
  ],
};
const gkSplit: ClipDef = {
  meta: { name: "gk_set", label: "GK: preparação (split step)", category: "keeper", duration: 0.3, loop: false, direction: "in-place",
    notes: "Pequeno salto no instante do chute adversário: o goleiro aterrissa carregado (joelhos ~50°) e pronto para empurrar para qualquer lado." },
  keys: secs([
    { t: 0, ground: "lowest", p: GK_READY_POSE },
    { t: 0.1, ground: "lowest", lift: 0.05, p: P(GK_READY_POSE, { kneeL: 30, kneeR: 30, ankleL: 20, ankleR: 20 }) },
    { t: 0.22, ground: "lowest", p: both(P(GK_READY_POSE, { kneeL: 52, kneeR: 52, hipFlexL: 40, hipFlexR: 40, hipAbdL: 13, hipAbdR: 13 })) },
    { t: 0.3, ground: "lowest", p: GK_READY_POSE },
  ], 0.3),
};
// Lateral shuffle to the keeper's left (+X). Feet never cross.
const gkShuffle: ClipDef = {
  meta: { name: "gk_shuffle", label: "GK: passos laterais", category: "keeper", duration: 0.46, loop: true, direction: "lateral", speed: [0.5, 3.4], stance: { L: [0.3, 1.0], R: [0, 0.6] },
    notes: "Passo lateral: pé esquerdo abre, o direito fecha sem cruzar. Ciclo medido por FK no eixo X." },
  keys: [
    { u: 0, ground: "lowest", p: both(P(GK_READY_POSE, { hipAbdL: 10, hipAbdR: 10 })) },
    { u: 0.25, ground: "R", p: P(both(P(GK_READY_POSE, { hipAbdR: 6 })), { hipAbdL: 26, kneeL: 30, ankleL: 0, rootX: 0.08, pelvisRoll: 2 }) },
    { u: 0.5, ground: "lowest", p: both(P(GK_READY_POSE, { hipAbdL: 18, hipAbdR: 16, rootX: 0.0 })) },
    { u: 0.75, ground: "L", p: P(both(P(GK_READY_POSE, { hipAbdL: 8 })), { hipAbdR: 2, kneeR: 34, rootX: -0.02, pelvisRoll: -2 }) },
    { u: 1, ground: "lowest", p: both(P(GK_READY_POSE, { hipAbdL: 10, hipAbdR: 10 })) },
  ],
};
/** Dive to the keeper's left; body SHAPE only (rootDriven): translation and roll come from the keeper physics. */
function gkDive(name: string, label: string, high: boolean): ClipDef {
  const armUp = high ? 172 : 150;
  return {
    meta: { name, label, category: "keeper", duration: 1.0, loop: false, direction: "lateral", rootDriven: true, contact: { u: 0.62, time: 0.62, part: "hands" },
      notes: "Normalizado pelo progresso do mergulho (u = 0 carga, 0,18 impulsão, 0,62 alcance máximo, 1 aterrissagem). A física do goleiro move a raiz e gira o corpo; o clip só dá a forma." },
    keys: [
      { u: 0, ground: "lowest", p: GK_READY_POSE },
      // load: step with the near (left) foot, sink on it
      { u: 0.12, ground: "L", p: P(flat({ hipFlexL: 46, kneeL: 64, pelvisFlex: 10 }, "L"), { pelvisFlex: 10, spineFlex: 18, spineRoll: 8, hipAbdL: 24, hipFlexR: 30, kneeR: 36, hipAbdR: 4, shFlexL: 40, shAbdL: 50, elbowL: 50, shFlexR: 40, shAbdR: 30, elbowR: 60, headYaw: 20 }) },
      // push-off: near leg drives, far leg swings up and across, arms start the reach
      { u: 0.24, ground: "L", p: P({ pelvisFlex: 4, spineFlex: 6, spineRoll: 12, chestRoll: 6, hipFlexL: -4, kneeL: 10, ankleL: 34, hipAbdL: 18, hipFlexR: 46, kneeR: 50, hipAbdR: 26, shAbdL: 120, shFlexL: 40, elbowL: 20, shAbdR: 30, shFlexR: 110, elbowR: 40, headYaw: 14 }) },
      // full stretch (contact window): arms overhead towards the ball, body long, top leg trailing
      { u: 0.62, ground: "none", p: P({ pelvisFlex: 0, spineFlex: 2, spineRoll: 10, chestRoll: 8, neckFlex: -4, headRoll: 10, hipFlexL: 6, kneeL: 22, ankleL: 20, hipAbdL: 4, hipFlexR: 18, kneeR: 34, hipAbdR: 18, ankleR: 20, shAbdL: armUp, shFlexL: 20, elbowL: 4, shAbdR: high ? 150 : 128, shFlexR: high ? 40 : 60, elbowR: 10, wristL: -10, wristR: -10 }) },
      // landing: forearm and hip take the impact, knees draw up, ball/arms pulled in
      { u: 0.85, ground: "none", p: P({ pelvisFlex: 6, spineFlex: 14, spineRoll: 6, neckFlex: 6, hipFlexL: 30, kneeL: 50, hipFlexR: 40, kneeR: 60, hipAbdR: 10, shAbdL: 120, shFlexL: 40, elbowL: 40, shAbdR: 80, shFlexR: 70, elbowR: 70 }) },
      { u: 1, ground: "none", p: P({ pelvisFlex: 10, spineFlex: 22, neckFlex: 10, hipFlexL: 50, kneeL: 80, hipFlexR: 56, kneeR: 86, shAbdL: 90, shFlexL: 50, elbowL: 80, shAbdR: 60, shFlexR: 70, elbowR: 90 }) },
    ],
  };
}
const gkDiveLow = gkDive("gk_dive_low", "GK: mergulho rasteiro", false);
const gkDiveHigh = gkDive("gk_dive_high", "GK: mergulho alto", true);
const gkCollapse: ClipDef = {
  meta: { name: "gk_collapse", label: "GK: defesa baixa (colapso)", category: "keeper", duration: 0.6, loop: false, direction: "lateral", rootDriven: true, contact: { u: 0.5, time: 0.3, part: "hands" },
    notes: "Bola rasteira perto do corpo: a perna do lado da bola cede e o goleiro cai de lado com as mãos no chão, sem impulsão." },
  keys: [
    { u: 0, ground: "lowest", p: GK_READY_POSE },
    { u: 0.3, ground: "R", p: P(flat({ hipFlexR: 60, kneeR: 100, pelvisFlex: 10 }, "R"), { pelvisFlex: 10, spineFlex: 26, spineRoll: 18, hipFlexL: 70, kneeL: 40, hipAbdL: 30, shAbdL: 70, shFlexL: 60, elbowL: 10, shAbdR: 30, shFlexR: 80, elbowR: 20, wristL: -20, wristR: -20, headYaw: 25 }) },
    { u: 0.5, ground: "none", p: P({ pelvisFlex: 12, spineFlex: 20, spineRoll: 14, hipFlexL: 40, kneeL: 30, hipAbdL: 16, hipFlexR: 50, kneeR: 90, shAbdL: 100, shFlexL: 30, elbowL: 6, shAbdR: 70, shFlexR: 60, elbowR: 14, wristL: -10, wristR: -10 }) },
    { u: 1, ground: "none", p: P({ pelvisFlex: 12, spineFlex: 26, neckFlex: 10, hipFlexL: 50, kneeL: 70, hipFlexR: 56, kneeR: 90, shAbdL: 70, shFlexL: 60, elbowL: 80, shAbdR: 50, shFlexR: 70, elbowR: 90 }) },
  ],
};
const gkJump: ClipDef = {
  meta: { name: "gk_jump", label: "GK: salto (bola alta)", category: "keeper", duration: 0.9, loop: false, direction: "in-place", contact: { u: 0.42, time: 0.38, part: "hands" }, recovery: 0.35,
    notes: "Impulsão com uma perna (joelho da outra para cima, proteção), braços estendidos acima da cabeça." },
  keys: secs([
    { t: 0, ground: "lowest", p: GK_READY_POSE },
    { t: 0.16, ground: "L", p: P(flat({ hipFlexL: 40, kneeL: 62, pelvisFlex: 6 }, "L"), { pelvisFlex: 6, spineFlex: 18, hipFlexR: 20, kneeR: 40, shFlexL: -30, shFlexR: -30, elbowL: 30, elbowR: 30 }) },
    { t: 0.3, ground: "L", lift: 0.3, p: P({ spineFlex: -4, hipFlexL: -2, kneeL: 8, ankleL: 40, hipFlexR: 80, kneeR: 100, shFlexL: 165, shFlexR: 165, shAbdL: 16, shAbdR: 16, elbowL: 12, elbowR: 12, headFlex: -24 }) },
    { t: 0.38, ground: "L", lift: 0.42, p: P({ spineFlex: -6, hipFlexL: 4, kneeL: 14, ankleL: 36, hipFlexR: 84, kneeR: 104, shFlexL: 175, shFlexR: 172, shAbdL: 12, shAbdR: 12, elbowL: 6, elbowR: 6, wristL: -24, wristR: -24, headFlex: -28 }) },
    { t: 0.58, ground: "lowest", lift: 0.05, p: P({ spineFlex: 12, hipFlexL: 20, kneeL: 30, ankleL: 20, hipFlexR: 40, kneeR: 60, shFlexL: 80, shFlexR: 80, elbowL: 100, elbowR: 100, shAbdL: 10, shAbdR: 10 }) },
    { t: 0.9, ground: "lowest", p: GK_READY_POSE },
  ], 0.9),
};
const gkCatch: ClipDef = {
  meta: { name: "gk_catch", label: "GK: encaixe", category: "keeper", duration: 0.6, loop: false, direction: "in-place", contact: { u: 0.2 / 0.6, time: 0.2, part: "hands" }, recovery: 0.3,
    notes: "Mãos em 'W' à frente do peito, recolhe a bola no contato (amortece) e protege com o corpo." },
  keys: secs([
    { t: 0, ground: "lowest", p: GK_READY_POSE },
    { t: 0.16, ground: "lowest", p: both(P(GK_READY_POSE, { spineFlex: 8, shFlexL: 72, shFlexR: 72, shAbdL: 18, shAbdR: 18, elbowL: 40, elbowR: 40, wristL: -30, wristR: -30, shTwistL: -10, shTwistR: -10 })) },
    { t: 0.24, ground: "lowest", p: both(P(GK_READY_POSE, { spineFlex: 14, shFlexL: 50, shFlexR: 50, shAbdL: 16, shAbdR: 16, elbowL: 90, elbowR: 90, wristL: -20, wristR: -20, rootZ: -0.04 })) },
    { t: 0.42, ground: "lowest", p: both(P(GK_READY_POSE, { spineFlex: 26, chestFlex: 10, kneeL: 50, kneeR: 50, shFlexL: 18, shFlexR: 18, shAbdL: 12, shAbdR: 12, elbowL: 125, elbowR: 125, rootZ: -0.06 })) },
    { t: 0.6, ground: "lowest", p: both(P({ spineFlex: 10, hipFlexL: 10, kneeL: 14, hipFlexR: 10, kneeR: 14, shFlexL: 26, shFlexR: 26, elbowL: 120, elbowR: 120, shAbdL: 10, shAbdR: 10 })) },
  ], 0.6),
};
const gkParry: ClipDef = {
  meta: { name: "gk_parry", label: "GK: espalmada", category: "keeper", duration: 0.5, loop: false, direction: "in-place", contact: { u: 0.36, time: 0.18, part: "handL" }, recovery: 0.25,
    notes: "Mão firme (punho estendido) empurra a bola para fora; usada como camada sobre o mergulho quando o contato não permite encaixe." },
  keys: secs([
    { t: 0, ground: "lowest", p: GK_READY_POSE },
    { t: 0.12, ground: "lowest", p: both(P(GK_READY_POSE, { shAbdL: 120, shFlexL: 50, elbowL: 30, wristL: 10, spineRoll: 10 })) },
    { t: 0.18, ground: "lowest", p: both(P(GK_READY_POSE, { shAbdL: 132, shFlexL: 40, elbowL: 4, wristL: -40, spineRoll: 14 })) },
    { t: 0.5, ground: "lowest", p: GK_READY_POSE },
  ], 0.5),
};
const gkGetUp: ClipDef = {
  meta: { name: "gk_getup", label: "GK: recuperação", category: "keeper", duration: 1.1, loop: false, direction: "in-place", rootDriven: true,
    notes: "Do chão de lado: apoia o antebraço, ajoelha e volta à postura de espera. A física decide quanto tempo o goleiro fica fora do lance (0,6–0,9 s)." },
  keys: [
    { u: 0, ground: "none", p: P({ pelvisFlex: 10, spineFlex: 22, neckFlex: 10, hipFlexL: 50, kneeL: 80, hipFlexR: 56, kneeR: 86, shAbdL: 90, shFlexL: 50, elbowL: 80, shAbdR: 60, shFlexR: 70, elbowR: 90 }) },
    { u: 0.45, ground: "lowest", p: P({ pelvisFlex: 6, spineFlex: 30, hipFlexL: 90, kneeL: 120, hipFlexR: 10, kneeR: 100, ankleR: 30, shFlexL: 40, shFlexR: 30, elbowL: 30, elbowR: 30, shAbdL: 30, shAbdR: 20 }) },
    { u: 0.75, ground: "lowest", p: both(P({ pelvisFlex: 8, spineFlex: 22, hipFlexL: 50, kneeL: 70, hipFlexR: 40, kneeR: 60, hipAbdL: 10, hipAbdR: 10, shFlexL: 30, shFlexR: 30, shAbdL: 30, shAbdR: 30, elbowL: 50, elbowR: 50 })) },
    { u: 1, ground: "lowest", p: GK_READY_POSE },
  ],
};
const gkThrow: ClipDef = {
  meta: { name: "gk_throw", label: "GK: reposição (mão)", category: "keeper", duration: 1.1, loop: false, direction: "forward", contact: { u: 0.56 / 1.1, time: 0.56, part: "handR" }, recovery: 0.3,
    notes: "Lançamento por cima: passo à frente com a perna esquerda, braço direito estendido atrás e soltura no ponto alto (u≈0,51)." },
  keys: secs([
    { t: 0, ground: "lowest", p: both(P({ spineFlex: 6, hipFlexL: 8, kneeL: 10, hipFlexR: 8, kneeR: 10, shFlexL: 30, shFlexR: 30, elbowL: 100, elbowR: 100, shAbdL: 12, shAbdR: 12 })) },
    { t: 0.3, ground: "R", p: P(flat({ hipFlexR: -6, kneeR: 20, pelvisFlex: 2 }, "R"), { pelvisFlex: 2, spineFlex: -8, spineYaw: -24, pelvisYaw: -20, hipFlexL: 30, kneeL: 20, shFlexR: -40, shAbdR: 80, elbowR: 10, shFlexL: 70, shAbdL: 20, elbowL: 20, headYaw: 30 }) },
    { t: 0.48, ground: "L", p: P(flat({ hipFlexL: 26, kneeL: 22, pelvisFlex: 4 }, "L"), { pelvisFlex: 4, spineFlex: 0, spineYaw: -10, pelvisYaw: -6, hipFlexR: -18, kneeR: 20, ankleR: 30, shFlexR: 110, shAbdR: 70, elbowR: 6, shFlexL: 30, shAbdL: 30, elbowL: 40 }) },
    { t: 0.56, ground: "L", p: P(flat({ hipFlexL: 26, kneeL: 26, pelvisFlex: 4 }, "L"), { pelvisFlex: 4, spineFlex: 10, spineYaw: 12, pelvisYaw: 8, hipFlexR: -24, kneeR: 26, ankleR: 34, shFlexR: 150, shAbdR: 20, elbowR: 4, shFlexL: 0, shAbdL: 30, elbowL: 40 }) },
    { t: 0.8, ground: "L", p: P(flat({ hipFlexL: 22, kneeL: 30, pelvisFlex: 4 }, "L"), { pelvisFlex: 4, spineFlex: 22, spineYaw: 20, pelvisYaw: 14, hipFlexR: -10, kneeR: 40, ankleR: 30, shFlexR: 40, shAbdR: 10, elbowR: 10, shFlexL: -20, shAbdL: 30, elbowL: 40 }) },
    { t: 1.1, ground: "lowest", p: ATHLETIC },
  ], 1.1),
};

export const CLIP_DEFS: ClipDef[] = [idle, walk, run, sprint, brake, cut, dribble, passShort, passLong, cross, shot, firstTime, receive, chestControl, header, standTackle, slideTackle, fall, celebrate,
  gkReady, gkSplit, gkShuffle, gkDiveLow, gkDiveHigh, gkCollapse, gkJump, gkCatch, gkParry, gkGetUp, gkThrow];
export const CLIPS: Record<string, ClipDef> = Object.fromEntries(CLIP_DEFS.map((c) => [c.meta.name, c]));

// ------------------------------------------------------------------ sampling
function catmullValue(keys: Key[], u: number, param: PoseParam | "lift", loop: boolean): number {
  const n = keys.length;
  const val = (i: number) => {
    const k = keys[(i + n) % n];
    return param === "lift" ? (k.lift ?? 0) : (k.p[param] ?? 0);
  };
  if (!loop) {
    if (u <= keys[0].u) return val(0);
    if (u >= keys[n - 1].u) return val(n - 1);
  }
  const uu = loop ? ((u % 1) + 1) % 1 : u;
  let i = n - 1;
  for (let k = 0; k < n; k += 1) if (keys[k].u <= uu) i = k;
  const j = i + 1;
  const ui = keys[i].u;
  const uj = j < n ? keys[j].u : (loop ? 1 + keys[0].u : 1);
  const t = Math.max(0, Math.min(1, (uu - ui) / Math.max(1e-6, uj - ui)));
  const at = (k: number) => (loop ? val(k) : val(Math.max(0, Math.min(n - 1, k))));
  const p0 = at(i - 1), p1 = at(i), p2 = at(j), p3 = at(j + 1);
  const t2 = t * t, t3 = t2 * t;
  return 0.5 * (2 * p1 + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t3);
}

function groundAt(keys: Key[], u: number, loop: boolean): Ground {
  const uu = loop ? ((u % 1) + 1) % 1 : Math.max(0, Math.min(1, u));
  let g: Ground = keys[0].ground ?? "lowest";
  for (const k of keys) if (k.u <= uu + 1e-6) g = k.ground ?? "lowest";
  return g;
}

const groundCache = new Map<string, Float32Array>();
const GROUND_SAMPLES = 120;
/** rootY correction per sample so the grounded foot touches the grass (precomputed once per clip). */
function groundTable(def: ClipDef): Float32Array {
  const hit = groundCache.get(def.meta.name);
  if (hit) return hit;
  const tab = new Float32Array(GROUND_SAMPLES + 1);
  for (let i = 0; i <= GROUND_SAMPLES; i += 1) {
    const u = i / GROUND_SAMPLES;
    const p = rawPose(def, u);
    const g = groundAt(def.keys, u, def.meta.loop);
    const lift = catmullValue(def.keys, u, "lift", def.meta.loop);
    tab[i] = g === "none" ? 0 : groundOffset(p, g) + lift;
  }
  // smooth the switch between grounding feet (avoid a pop when the support changes)
  const sm = new Float32Array(tab.length);
  for (let i = 0; i <= GROUND_SAMPLES; i += 1) {
    let s = 0, w = 0;
    for (let k = -2; k <= 2; k += 1) {
      let j = i + k;
      if (def.meta.loop) j = (j + GROUND_SAMPLES) % GROUND_SAMPLES; else j = Math.max(0, Math.min(GROUND_SAMPLES, j));
      const wk = 3 - Math.abs(k); s += tab[j] * wk; w += wk;
    }
    sm[i] = s / w;
  }
  groundCache.set(def.meta.name, sm);
  return sm;
}

function rawPose(def: ClipDef, u: number): Pose {
  const out: Pose = {};
  for (const k of ALL_PARAMS) {
    let used = false;
    for (const key of def.keys) if (key.p[k] !== undefined) { used = true; break; }
    if (used) out[k] = catmullValue(def.keys, u, k, def.meta.loop);
  }
  return out;
}

/** Pose of a clip at normalised time u (grounded). */
export function samplePose(def: ClipDef, u: number): Pose {
  const p = rawPose(def, u);
  const tab = groundTable(def);
  const x = (def.meta.loop ? ((u % 1) + 1) % 1 : Math.max(0, Math.min(1, u))) * GROUND_SAMPLES;
  const i = Math.floor(x), f = x - i;
  const g = tab[Math.min(GROUND_SAMPLES, i)] * (1 - f) + tab[Math.min(GROUND_SAMPLES, i + 1)] * f;
  p.rootY = (p.rootY ?? 0) + g;
  return p;
}

// ------------------------------------------------------------------ measurement (root motion extraction)
/**
 * Natural cycle length of a gait clip: integrate how far the weight-bearing sole point
 * travels backwards relative to the hips while it is on the ground (y < 2 cm), over one
 * cycle, for both feet. Playing the cycle at `speed / stride` cycles per second keeps the
 * planted foot still on the grass while the engine moves the root at `speed`.
 */
export function measureStride(def: ClipDef, axis: "z" | "x" = "z", samples = 240): { stride: number; contactShare: number } {
  const rig = fkRig();
  let travel = 0, contact = 0;
  const prev: Record<"L" | "R", { y: number; v: number; id: number; pts: number[] } | null> = { L: null, R: null };
  for (let i = 0; i <= samples; i += 1) {
    applyPose(rig, samplePose(def, i / samples));
    const c = contactPoints(rig);
    for (const side of ["L", "R"] as const) {
      const { p: pt, id } = lowestWithId(c, side);
      const all = side === "L" ? [c.heelL, c.ballL, c.tipL] : [c.heelR, c.ballR, c.tipR];
      const v = axis === "z" ? pt.z : pt.x;
      const pr = prev[side];
      if (pr && pt.y < 0.02 && pr.y < 0.02) {
        // compare the SAME sole point across samples (heel->ball roll is not travel)
        const same = axis === "z" ? all[pr.id].z : all[pr.id].x;
        const d = pr.pts[pr.id] - same;   // backwards travel of the planted point = forward travel of the body
        if (d > 0) travel += d;
        contact += 1;
      }
      prev[side] = { y: pt.y, v, id, pts: all.map((q) => (axis === "z" ? q.z : q.x)) };
    }
  }
  // body speed is constant: planted travel summed over both feet = cycle length x total contact share
  return { stride: contact ? travel * samples / contact : 0, contactShare: contact / (samples * 2) };
}

/** Foot speed (m/s, hips frame, time scale 1) of the contact part at the contact time. */
export function contactSpeed(def: ClipDef): number | null {
  const c = def.meta.contact;
  if (!c) return null;
  const bone: Partial<Record<ContactPart, BoneName>> = { footR: "toeR", footL: "toeL", head: "head", chest: "chest", hands: "handL", handL: "handL", handR: "handR", thighR: "shinR" };
  const b = bone[c.part];
  if (!b) return null;
  const rig = fkRig();
  const dt = 1 / 240;
  applyPose(rig, samplePose(def, c.u - dt / def.meta.duration));
  const a = worldOf(rig, b);
  applyPose(rig, samplePose(def, c.u + dt / def.meta.duration));
  const bb = worldOf(rig, b);
  return a.distanceTo(bb) / (2 * dt);
}

// ------------------------------------------------------------------ baking (AnimationMixer / GLB)
const rotScratch = new Map<BoneName, THREE.Quaternion>();
export function bakeClip(def: ClipDef, fps = 30): THREE.AnimationClip {
  const frames = Math.max(2, Math.round(def.meta.duration * fps));
  const times = new Float32Array(frames + 1);
  const quats: Record<string, Float32Array> = {};
  for (const b of BONES) quats[b] = new Float32Array((frames + 1) * 4);
  const hips = new Float32Array((frames + 1) * 3);
  const prev = new Map<BoneName, THREE.Quaternion>();
  const base = fkRig().bones.hips.position.clone();
  for (let i = 0; i <= frames; i += 1) {
    const u = i / frames;
    times[i] = u * def.meta.duration;
    const p = samplePose(def, u);
    poseRotations(p, rotScratch);
    for (const b of BONES) {
      const qq = rotScratch.get(b)!.clone();
      const pq = prev.get(b);
      if (pq && pq.dot(qq) < 0) qq.set(-qq.x, -qq.y, -qq.z, -qq.w);   // shortest path for slerp
      prev.set(b, qq);
      quats[b].set([qq.x, qq.y, qq.z, qq.w], i * 4);
    }
    applyPose(fkRig(), p);
    hips.set([base.x + (p.rootX ?? 0), fkRig().bones.hips.position.y, base.z + (p.rootZ ?? 0)], i * 3);
  }
  const tracks: THREE.KeyframeTrack[] = BONES.map((b) => new THREE.QuaternionKeyframeTrack(`${b}.quaternion`, times, quats[b]));
  tracks.push(new THREE.VectorKeyframeTrack("hips.position", times, hips));
  return new THREE.AnimationClip(def.meta.name, def.meta.duration, tracks);
}

let baked: { meta: ClipMeta; clip: THREE.AnimationClip }[] | null = null;
export function allClips(): { meta: ClipMeta; clip: THREE.AnimationClip }[] {
  return (baked ??= CLIP_DEFS.map((d) => ({ meta: { ...d.meta, stride: d.meta.loop && d.meta.direction !== "in-place" ? measureStride(d, d.meta.direction === "lateral" ? "x" : "z").stride : undefined }, clip: bakeClip(d) })));
}

/** Plain-JSON metadata for every clip (the integration contract; also written to docs). */
export function clipMetadata(): ClipMeta[] {
  return CLIP_DEFS.map((d) => ({ ...d.meta, stride: d.meta.loop && d.meta.direction !== "in-place" ? +measureStride(d, d.meta.direction === "lateral" ? "x" : "z").stride.toFixed(3) : undefined }));
}
