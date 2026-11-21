import { it } from "vitest";
import { AI_SCENARIOS, makeWorld, metrics, seededRng, step } from "../ai/tactics";
import { clipMetadata, contactSpeed, CLIP_DEFS, measureStride, CLIPS } from "../../../football/anim/clips";
import { keeperFromRating, scenarios, simulateShot, v6KeeperOutcome, lineCrossing } from "../keeper/sim";
import { slideRun } from "./anim.test";

/** Writes the measured data used in docs/research/football-lab (run with REPORT=1). */
declare const process: { env: Record<string, string | undefined> };
const enabled = typeof process !== "undefined" && process.env.REPORT === "1";
it.skipIf(!enabled)("writes research data", async () => {
  const fs = await import(/* @vite-ignore */ "node:" + "fs") as { writeFileSync: (p: string, d: string) => void };
  const out = "../docs/research/football-lab/data/";
  const keeper = scenarios().map((s) => {
    const at = lineCrossing(s.shot);
    const row: Record<string, unknown> = { id: s.id, label: s.label, speed: s.shot.speed, line: at && { y: +at.y.toFixed(2), z: +at.z.toFixed(2), t: +at.t.toFixed(2) } };
    for (const r of [45, 70, 92]) { const res = simulateShot(s.shot, { keeper: keeperFromRating(r), seed: 7 }); row[`gk${r}`] = { outcome: res.outcome, plan: res.plan?.kind, takeoff: res.takeoff && +res.takeoff.toFixed(2), contact: res.contact && +res.contact.t.toFixed(2), maxComSpeed: +res.maxComSpeed.toFixed(2), detail: res.detail }; }
    const v6 = v6KeeperOutcome(s.shot, 70); row.v6_70 = { result: v6.result, probability: +v6.probability.toFixed(2) };
    return row;
  });
  fs.writeFileSync(out + "keeper-scenarios.json", JSON.stringify(keeper, null, 2));
  const slide = [1.5, 4.2, 7.5].map((v) => ({ speed: v, naive: slideRun("naive", v), synced: slideRun("synced", v), syncedIK: slideRun("synced+ik", v) }));
  fs.writeFileSync(out + "foot-sliding.json", JSON.stringify(slide, null, 2));
  const meta = clipMetadata().map((m) => ({ ...m, contactFootSpeed: contactSpeed(CLIP_DEFS.find((d) => d.meta.name === m.name)!) }));
  fs.writeFileSync(out + "clip-metadata.json", JSON.stringify(meta, null, 2));
  fs.writeFileSync(out + "strides.json", JSON.stringify({ walk: measureStride(CLIPS.walk), run: measureStride(CLIPS.run), sprint: measureStride(CLIPS.sprint), dribble: measureStride(CLIPS.dribble), gk_shuffle: measureStride(CLIPS.gk_shuffle, "x") }, null, 2));
  const ai = AI_SCENARIOS.map((d) => {
    const run = (naive: boolean) => {
      const w = makeWorld(d, 1); const rng = seededRng(1); let chaserSum = 0, n = 0, maxCh = 0, spacing = 0;
      for (let i = 0; i < 30 * 8 && !w.done; i += 1) {
        if (naive) for (const a of w.agents) if (a.role !== "GK" && a.id !== w.ball.owner) a.target = { ...w.ball.p };
        step(w, 1 / 30, rng);
        if (naive) for (const a of w.agents) if (a.role !== "GK" && a.id !== w.ball.owner) a.target = { ...w.ball.p };
        const m = metrics(w); chaserSum += m.chasers; maxCh = Math.max(maxCh, m.chasers); spacing += m.meanSpacing; n += 1;
      }
      return { meanChasers: +(chaserSum / n).toFixed(2), maxChasers: maxCh, meanSpacing: +(spacing / n).toFixed(1), end: w.done ?? "8 s", events: w.events };
    };
    return { id: d.id, label: d.label, ai: run(false), naive: run(true) };
  });
  fs.writeFileSync(out + "ai-scenarios.json", JSON.stringify(ai, null, 2));
});
