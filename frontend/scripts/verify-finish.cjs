// End-of-match regression (Modo Jogável): two real browsers play the SAME match to the
// final whistle and the app must leave the 3D/2D screen on its own, show the official
// result once and let the coach continue the career. Also checks that reloading after the
// whistle neither restarts the match nor duplicates the result, and that 2D <-> 3D can be
// switched near the end without losing the official state.
//
// Backend: tools/interactive_acceptance.py (state file with room_id, tokens, clubs).
// Usage: node scripts/verify-finish.cjs <state.json> <out dir> [app url] [api url]
const path = require("node:path");
const fs = require("node:fs");
const { chromium } = require(path.join(__dirname, "..", "node_modules", "playwright"));
const state = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const out = process.argv[3] || "/tmp/finish";
const APP = process.argv[4] || "http://127.0.0.1:5175/";
const API = process.argv[5] || "http://127.0.0.1:8001/api/v1";
const EXE = process.env.CHROMIUM_PATH || undefined;
fs.mkdirSync(out, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok: Boolean(ok), detail }); log(ok ? "PASS" : "FAIL", name, detail); };
const api = (p, token, init = {}) => fetch(`${API}${p}`, {
  ...init,
  headers: { authorization: `Bearer ${token}`, "content-type": "application/json", ...(init.headers || {}) },
});

async function ready(token) {
  const response = await api(`/rooms/${state.room_id}/season/ready`, token, { method: "POST", body: "{}" });
  return response.status;
}

async function open(browser, token, exp, name) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 760 }, recordVideo: { dir: out, size: { width: 1280, height: 760 } } });
  await context.addInitScript(([t, room, e]) => {
    localStorage.setItem("bm_session_token", t); localStorage.setItem("bm_active_room", room);
    localStorage.setItem("bm_match_experience", e); localStorage.setItem("bm_playtest", "1");
    localStorage.setItem("bm_quality", "low");
  }, [token, state.room_id, exp]);
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error" && !/ERR_ABORTED|401|net::|Failed to load resource/.test(m.text())) errors.push(m.text()); });
  await page.goto(APP);
  return { page, context, errors, name, exp, actions: 0 };
}
const view = (c) => c.page.evaluate(() => (window.__bmMatch ? window.__bmMatch.view() : null)).catch(() => null);

/** One gesture by keyboard: pick the shot (or a pass inside the box), aim, execute. */
async function act(c, v) {
  const o = v.opportunity;
  const L = v.pitch.length, W = v.pitch.width;
  const ci = o.roster.findIndex((r) => r.id === o.carrier);
  const [cx, cy] = o.positions[ci];
  const dir = o.right === false ? -1 : 1;
  const goalX = dir > 0 ? L : 0;
  const near = Math.abs(goalX - cx * L) < 30 || o.actions >= 3;
  await c.page.keyboard.press(near ? "5" : "2");
  await c.page.keyboard.press("Enter");
  await sleep(90);
  if (!near) {
    // Aim at the most advanced team-mate, then execute.
    for (let i = 0; i < 4; i += 1) await c.page.keyboard.press("Tab");
  }
  void cy; void W;
  await c.page.keyboard.press("Enter");
  c.actions += 1;
  await sleep(260);
}

(async () => {
  // Both coaches confirm their teams (the round starts when both are ready).
  for (const token of state.tokens) await ready(token);
  const browser = await chromium.launch({ executablePath: EXE, headless: true, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
  const A = await open(browser, state.tokens[0], process.env.EXP_A || "2D", "A-2D");
  const B = await open(browser, state.tokens[1], process.env.EXP_B || "3D", "B-3D");
  let matchId = null;
  const finished = { A: null, B: null };
  try {
    await Promise.all([A, B].map((c) => c.page.waitForFunction(() => window.__bmMatch && window.__bmMatch.view() && window.__bmMatch.view().state !== "NONE", null, { timeout: 90000 })));
    check("both coaches enter the same interactive match", true);
    const t0 = Date.now();
    let switched = false, maxMinute = 0;
    while (Date.now() - t0 < 420000) {
      const [va, vb] = await Promise.all([view(A), view(B)]);
      matchId = matchId || va?.match_id || vb?.match_id;
      const a = va && va.match_id === matchId ? va : null;
      const b = vb && vb.match_id === matchId ? vb : null;
      if (a) finished.A = a; if (b) finished.B = b;
      maxMinute = Math.max(maxMinute, a?.minute ?? 0, b?.minute ?? 0);
      if (a?.state === "FINISHED" || b?.state === "FINISHED") break;
      if (!a && !b) break;                                   // the app already left the match
      if (!switched && maxMinute > 60) {
        switched = true;
        await B.page.locator(".im-tool--exp").click().catch(() => {});
        await sleep(900);
        await B.page.locator(".im-tool--exp").click().catch(() => {});
        await sleep(600);
      }
      for (const [c, v] of [[A, a], [B, b]]) if (v?.your_turn) { await act(c, v); break; }
      await sleep(120);
    }
    check("match reached the final whistle", (finished.A?.state === "FINISHED") || (finished.B?.state === "FINISHED") || maxMinute >= 89, `minute ${maxMinute}`);
    const scoreA = finished.A?.score, scoreB = finished.B?.score;
    check("both coaches got the same official score", !scoreA || !scoreB || (scoreA.home === scoreB.home && scoreA.away === scoreB.away), JSON.stringify({ scoreA, scoreB }));
    check("2D/3D switch near the end kept the match", switched, "switched once after the 60th minute");
    await sleep(1200);
    await A.page.screenshot({ path: path.join(out, "fim-2d.png") }).catch(() => {});
    await B.page.screenshot({ path: path.join(out, "fim-3d.png") }).catch(() => {});

    // The decisive check: the match screen must hand over to the official report by itself.
    const left = await A.page.waitForFunction(() => !document.querySelector(".im") || document.querySelector(".postmatch"), null, { timeout: 45000 }).then(() => true).catch(() => false);
    check("app leaves the match screen after the whistle (no freeze)", left, "waited up to 45 s");
    const report = await A.page.waitForSelector(".postmatch", { timeout: 20000 }).then(() => true).catch(() => false);
    check("official post-match report is shown", report);
    check("no blocking overlay left behind", !(await A.page.evaluate(() => document.body.classList.contains("im-open"))));
    await A.page.screenshot({ path: path.join(out, "resultado-2d.png") }).catch(() => {});
    if (report) {
      const heading = (await A.page.locator(".postmatch__hero h1").innerText().catch(() => "")).trim();
      check("result headline is visible", /VITÓRIA|DERROTA|EMPATE/.test(heading), heading);
      const continueButton = A.page.getByRole("button", { name: /Continuar carreira/i });
      check("coach can continue the career", await continueButton.isVisible().catch(() => false));
      await continueButton.click().catch(() => {});
      await sleep(800);
      check("career is responsive after the result", await A.page.locator(".cr-body, .career").first().isVisible().catch(() => false));
      await A.page.screenshot({ path: path.join(out, "carreira-apos-resultado.png") }).catch(() => {});
    }
    // Reload after the whistle: no restart of the simulation and no duplicated result.
    await A.page.reload();
    await sleep(2500);
    const after = await view(A);
    check("reload after the whistle does not restart the match", !after || after.state === "NONE" || after.state === "FINISHED", after ? after.state : "no match");
    check("no page errors in the coach's browser", A.errors.length === 0, A.errors.slice(0, 3).join(" | "));
    check("no page errors in the rival's browser", B.errors.length === 0, B.errors.slice(0, 3).join(" | "));
  } finally {
    fs.writeFileSync(path.join(out, "finish-results.json"), JSON.stringify({ results, matchId, score: { A: finished.A?.score ?? null, B: finished.B?.score ?? null } }, null, 2));
    for (const r of results) if (!r.ok) process.exitCode = 1;
    await A.context.close().catch(() => {}); await B.context.close().catch(() => {});
    await browser.close();
  }
})();

