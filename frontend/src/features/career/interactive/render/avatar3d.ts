import * as THREE from "three";

import { createAthlete, type Athlete } from "../../../../football/athlete/athlete";
import type { KitSpec, Pattern } from "../../../../football/athlete/kit";
import { lerpPose, mirrorPose, type Pose } from "../../../../football/athlete/rig";
import { CLIPS, GK_READY_POSE, samplePose, type ClipDef } from "../../../../football/anim/clips";
import { Locomotion } from "../../../../football/anim/locomotion";
import type { InteractiveCue, InteractiveStep } from "../../../../lib/api";
import { ACT, type ScenePlayer } from "./presentation";
import { hashOf, VISUAL } from "./config";
import type { Kit } from "./renderer2d";

/**
 * V8 athlete of the official 3D view: the research lab's skinned human (21 bones, loft
 * body, kit texture) driven ONLY by the official scene.
 *
 *  - Locomotion: the server moves the root; the legs follow with a distance-matched gait
 *    phase and foot locking (football/anim/locomotion.ts, "matched+ik"), so a planted foot
 *    stays on the grass at every speed (docs/v8/SPRINT.md).
 *  - Actions: the clip of each official action (pass, cross, shot, tackle, header, control,
 *    keeper dive…) is played so that its CONTACT frame lands exactly on the server's cue
 *    time — the ball leaves the foot on the frame it leaves in the physics.
 *  - Nothing here decides anything: no clip can move the athlete or the ball.
 */
const DETAIL = { low: "low", medium: "medium", high: "high" } as const;
type Quality = keyof typeof DETAIL;

function kitSpec(kit: Kit, number: number): KitSpec {
  const pattern: Pattern = kit.pattern === "stripes" || kit.pattern === "hoops" || kit.pattern === "sash" ? kit.pattern : "plain";
  return { primary: kit.shirt, secondary: kit.trim, pattern, shorts: kit.shorts, socks: kit.socks, number: number || 0, numberColor: kit.number ?? "#ffffff" };
}

type Action = { def: ClipDef; t0: number; contact: number; mirror: boolean; until: number; hold?: boolean };

export class Avatar3D {
  readonly root = new THREE.Group();      // world placement (renderer sets position + yaw)
  readonly tilt = new THREE.Group();      // keeper roll on the ground / in the air
  readonly athlete: Athlete;
  readonly ring: THREE.Mesh;
  readonly key: string;
  private loco = new Locomotion();
  private action: Action | null = null;
  private weight = 0;
  private lastStep = "init";
  private lastPose: Pose = GK_READY_POSE;
  private keeperRoll = 0;
  slide = 0;

  constructor(p: ScenePlayer, kit: Kit, quality: Quality, shadows: boolean, ringGeo: THREE.BufferGeometry, key: string) {
    const wear = p.keeper ? (kit.gk ?? { shirt: VISUAL.keeperKits[p.team], shorts: "#2a2a33", socks: VISUAL.keeperKits[p.team], trim: "#ffffff" }) : kit;
    this.athlete = createAthlete({ kit: kitSpec(wear, p.number), keeper: p.keeper, detail: DETAIL[quality], shadows, seed: hashOf(p.id) });
    this.loco.mode = "matched+ik";
    this.root.add(this.tilt);
    this.tilt.add(this.athlete.group);
    this.ring = new THREE.Mesh(ringGeo, new THREE.MeshBasicMaterial({ color: 0xc6f24e, transparent: true, opacity: 0.9, depthWrite: false }));
    this.ring.position.y = 0.03; this.ring.scale.setScalar(0.8); this.ring.visible = false;
    this.root.add(this.ring);
    this.key = key;
  }

  dispose() { this.athlete.dispose(); }

  /** The clip and timing of the official action this athlete is doing now (or null). */
  private chooseAction(p: ScenePlayer, step: InteractiveStep | null, t: number): Action | null {
    if (!step) return null;
    const cues = step.cues ?? [];
    const mine = (kinds: string[]) => cues.filter((c) => c.id === p.id && kinds.includes(c.kind));
    const at = (c: InteractiveCue, def: ClipDef, mirror = false, hold = false): Action => {
      const contact = def.meta.contact?.time ?? 0;
      return { def, t0: c.t - contact, contact: c.t, mirror, until: c.t - contact + def.meta.duration, hold };
    };
    for (const c of mine(["KICK"])) {
      const def = c.action === "SHOT" ? (step.type === "SHOT" && (c.power ?? 0.7) > 0.45 ? CLIPS.shot : CLIPS.first_time)
        : c.action === "LOFT" ? CLIPS.cross : (c.power ?? 0.4) > 0.55 ? CLIPS.pass_long : CLIPS.pass_short;
      const a = at(c, def);
      if (t >= a.t0 - 0.02 && t <= a.until) return a;
    }
    for (const c of mine(["HEADER"])) { const a = at(c, CLIPS.header); if (t >= a.t0 && t <= a.until) return a; }
    for (const c of mine(["TACKLE", "INTERCEPT", "BLOCK"])) {
      const a = at(c, p.speed > 4 && c.kind === "TACKLE" ? CLIPS.slide_tackle : CLIPS.stand_tackle);
      if (t >= a.t0 && t <= a.until) return a;
    }
    for (const c of mine(["CONTROL"])) { const a = at(c, CLIPS.receive); if (t >= a.t0 && t <= a.until) return a; }
    if (p.keeper) {
      for (const c of mine(["SAVE", "DIVE", "CLAIM"])) {
        if (c.kind === "CLAIM" || (c.kind === "SAVE" && c.hold && !(c.dy ?? 0))) { const a = at(c, CLIPS.gk_catch, false, true); if (t >= a.t0) return a; continue; }
        if (c.level === "high" && !(c.dy ?? 0)) { const a = at(c, CLIPS.gk_jump); if (t >= a.t0 && t <= a.until) return a; continue; }
      }
    }
    return null;
  }

  update(p: ScenePlayer, step: InteractiveStep | null, t: number, dt: number, now: number, playing: boolean) {
    const a = this.athlete;
    if (!playing && this.lastStep !== "init" && p.pose !== "celebrate") {
      // Decision pause: the official state is frozen — so is the body (frozen mid-stride),
      // the gait phase does not advance (no running on the spot).
      if (p.keeper && p.pose === "ready") a.setPose(GK_READY_POSE);
      else a.setPose(this.lastPose);
      return;
    }
    const stepKey = step ? `${step.starts_at}:${step.carrier}` : "";
    if (stepKey !== this.lastStep) { this.lastStep = stepKey; this.action = null; }
    // ---- keeper on the ground / in the air: physics already moved the body; we roll and pose it
    if (p.keeper && (p.act === ACT.GK_DIVE || p.act === ACT.GK_DOWN || p.act === ACT.GK_RISE)) {
      const side = this.diveSide(p);
      const dive = (step?.cues ?? []).find((c) => c.id === p.id && (c.kind === "DIVE" || c.kind === "SAVE"));
      const high = dive?.level === "high" || dive?.high;
      const def = p.act === ACT.GK_RISE ? CLIPS.gk_getup : high ? CLIPS.gk_dive_high : CLIPS.gk_dive_low;
      const since = dive ? Math.max(0, t - dive.t) : 0.4;
      const u = p.act === ACT.GK_DIVE ? Math.min(0.75, 0.25 + since / 0.55 * 0.5) : p.act === ACT.GK_DOWN ? 0.95 : Math.min(1, since / 1.1);
      let pose = samplePose(def, u);
      if (side < 0) pose = mirrorPose(pose);
      const roll = p.act === ACT.GK_RISE ? 0 : -side * Math.min(1.2, 0.35 + since * 2.4);
      this.keeperRoll += (roll - this.keeperRoll) * Math.min(1, dt * 14);
      this.tilt.rotation.z = this.keeperRoll;
      this.tilt.position.y = p.act === ACT.GK_DIVE ? 0.35 * Math.sin(Math.min(1, since / 0.5) * Math.PI) : 0;
      a.setPose(pose);
      this.lastPose = pose;
      return;
    }
    this.keeperRoll += (0 - this.keeperRoll) * Math.min(1, dt * 10);
    this.tilt.rotation.z = this.keeperRoll;
    this.tilt.position.y = 0;
    // ---- official action clip, aligned on the contact cue
    const act = this.chooseAction(p, step, t);
    if (act) this.action = act;
    const live = this.action && (t <= this.action.until || this.action.hold) ? this.action : null;
    this.weight += ((live ? 1 : 0) - this.weight) * Math.min(1, dt * (live ? 14 : 7));
    let actionPose: Pose | null = null;
    if (live) {
      const u = Math.max(0, Math.min(1, (t - live.t0) / live.def.meta.duration));
      actionPose = samplePose(live.def, live.hold ? Math.min(u, 0.6) : u);
      if (live.mirror) actionPose = mirrorPose(actionPose);
    } else if (this.weight < 0.02) this.action = null;
    // ---- locomotion (legs follow the official displacement; foot locking)
    const keeperIdle = p.keeper && (p.pose === "ready" || p.act === ACT.GK_SET || p.act === ACT.GK_STEP) && p.speed < 2.5;
    const celebrate = p.pose === "celebrate";
    if (this.weight > 0.98 && actionPose) {
      a.setPose(actionPose);
      this.lastPose = actionPose;
      return;
    }
    const body = { group: this.root, rig: a.rig, setPose: (pose: Pose) => {
      let out = pose;
      if (keeperIdle) out = lerpPose(pose, GK_READY_POSE, Math.max(0, 1 - p.speed / 2.5));
      if (celebrate) out = lerpPose(out, samplePose(CLIPS.celebrate, ((now % 2) + 2) % 2 / 2), 0.85);
      if (actionPose && this.weight > 0.01) out = lerpPose(out, actionPose, this.weight);
      this.lastPose = out;
      a.setPose(out);
    } };
    this.loco.dribble = p.act === ACT.DRIBBLE;
    this.loco.update(body, Math.max(1e-3, dt), p.speed, this.root.rotation.y);
    this.slide = this.loco.slideMean();
  }

  /** Dive side in the athlete's own frame: +1 = towards his left (+X), the clips' side. */
  private diveSide(p: ScenePlayer): number {
    const ry = this.root.rotation.y;
    // world velocity in three.js axes: x along the pitch, z across (renderer convention: z = y·W)
    const lx = Math.cos(ry), lz = -Math.sin(ry);
    const d = p.vx * lx + p.vy * lz;
    return d >= 0 ? 1 : -1;
  }
}
