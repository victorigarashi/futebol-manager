import { describe, expect, it } from "vitest";
import { slideRun } from "./anim.test";

declare const process: { stderr: { write: (s: string) => void } };

/**
 * V8 sprint fix: distance-matched phase + foot lock vs the research "synced+ik".
 * Metric (same meter as the research lab): mean speed of the planted sole points (cm/s),
 * straight runs with accelerations/stops, skipping the first second.
 */
describe("foot sliding: distance-matched phase (V8)", () => {
  it("removes most of the remaining sliding at every gait, sprint included", () => {
    const rows: string[] = [];
    for (const v of [1.5, 4.2, 7.5, 8.5]) {
      const ik = slideRun("synced+ik", v), matched = slideRun("matched+ik", v);
      rows.push(`v=${v} synced+ik=${ik.mean.toFixed(1)} matched+ik=${matched.mean.toFixed(1)} cm/s (max ${ik.max.toFixed(0)}/${matched.max.toFixed(0)})`);
      expect(matched.mean).toBeLessThanOrEqual(ik.mean + 1);
    }
    for (const v of [4.2, 8.5]) {
      const ik = slideRun("synced+ik", v, "circle"), matched = slideRun("matched+ik", v, "circle");
      rows.push(`circle v=${v} synced+ik=${ik.mean.toFixed(1)} matched+ik=${matched.mean.toFixed(1)} cm/s`);
    }
    process.stderr.write(rows.join("\n") + "\n");
    const sprint = slideRun("matched+ik", 7.5);
    expect(sprint.mean).toBeLessThan(40);
  });
});
