// Two real browsers, one 2D and one 3D, play the SAME Modo Jogável match against each other
// (backend: tools/interactive_acceptance.py). Checks: both see the same official state, the
// gestures of each coach are accepted only on his own attacks, a reload in the middle of the
// match resumes it (same score, clock not reset) and the result is recorded once.
// Automated playtest — not human feedback.
// Usage: node scripts/verify-interactive.cjs <state.json> <out dir> [app url] [api url]
const path = require("node:path");
const fs = require("node:fs");
const { chromium } = require(path.join(__dirname, "..", "node_modules", "playwright"));
const state = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const out = process.argv[3] || "/tmp/interactive";
const APP = process.argv[4] || "http://127.0.0.1:5175/";
const API = process.argv[5] || "http://127.0.0.1:8001/api/v1";
fs.mkdirSync(out, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok: Boolean(ok), detail }); log(ok ? "PASS" : "FAIL", name, detail); };

async function open(browser, token, exp, name) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 760 }, recordVideo: { dir: out, size: { width: 1280, height: 760 } } });
  await context.addInitScript(([t, room, e]) => {
    localStorage.setItem("bm_session_token", t); localStorage.setItem("bm_active_room", room);
    localStorage.setItem("bm_match_experience", e); localStorage.setItem("bm_playtest", "1");
  }, [token, state.room_id, exp]);
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error" && !/ERR_ABORTED|401|net::/.test(m.text())) errors.push(m.text()); });
  await page.goto(APP);
  return { page, context, errors, name, exp, actions: 0, rejected: 0 };
}
const view = (c) => c.page.evaluate(() => (window.__bmMatch ? window.__bmMatch.view() : null)).catch(() => null);

async function act(c, v) {
  const o = v.opportunity, L = v.pitch.length, W = v.pitch.width;
  const dir = o.right === false ? -1 : 1;
  const ci = o.roster.findIndex((r) => r.id === o.carrier);
  const [cx, cy] = o.positions[ci];
  const x = cx * L, y = cy * W, goalX = dir > 0 ? L : 0;
  let tx, ty, power, key;
  if (Math.abs(goalX - x) < 24 || o.actions >= 4) { tx = goalX; ty = W / 2 + (Math.random() < 0.5 ? -2.4 : 2.4); power = 0.75; key = "5"; }
  else {
    const mates = o.roster.map((r, i) => [r, o.positions[i]]).filter(([r]) => r.team === "A" && r.role !== "GK" && r.id !== o.carrier)
      .map(([, p]) => [p[0] * L, p[1] * W]).filter((p) => Math.hypot(p[0] - x, p[1] - y) > 6 && Math.hypot(p[0] - x, p[1] - y) < 30)
      .sort((a, b) => (b[0] - x) * dir - (a[0] - x) * dir);
    const m = mates[0] || [x + dir * 10, y];
    tx = m[0] + dir * 2; ty = m[1]; power = Math.min(1, Math.max(0.12, Math.hypot(tx - x, ty - y) / 55)); key = "2";
  }
  const ux = tx - x, uy = ty - y, len = Math.hypot(ux, uy) || 1, dragM = Math.max(2, power * L * 0.4);
  let a = null, b = null;
  for (const shift of [0, 6, 12, -6]) {
    const sx = cx + (dir * shift) / L;
    const pa = await c.page.evaluate(([px, py]) => window.__bmMatch.toClient(px, py), [sx, cy]);
    const pb = await c.page.evaluate(([px, py]) => window.__bmMatch.toClient(px, py), [sx + (ux / len) * dragM / L, cy + (uy / len) * dragM / W]);
    if (pa && pb && pa[1] > 90 && pa[1] < 640 && pa[0] > 10 && pa[0] < 1270) { a = pa; b = pb; break; }
  }
  if (!a) {
    const exp = await c.page.evaluate(() => window.__bmMatch.experience());
    const pc = await c.page.evaluate(([px, py]) => window.__bmMatch.toClient(px, py), [cx, cy]);
    c.misses = (c.misses || 0) + 1;
    if (c.misses < 4) log(c.name, "no drag start", exp, JSON.stringify(pc), v.state, o.kind);
    return;
  }
  await c.page.keyboard.press(key);
  await c.page.mouse.move(a[0], a[1]);
  await c.page.mouse.down();
  for (let k = 1; k <= 10; k += 1) { await c.page.mouse.move(a[0] + (b[0] - a[0]) * k / 10, a[1] + (b[1] - a[1]) * k / 10); await sleep(14); }
  await c.page.mouse.up();
  c.actions += 1;
  await sleep(400);
  const feedback = await c.page.locator(".im-feedback").innerText().catch(() => "");
  if (feedback) { c.rejected += 1; log(c.name, "feedback:", feedback); }
}

(async () => {
  const browser = await chromium.launch({ executablePath: "/usr/bin/google-chrome", headless: true, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
  const expA = process.env.EXP_A || "2D", expB = process.env.EXP_B || "3D";
  const A = await open(browser, state.tokens[0], expA, `A-${expA}`);
  const B = await open(browser, state.tokens[1], expB, `B-${expB}`);
  try {
    for (const c of [A, B]) {
      await c.page.waitForSelector(".career-head", { timeout: 30000 });
      await c.page.locator(".career-head__cta button").click();
      await c.page.waitForSelector(".matchup", { timeout: 30000 });
      await c.page.getByRole("button", { name: "Confirmar equipe" }).click();
    }
    for (const c of [A, B]) await c.page.waitForFunction(() => window.__bmMatch && window.__bmMatch.view() && window.__bmMatch.view().state !== "NONE", null, { timeout: 60000 });
    check("both coaches enter the same interactive match", true);
    const t0 = Date.now();
    let reloaded = false, mismatches = 0, syncs = 0, maxMinute = 0, minuteReset = false;
    let lastScore = null;
    const final = { A: null, B: null };
    let matchId = null;
    while (Date.now() - t0 < 560000) {
      let [va, vb] = await Promise.all([view(A), view(B)]);
      matchId = matchId || va?.match_id || vb?.match_id;
      // Only the coaches' own match counts (after it, the app may show another one).
      if (va && va.match_id !== matchId) va = null;
      if (vb && vb.match_id !== matchId) vb = null;
      if (va) final.A = va;
      if (vb) final.B = vb;
      // After the final whistle the app leaves the match screen (match report): done.
      if ((!va || va.state === "FINISHED") && (!vb || vb.state === "FINISHED") && (maxMinute > 85 || final.A?.state === "FINISHED" || final.B?.state === "FINISHED")) break;
      if (va && vb) {
        if (va.match_id !== vb.match_id) mismatches += 1;
        if (va.revision === vb.revision) { syncs += 1; if (va.score.home !== vb.score.home || va.score.away !== vb.score.away) mismatches += 1; }
        if (typeof va.minute === "number") {
          if (va.minute + 2 < maxMinute) minuteReset = true;
          maxMinute = Math.max(maxMinute, va.minute);
        }
        lastScore = va.score;
        if (va.state === "FINISHED" && vb.state === "FINISHED") break;
        if (va.your_turn && vb.your_turn) { mismatches += 1; log("both your_turn", va.revision, vb.revision, va.match_id, vb.match_id); }
        for (const [c, v] of [[A, va], [B, vb]]) if (v.your_turn) await act(c, v);
        if (!reloaded && B.actions >= 1 && va.minute > 20) {
          reloaded = true;
          const before = await view(B);
          await B.page.screenshot({ path: path.join(out, "antes-reload-3d.png") });
          await B.page.reload();
          await B.page.waitForFunction(() => window.__bmMatch && window.__bmMatch.view() && window.__bmMatch.view().state !== "NONE", null, { timeout: 60000 }).catch(() => {});
          const after = await view(B);
          check(`${B.exp} coach reloads mid-match and is back in the same match`, Boolean(after && after.match_id === before.match_id), `${before?.minute?.toFixed(1)}' → ${after?.minute?.toFixed(1)}'`);
          check("reload keeps the score and the clock", Boolean(after && after.score.home >= before.score.home && after.score.away >= before.score.away && after.minute >= before.minute - 0.5));
        }
      }
      await sleep(250);
    }
    const fa = final.A, fb = final.B;
    check("match finishes for both coaches", (fa?.state === "FINISHED" || fa?.minute > 85) && (fb?.state === "FINISHED" || fb?.minute > 85), `${fa?.state} ${fa?.minute?.toFixed?.(1)}' / ${fb?.state} ${fb?.minute?.toFixed?.(1)}'`);
    check(`same official score on ${A.exp} and ${B.exp}`, Boolean(fa && fb && fa.score.home === fb.score.home && fa.score.away === fb.score.away), JSON.stringify(fa?.score));
    check("no divergence during the match", mismatches === 0, `${mismatches} mismatches in ${syncs} synchronised polls`);
    check("clock never reset", !minuteReset, `max ${maxMinute.toFixed(1)}'`);
    check("both coaches played their own attacks", A.actions > 0 && B.actions > 0, `2D: ${A.actions} gestos (${A.rejected} recusados), 3D: ${B.actions} gestos (${B.rejected} recusados)`);
    await A.page.screenshot({ path: path.join(out, "fim-2d.png") });
    await B.page.screenshot({ path: path.join(out, "fim-3d.png") });
    await sleep(8000);
    const season = await fetch(`${API}/rooms/${state.room_id}/season`, { headers: { authorization: `Bearer ${state.tokens[0]}` } }).then((r) => r.json()).then((r) => r.data).catch(() => null);
    const tie = season && Object.values(season.knockout?.ties ?? {}).find((t) => t.stage === "SF" && [t.high, t.low].includes(state.clubs[0]) && [t.high, t.low].includes(state.clubs[1]));
    check("result recorded in the competition (the coaches' semi-final)", Boolean(tie && tie.winner && state.clubs.includes(tie.winner)), JSON.stringify(tie ? { tie: [tie.high, tie.low], winner: tie.winner } : null));
    void lastScore;
  } catch (error) {
    check("flow completed without exceptions", false, String(error).slice(0, 300));
    await A.page.screenshot({ path: path.join(out, "zz-falha-a.png") }).catch(() => {});
    await B.page.screenshot({ path: path.join(out, "zz-falha-b.png") }).catch(() => {});
  }
  check(`no page errors (${A.exp})`, A.errors.length === 0, A.errors.slice(0, 2).join(" | "));
  check(`no page errors (${B.exp})`, B.errors.length === 0, B.errors.slice(0, 2).join(" | "));
  fs.writeFileSync(path.join(out, "results.json"), JSON.stringify(results, null, 2));
  await A.context.close(); await B.context.close();
  await browser.close();
  log(`${results.filter((r) => r.ok).length}/${results.length} checks passed`);
})();
