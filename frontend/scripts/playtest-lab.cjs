// Automated playtest of the Football Lab through the REAL interface (mouse drags on the pitch).
// This is an automated playtest, not human feedback: it plays like a simple human would
// (pass to an open team-mate, through ball to the striker, shoot when in range), records
// a video per scenario, and logs every action, its outcome and the response time.
//
// Usage: node scripts/playtest-lab.cjs <out dir> <label> [2D|3D|both] [scenarios] [mode]
const path = require("node:path");
const fs = require("node:fs");
const { chromium } = require(path.join(__dirname, "..", "node_modules", "playwright"));
const out = process.argv[2] || "/tmp/playtest";
const label = process.argv[3] || "run";
const which = process.argv[4] || "both";
const scenarios = (process.argv[5] || "BUILDUP,THROUGH,CROSS,ONE_ON_ONE,COUNTER,WING").split(",");
const formats = (process.argv[6] || "ELEVEN_A_SIDE,FIVE_A_SIDE").split(",");
const engine = process.env.LAB_ENGINE || "";
const APP = process.env.APP || "http://127.0.0.1:5174/";
fs.mkdirSync(out, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const LABEL = { BUILDUP: "Construção pelo meio", COUNTER: "Contra-ataque", WING: "Ataque pela ponta", THROUGH: "Passe em profundidade", CROSS: "Cruzamento",
  REBOUND: "Chute de fora", ONE_ON_ONE: "Cara a cara", FREE_KICK: "Falta", PENALTY: "Pênalti", OVERLOAD: "Superioridade", MATCH: "Partida completa",
  DRILL_1V_GK: "Atacante × goleiro", DRILL_2V1: "2 × 1", DRILL_3V2: "3 × 2", DRILL_COUNTER: "Contra-ataque 3 × 3", DRILL_CROSS: "Cruzamento e área" };
const KEY = { AUTO: "1", PASS: "2", LOFT: "3", CARRY: "4", SHOT: "5" };

function plan(view, step) {
  const o = view.opportunity, L = view.pitch.length, W = view.pitch.width;
  const dir = o.right === false ? -1 : 1;
  const ci = o.roster.findIndex((p) => p.id === o.carrier);
  const [cx, cy] = o.positions[ci];
  const m = (p) => [p[0] * L, p[1] * W];
  const [x, y] = m([cx, cy]);
  const goalX = dir > 0 ? L : 0;
  const toGoal = Math.abs(goalX - x);
  const defenders = o.roster.map((p, i) => [p, m(o.positions[i])]).filter(([p]) => p.team === "D" && p.role !== "GK");
  const keeper = o.roster.map((p, i) => [p, m(o.positions[i])]).find(([p]) => p.team === "D" && p.role === "GK");
  const open = (px, py) => Math.min(...defenders.map(([, d]) => Math.hypot(d[0] - px, d[1] - py)));
  if (o.kind === "PENALTY" || toGoal < 22 * (L / 105) || step >= 5) {
    const side = keeper && keeper[1][1] > W / 2 ? -1 : 1;
    return { type: "SHOT", tx: goalX, ty: W / 2 + side * view.pitch.goal * 0.36, power: 0.72 };
  }
  const mates = o.roster.map((p, i) => [p, m(o.positions[i])]).filter(([p]) => p.team === "A" && p.role !== "GK" && p.id !== o.carrier);
  const scored = mates.map(([p, q]) => ({ p, q, gain: (q[0] - x) * dir, free: open(q[0], q[1]), d: Math.hypot(q[0] - x, q[1] - y) }))
    .filter((c) => c.d > 5 && c.d < 38);
  const wide = Math.min(y, W - y) < 12 * (W / 68) && toGoal < 30;
  if (wide && o.kind !== "BUILDUP") {
    const box = scored.filter((c) => Math.abs(goalX - c.q[0]) < 16).sort((a, b) => b.free - a.free)[0];
    if (box) return { type: "LOFT", tx: box.q[0], ty: box.q[1], power: Math.min(1, Math.max(0, (box.d - 12) / 46)) };
  }
  const best = scored.sort((a, b) => (b.gain * 0.12 + Math.min(b.free, 6) * 0.4) - (a.gain * 0.12 + Math.min(a.free, 6) * 0.4))[0];
  const ahead = open(x + dir * 8, y);
  if ((!best || best.free < 2) && ahead > 5) return { type: "CARRY", tx: x + dir * 11, ty: y + (W / 2 - y) * 0.2, power: 0.5 };
  if (!best) return { type: "SHOT", tx: goalX, ty: W / 2, power: 0.8 };
  const through = best.p.role === "ST" && best.gain > 4 && step % 2 === 1;
  const tx = best.q[0] + (through ? dir * 6 : dir * 1), ty = best.q[1];
  const d = Math.hypot(tx - x, ty - y);
  // PASS power that reaches d with the view's physics (same forecast as the screen).
  const ph = view.physics;
  let power;
  if (ph.model === "v7") power = Math.min(1, Math.max(0.08, (Math.sqrt(2 * ph.decel * (d + 3)) - ph.pass[0]) / ph.pass[1]));
  else power = Math.min(1, Math.max(0.08, (Math.sqrt(2 * ph.decel * (d + 2)) - ph.pass[0]) / ph.pass[1]));
  return { type: "PASS", tx, ty, power, through };
}

async function playScenario(browser, exp, kind, format) {
  const name = `${label}-${exp}-${format === "FIVE_A_SIDE" ? "5x5" : "11x11"}-${kind}`;
  const context = await browser.newContext({ viewport: { width: 1280, height: 760 }, recordVideo: { dir: out, size: { width: 1280, height: 760 } } });
  await context.addInitScript(([e, eng]) => { localStorage.setItem("bm_match_experience", e); localStorage.setItem("bm_cam2d", "play"); if (eng) localStorage.setItem("bm_lab_engine", eng); }, [exp, engine]);
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  await page.goto(APP + "#lab");
  await page.getByRole("radio", { name: new RegExp(LABEL[kind]) }).first().click();
  await page.getByLabel("Formato").selectOption(format);
  await page.getByRole("button", { name: /Jogar cenário/ }).click();
  await page.waitForFunction(() => window.__bmMatch && window.__bmMatch.view(), null, { timeout: 30000 });
  if (exp === "3D") await page.waitForFunction(() => window.__bmMatch.experience() === "3D", null, { timeout: 30000 }).catch(() => {});
  const log = [];
  let step = 0;
  const t0 = Date.now();
  let lastOpp = null;
  while (Date.now() - t0 < 70000) {
    const v = await page.evaluate(() => window.__bmMatch.view());
    if (!v) { await sleep(200); continue; }
    if (v.state === "FINISHED") break;
    if (v.opportunity && v.opportunity.attacking !== v.home && v.state === "OUTCOME") { await sleep(1500); break; }
    if (v.your_turn && v.opportunity) {
      lastOpp = v.opportunity.id;
      await sleep(900);  // "look" at the situation, as a player would
      const p = plan(v, step);
      const o = v.opportunity;
      const ci = o.roster.findIndex((r) => r.id === o.carrier);
      const [cx, cy] = o.positions[ci];
      const L = v.pitch.length, W = v.pitch.width;
      const ux = p.tx - cx * L, uy = p.ty - cy * W, len = Math.hypot(ux, uy) || 1;
      const dragM = Math.max(1.6, p.power * L * 0.4);
      // The drag can start anywhere on the pitch (direction + length are what count): start
      // on the carrier when he is clear of the controls, otherwise on a free point near him.
      let a = null, b = null;
      const dirx = o.right === false ? -1 : 1;
      for (const shift of [0, 6, 12, -6]) {
        const sx = cx + (dirx * shift) / L, sy = cy;
        const ex = sx + (ux / len) * dragM / L, ey = sy + (uy / len) * dragM / W;
        const pa = await page.evaluate(([x, y]) => window.__bmMatch.toClient(x, y), [sx, sy]);
        const pb = await page.evaluate(([x, y]) => window.__bmMatch.toClient(x, y), [ex, ey]);
        const inside = (p) => p && p[1] > 90 && p[1] < 760 - 120 && p[0] > 10 && p[0] < 1270;
        if (inside(pa) && pb) { a = pa; b = pb; if (shift !== 0) log.push({ step, note: `drag started ${shift} m from the carrier (carrier under the controls)` }); break; }
      }
      if (!a || !b) { log.push({ step, error: "projection" }); break; }
      await page.keyboard.press(KEY[step === 0 && kind === "BUILDUP" ? "AUTO" : p.type]);
      await page.mouse.move(a[0], a[1]);
      await page.mouse.down();
      for (let k = 1; k <= 12; k += 1) { await page.mouse.move(a[0] + (b[0] - a[0]) * k / 12, a[1] + (b[1] - a[1]) * k / 12); await sleep(16); }
      if (step === 0) await page.screenshot({ path: path.join(out, `${name}-mira.png`) });
      const up = Date.now();
      await page.mouse.up();
      const rev = v.revision;
      if (process.env.BURST && (step <= 1 || p.type === "SHOT" || p.type === "LOFT")) {
        // Burst of the execution (motion evidence), taken in the background of the timing check.
        const shots = [];
        for (let k = 0; k < 9; k += 1) { shots.push(page.screenshot({ path: path.join(out, `${name}-a${step}-${k}.png`), clip: { x: 0, y: 0, width: 1280, height: 760 } })); await shots[shots.length - 1]; await sleep(110); }
      }
      let confirmed = null;
      while (Date.now() - up < 5000) {
        const w = await page.evaluate(() => window.__bmMatch.view());
        if (w && w.revision !== rev) { confirmed = Date.now() - up; break; }
        await sleep(15);
      }
      // Wait for the execution to finish (next decision or the end of the move).
      let w = null;
      const until = Date.now() + 15000;
      while (Date.now() < until) {
        w = await page.evaluate(() => window.__bmMatch.view());
        if (w && (w.state === "DECISION" || w.state === "OUTCOME" || w.state === "CLOCK" || w.state === "FINISHED") && w.revision !== rev && !(w.state === "EXECUTING")) break;
        await sleep(100);
      }
      const last = w?.opportunity?.last;
      log.push({ step, type: p.type, through: Boolean(p.through), power: Number(p.power.toFixed(2)), confirm_ms: confirmed, outcome: last?.outcome ?? `state:${w?.state}`, detail: last?.detail ?? w?.opportunity?.result, duration: last?.duration });
      step += 1;
      if (w && w.state !== "DECISION") { await sleep(2600); await page.screenshot({ path: path.join(out, `${name}-fim.png`) }); }
      continue;
    }
    await sleep(150);
  }
  const final = await page.evaluate(() => window.__bmMatch.view());
  await context.close();
  const video = await page.video()?.path();
  const target = path.join(out, `${name}.webm`);
  if (video && fs.existsSync(video)) fs.renameSync(video, target);
  return { name, exp, kind, format, actions: log, score: final?.score, errors: errors.slice(0, 5), video: target };
}

(async () => {
  const browser = await chromium.launch({ executablePath: "/usr/bin/google-chrome", headless: true, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
  const results = [];
  const exps = which === "both" ? ["2D", "3D"] : [which];
  for (const format of formats) for (const exp of exps) for (const kind of scenarios) {
    try { const r = await playScenario(browser, exp, kind, format); results.push(r); console.log(JSON.stringify({ name: r.name, score: r.score, actions: r.actions.map((a) => `${a.type}${a.through ? "(prof)" : ""}:${a.outcome}:${a.confirm_ms}ms`) })); }
    catch (error) { results.push({ exp, kind, format, error: String(error).slice(0, 300) }); console.log("FAIL", exp, kind, format, String(error).slice(0, 200)); }
  }
  fs.writeFileSync(path.join(out, `${label}-results.json`), JSON.stringify(results, null, 1));
  await browser.close();
})();
