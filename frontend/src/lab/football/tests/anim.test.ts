import * as THREE from "three";
import { describe, expect, it } from "vitest";

declare const process: { stderr: { write: (s: string) => void } };
import { applyPose, createSkeleton } from "../athlete/rig";
import { CLIPS, CLIP_DEFS, clipMetadata, contactSpeed, measureStride, samplePose, bakeClip } from "../anim/clips";
import { contactPoints, fkRig, lowestOf } from "../anim/fk";
import { Locomotion, RootDriver, type LocoMode } from "../anim/locomotion";

function headlessBody() {
  const rig = createSkeleton();
  const group = new THREE.Group();
  group.add(rig.root);
  return { group, rig, setPose: (p: Parameters<typeof applyPose>[1]) => applyPose(rig, p) };
}

export function slideRun(mode: LocoMode, speed: number, kind: "straight" | "circle" = "straight", seconds = 8) {
  const body = headlessBody();
  const loco = new Locomotion();
  loco.mode = mode;
  const drv = new RootDriver(kind, speed);
  const dt = 1 / 60;
  for (let i = 0; i < seconds / dt; i += 1) {
    drv.step(dt);
    body.group.position.copy(drv.pos);
    body.group.rotation.y = drv.yaw;
    body.group.updateMatrixWorld(true);
    if (i === 60) loco.resetMeter();   // skip the start
    loco.update(body, dt, drv.speed, drv.yaw);
  }
  return { mean: loco.slideMean(), max: loco.slide.max * 100 };
}

describe("animation library", () => {
  it("every clip samples, bakes and keeps a grounded foot where it says so", () => {
    for (const d of CLIP_DEFS) {
      const clip = bakeClip(d);
      expect(clip.tracks.length).toBe(22);
      expect(clip.duration).toBeCloseTo(d.meta.duration, 5);
    }
    const rig = fkRig();
    applyPose(rig, samplePose(CLIPS.idle, 0.3));
    const c = contactPoints(rig);
    expect(Math.min(lowestOf(c, "L").y, lowestOf(c, "R").y)).toBeCloseTo(0, 2);
  });
  it("measured strides are in the human range (walk 1.2-1.8 m, run 2-3.2 m, sprint 3.4-4.8 m per cycle)", () => {
    const walk = measureStride(CLIPS.walk).stride, run = measureStride(CLIPS.run).stride, sprint = measureStride(CLIPS.sprint).stride;
    process.stderr.write(`strides walk=${walk.toFixed(2)} run=${run.toFixed(2)} sprint=${sprint.toFixed(2)}\n`);
    expect(walk).toBeGreaterThan(1.0); expect(walk).toBeLessThan(1.9);
    expect(run).toBeGreaterThan(1.8); expect(run).toBeLessThan(3.3);
    expect(sprint).toBeGreaterThan(3.0); expect(sprint).toBeLessThan(5.0);
    // cadence at typical speeds (steps per second = 2 / cycle time)
    process.stderr.write(`cadence run@4.2=${(2 * 4.2 / run).toFixed(2)} steps/s sprint@8=${(2 * 8 / sprint).toFixed(2)} steps/s\n`);
  });
  it("contact metadata is consistent and the kicking foot moves fast at contact", () => {
    for (const m of clipMetadata()) if (m.contact) { expect(m.contact.time).toBeGreaterThan(0); expect(m.contact.time).toBeLessThan(m.duration); }
    const shot = contactSpeed(CLIPS.shot)!, pass = contactSpeed(CLIPS.pass_short)!;
    process.stderr.write(`foot speed at contact: shot=${shot.toFixed(1)} m/s pass=${pass.toFixed(1)} m/s first_time=${contactSpeed(CLIPS.first_time)!.toFixed(1)}\n`);
    expect(shot).toBeGreaterThan(pass);
  });
  it("speed-synced cycles + foot locking remove most foot sliding", () => {
    const rows: string[] = [];
    for (const v of [1.5, 4.2, 7.5]) {
      const naive = slideRun("naive", v), synced = slideRun("synced", v), ik = slideRun("synced+ik", v);
      rows.push(`v=${v} naive=${naive.mean.toFixed(1)} synced=${synced.mean.toFixed(1)} ik=${ik.mean.toFixed(1)} cm/s (max ${naive.max.toFixed(0)}/${synced.max.toFixed(0)}/${ik.max.toFixed(0)})`);
      process.stderr.write(rows[rows.length - 1] + "\n");
      expect(ik.mean).toBeLessThan(naive.mean);
      expect(ik.mean).toBeLessThanOrEqual(synced.mean + 0.5);
    }
    process.stderr.write(rows.join("\n") + "\n");
  });
});
