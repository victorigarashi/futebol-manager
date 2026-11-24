// Full multiplayer match verification (backend: tools/interactive_acceptance.py), automated.
// Two real browsers play the same Modo Jogável semi-final to the END and beyond:
//   final whistle on both screens · post-game screen · official score/statistics · competition
//   record · back to the career centre · next round released (final drawn).
// Stress during the match: renderer switch 2D<->3D (SWITCH=1), coach offline during his
// attack (OFFLINE=1), reload right after a goal, duplicate action ids. Every event must be
// recorded exactly once (event ids, goals = score).
// Measures: real time per server state, driver (automation) time, action round-trip latency,
// FPS (rAF) and JS heap of each client. This is an AUTOMATED test, not a human evaluation.
// Usage: EXP_A=2D EXP_B=3D node scripts/verify-match-full.cjs <state.json> <out> <app> <api>
const path = require("node:path");
const fs = require("node:fs");
const { chromium } = require(path.join(__dirname, "..", "node_modules", "playwright"));
const state = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const out = process.argv[3] || "/tmp/match-full";
const APP = process.argv[4] || "http://127.0.0.1:5182/";
const API = process.argv[5] || "http://127.0.0.1:8021/api/v1";
fs.mkdirSync(out, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok: Boolean(ok), detail: String(detail) }); log(ok ? "PASS" : "FAIL", name, detail); };
const api = (p) => fetch(API + p, { headers: { authorization: `Bearer ${state.tokens[0]}` } }).then((r) => r.json()).then((r) => r.data).catch(() => null);

async function open(browser, token, exp, name) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 760 }, recordVideo: { dir: out, size: { width: 1280, height: 760 } } });
  await context.addInitScript(([t, room, e]) => {
    localStorage.setItem("bm_session_token", t); localStorage.setItem("bm_active_room", room);
    localStorage.setItem("bm_match_experience", e); localStorage.setItem("bm_playtest", "1");
    // FPS probe: frames per second of the page (sampled by the driver).
    let frames = 0; window.__fps = { frames: 0, t0: performance.now() };
    const tick = () => { frames += 1; window.__fps.frames = frames; requestAnimationFrame(tick); }; requestAnimationFrame(tick);
  }, [token, state.room_id, exp]);
  const page = await context.newPage();
  const c = { page, context, name, exp, actions: 0, rejected: 0, errors: [], latency: [], fps: [], heap: [], driverMs: 0, gestures: [], misses: 0 };
  page.on("pageerror", (e) => c.errors.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error" && !/ERR_ABORTED|401|net::/.test(m.text())) c.errors.push(m.text()); });
  page.on("requestfinished", (req) => { if (/\/season\/interactive\/actions$/.test(req.url())) { const t = req.timing(); c.latency.push(Math.round(t.responseEnd)); } });
  await page.goto(APP);
  return c;
}
const view = (c) => c.page.evaluate(() => (window.__bmMatch ? window.__bmMatch.view() : null)).catch(() => null);

async function act(c, v) {
  const t0 = Date.now();
  const o = v.opportunity, L = v.pitch.length, W = v.pitch.width;
  const dir = o.right === false ? -1 : 1;
  const ci = o.roster.findIndex((r) => r.id === o.carrier);
  const [cx, cy] = o.positions[ci];
  const x = cx * L, y = cy * W, goalX = dir > 0 ? L : 0;
  let tx, ty, power, key;
  if (Math.abs(goalX - x) < 24 || o.actions >= 3) { tx = goalX; ty = W / 2 + (Math.random() < 0.5 ? -2.6 : 2.6); power = 0.72; key = "5"; }
  else {
    const mates = o.roster.map((r, i) => [r, o.positions[i]]).filter(([r]) => r.team === "A" && r.role !== "GK" && r.id !== o.carrier)
      .map(([, p]) => [p[0] * L, p[1] * W]).filter((p) => Math.hypot(p[0] - x, p[1] - y) > 6 && Math.hypot(p[0] - x, p[1] - y) < 30)
      .sort((a, b) => (b[0] - x) * dir - (a[0] - x) * dir);
    const m = mates[0] || [x + dir * 10, y];
    tx = m[0] + dir * 2; ty = m[1]; power = Math.min(1, Math.max(0.12, Math.hypot(tx - x, ty - y) / 55)); key = "2";
  }
  const ux = tx - x, uy = ty - y, len = Math.hypot(ux, uy) || 1, dragM = Math.max(2, power * L * 0.4);
  let a = null, b = null;
  for (const shift of [0, 6, 12, -6, -12]) {
    const sx = cx + (dir * shift) / L;
    const pa = await c.page.evaluate(([px, py]) => window.__bmMatch.toClient(px, py), [sx, cy]);
    const pb = await c.page.evaluate(([px, py]) => window.__bmMatch.toClient(px, py), [sx + (ux / len) * dragM / L, cy + (uy / len) * dragM / W]);
    // Start the drag where the press really lands on the pitch input (not on the HUD/action bar).
    const onPitch = pa && pb && pa[1] > 0 && pa[1] < 760 && pa[0] > 0 && pa[0] < 1280
      && (await c.page.evaluate(([px, py]) => (document.elementFromPoint(px, py)?.className ?? "").includes("im-input"), pa));
    if (onPitch) { a = pa; b = pb; break; }
  }
  if (!a) { c.misses += 1; return; }
  await c.page.keyboard.press(key);
  await c.page.mouse.move(a[0], a[1]);
  await c.page.mouse.down();
  for (let k = 1; k <= 8; k += 1) { await c.page.mouse.move(a[0] + (b[0] - a[0]) * k / 8, a[1] + (b[1] - a[1]) * k / 8); await sleep(12); }
  await c.page.mouse.up();
  c.actions += 1;
  c.driverMs += Date.now() - t0;
  c.gestures.push(Date.now() - t0);
  await sleep(250);
  const feedback = await c.page.locator(".im-feedback").innerText().catch(() => "");
  if (feedback) { c.rejected += 1; log(c.name, "feedback:", feedback); }
}

async function sample(c) {
  const s = await c.page.evaluate(() => ({ frames: window.__fps?.frames ?? 0, heap: performance.memory ? performance.memory.usedJSHeapSize : null })).catch(() => null);
  if (!s) return;
  const now = Date.now();
  if (c.lastFps) c.fps.push(((s.frames - c.lastFps.frames) * 1000) / (now - c.lastFps.t));
  c.lastFps = { frames: s.frames, t: now };
  if (s.heap) c.heap.push(s.heap);
}

const pct = (arr, p) => { if (!arr.length) return null; const s = [...arr].sort((x, y) => x - y); return s[Math.min(s.length - 1, Math.floor((p / 100) * s.length))]; };
const mean = (arr) => (arr.length ? arr.reduce((x, y) => x + y, 0) / arr.length : null);

(async () => {
  const browser = await chromium.launch({ executablePath: "/usr/bin/google-chrome", headless: true, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
  const expA = process.env.EXP_A || "2D", expB = process.env.EXP_B || "3D";
  const A = await open(browser, state.tokens[0], expA, `A-${expA}`);
  const B = await open(browser, state.tokens[1], expB, `B-${expB}`);
  const timing = {};            // real seconds per official state (A's view)
  const events = new Map();     // event_id -> JSON (both clients)
  let duplicateConflict = 0;
  try {
    for (const c of [A, B]) {
      await c.page.waitForSelector(".career-head", { timeout: 30000 });
      await c.page.locator(".career-head__cta button").click();
      await c.page.waitForSelector(".matchup", { timeout: 30000 });
      await c.page.getByRole("button", { name: "Confirmar equipe" }).click();
    }
    for (const c of [A, B]) await c.page.waitForFunction(() => window.__bmMatch && window.__bmMatch.view() && window.__bmMatch.view().state !== "NONE", null, { timeout: 60000 });
    check("both coaches enter the same interactive match", true);
    const tStart = Date.now();
    let matchId = null, last = Date.now(), lastState = null, mismatches = 0, syncs = 0, maxMinute = 0;
    let switched = false, offlineDone = false, goalReloadDone = false, lastGoals = 0, finishedAt = null, dupSent = false;
    const final = { A: null, B: null };
    let lastSample = 0;
    while (Date.now() - tStart < 1500000) {
      let [va, vb] = await Promise.all([view(A), view(B)]);
      matchId = matchId || va?.match_id || vb?.match_id;
      if (va && va.match_id !== matchId) va = null;
      if (vb && vb.match_id !== matchId) vb = null;
      if (va) final.A = va;
      if (vb) final.B = vb;
      const now = Date.now();
      if (va) { if (lastState) timing[lastState] = (timing[lastState] || 0) + (now - last) / 1000; lastState = va.state; last = now; }
      for (const v of [va, vb]) for (const e of v?.events ?? []) {
        const k = JSON.stringify([e.kind, e.team, e.minute, e.player_id, e.outcome]);
        if (events.has(e.event_id) && events.get(e.event_id) !== k) duplicateConflict += 1;
        events.set(e.event_id, k);
      }
      if (now - lastSample > 4000) { lastSample = now; await sample(A); await sample(B); }
      if ((!va || va.state === "FINISHED") && (!vb || vb.state === "FINISHED") && (final.A?.state === "FINISHED" || final.B?.state === "FINISHED")) { finishedAt = Date.now(); break; }
      if (va && vb) {
        if (va.revision === vb.revision) { syncs += 1; if (va.score.home !== vb.score.home || va.score.away !== vb.score.away) mismatches += 1; }
        if (va.your_turn && vb.your_turn) mismatches += 1;
        maxMinute = Math.max(maxMinute, va.minute || 0);
        const goals = va.score.home + va.score.away;
        // Reload right after a goal (state must come back identical).
        if (!goalReloadDone && goals > lastGoals && goals > 0) {
          goalReloadDone = true;
          const before = va;
          await A.page.reload();
          await A.page.waitForFunction(() => window.__bmMatch && window.__bmMatch.view() && window.__bmMatch.view().state !== "NONE", null, { timeout: 60000 }).catch(() => {});
          const after = await view(A);
          check("reload right after a goal keeps score and clock", Boolean(after && after.score.home >= before.score.home && after.score.away >= before.score.away && after.minute >= before.minute - 0.5),
            `${before.score.home}:${before.score.away} ${before.minute.toFixed(1)}' → ${after?.score.home}:${after?.score.away} ${after?.minute?.toFixed(1)}'`);
        }
        lastGoals = goals;
        // Renderer switch in the middle of the match (presentation only).
        if (process.env.SWITCH && !switched && va.minute > 15) {
          switched = true;
          const rev = va.revision;
          await A.page.locator(".im-tool--exp").click();
          await sleep(2500);
          const after = await view(A);
          check(`switch ${A.exp}→${A.exp === "2D" ? "3D" : "2D"} mid-match keeps the state`, Boolean(after && after.revision >= rev && after.match_id === matchId), `rev ${rev} → ${after?.revision}`);
        }
        // Coach B offline during his own attack, back after 8 s (inside the 30 s grace).
        if (process.env.OFFLINE && !offlineDone && vb.your_turn && vb.minute > 30) {
          offlineDone = true;
          const opp = vb.opportunity?.id;
          await B.context.setOffline(true);
          await sleep(8000);
          await B.context.setOffline(false);
          await sleep(2500);
          const back = await view(B);
          check("coach offline during his attack resumes the same decision", Boolean(back && back.opportunity?.id === opp && (back.state === "DECISION" || back.state === "EXECUTING")), `${opp} → ${back?.opportunity?.id} ${back?.state}`);
        }
        // Duplicate action id: the second copy must never apply (server idempotency).
        if (!dupSent && va.your_turn && va.opportunity) {
          dupSent = true;
          const o = va.opportunity, ci = o.roster.findIndex((r) => r.id === o.carrier), d = o.right === false ? -1 : 1;
          const [px, py] = o.positions[ci];
          const payload = { action_id: "dup-" + o.id, opportunity_id: o.id, revision: va.revision, type: "PASS", x: Math.min(1, Math.max(0, px + d * 0.12)), y: py, power: 0.35 };
          const send = () => A.page.evaluate(([base, room, p]) => fetch(`${base}/rooms/${room}/season/interactive/actions`, { method: "POST", headers: { "content-type": "application/json", authorization: `Bearer ${localStorage.getItem("bm_session_token")}` }, body: JSON.stringify(p) }).then((r) => r.json()).catch((e) => ({ err: String(e) })), [API, state.room_id, payload]);
          const r1 = await send(), r2 = await send();
          if (r1?.detail && /desatualizado|decisão aberta/i.test(String(r1.detail))) {
            dupSent = false;   // the decision moved on between reading and sending (test race): try at the next one
          } else {
            check("duplicate action id applied once (ACCEPTED then DUPLICATE)", r1?.data?.status === "ACCEPTED" && r2?.data?.status === "DUPLICATE", `${r1?.data?.status ?? JSON.stringify(r1).slice(0, 120)} / ${r2?.data?.status ?? JSON.stringify(r2).slice(0, 120)}`);
          }
        }
        for (const [c, v] of [[A, va], [B, vb]]) if (v.your_turn) await act(c, v);
      }
      await sleep(250);
    }
    const fa = final.A, fb = final.B;
    check("competitive duration shown and enforced by the server", Boolean(fa?.duration?.mode === "LIMITED" && fa?.duration?.seconds), JSON.stringify(fa?.duration ?? null));
    check("final whistle on both screens (official state FINISHED)", fa?.state === "FINISHED" && fb?.state === "FINISHED", `${fa?.state} ${fa?.minute?.toFixed?.(1)}' / ${fb?.state} ${fb?.minute?.toFixed?.(1)}'`);
    check(`same official score on ${A.exp} and ${B.exp}`, Boolean(fa && fb && fa.score.home === fb.score.home && fa.score.away === fb.score.away), JSON.stringify(fa?.score));
    check("no divergence during the match", mismatches === 0, `${mismatches} in ${syncs} synchronised polls`);
    const goalsSeen = [...events.values()].filter((k) => JSON.parse(k)[0] === "GOAL").length;
    check("every event recorded exactly once (ids stable, goals = score)", duplicateConflict === 0 && (!fa || goalsSeen === fa.score.home + fa.score.away),
      `${events.size} events, ${goalsSeen} goals, conflicts ${duplicateConflict}`);
    check("both coaches played their own attacks", A.actions > 0 && B.actions > 0, `${A.exp}: ${A.actions} (${A.rejected} recusados), ${B.exp}: ${B.actions} (${B.rejected} recusados)`);
    await A.page.screenshot({ path: path.join(out, "fim-A.png") });
    await B.page.screenshot({ path: path.join(out, "fim-B.png") });
    // ---- after the whistle: the match screen must close into the post-game, for BOTH coaches
    const post = {};
    for (const c of [A, B]) {
      const t0 = Date.now();
      const ok = await c.page.waitForSelector(".postmatch", { timeout: 120000 }).then(() => true).catch(() => false);
      post[c.name] = { ok, s: (Date.now() - t0) / 1000 };
      const text = ok ? await c.page.locator(".postmatch__score strong").innerText().catch(() => "") : "";
      const stats = ok ? await c.page.locator(".postmatch").innerText().catch(() => "") : "";
      check(`${c.exp} (${c.name}) leaves the match into the post-game screen`, ok, `${post[c.name].s.toFixed(1)} s after the whistle`);
      const sc = fa ? `${fa.score.home}–${fa.score.away}` : "?";
      check(`${c.name} post-game shows the official score and statistics`, ok && text.replace(/\s/g, "") === sc && /Posse|Finaliza|Chutes/i.test(stats), `${text.replace(/\s/g, "")} vs ${sc}`);
      await c.page.screenshot({ path: path.join(out, `posjogo-${c.name}.png`) });
    }
    const season = await api(`/rooms/${state.room_id}/season`);
    const tie = season && Object.values(season.knockout?.ties ?? {}).find((t) => t.stage === "SF" && [t.high, t.low].includes(state.clubs[0]) && [t.high, t.low].includes(state.clubs[1]));
    check("result recorded in the competition", Boolean(tie && tie.winner && state.clubs.includes(tie.winner)), JSON.stringify(tie ? { tie: [tie.high, tie.low], winner: tie.winner } : null));
    const finalTie = season && Object.values(season.knockout?.ties ?? {}).find((t) => t.stage === "FINAL");
    check("next round released (final drawn by the server)", Boolean(finalTie), finalTie ? `${finalTie.high} × ${finalTie.low}` : "no final");
    for (const c of [A, B]) {
      await c.page.getByRole("button", { name: /Continuar carreira/ }).click().catch(() => {});
      const back = await c.page.waitForSelector(".career-head", { timeout: 30000 }).then(() => true).catch(() => false);
      check(`${c.name} back to the career centre`, back);
      await c.page.screenshot({ path: path.join(out, `central-${c.name}.png`) });
    }
    // ---- timing report
    const realMatch = finishedAt ? (finishedAt - tStart) / 1000 : null;
    const report = {
      engine: fa?.engine, renderers: [A.exp, B.exp], real_match_seconds: realMatch, seconds_per_state: Object.fromEntries(Object.entries(timing).map(([k, v]) => [k, Math.round(v)])),
      driver_misses: { [A.name]: A.misses, [B.name]: B.misses },
      driver: { [A.name]: { gestures: A.actions, mean_ms: Math.round(mean(A.gestures) ?? 0), total_s: Math.round(A.driverMs / 1000) }, [B.name]: { gestures: B.actions, mean_ms: Math.round(mean(B.gestures) ?? 0), total_s: Math.round(B.driverMs / 1000) } },
      action_latency_ms: { [A.name]: { p50: pct(A.latency, 50), p95: pct(A.latency, 95), n: A.latency.length }, [B.name]: { p50: pct(B.latency, 50), p95: pct(B.latency, 95), n: B.latency.length } },
      fps: { [A.name]: { p50: pct(A.fps, 50), p5: pct(A.fps, 5) }, [B.name]: { p50: pct(B.fps, 50), p5: pct(B.fps, 5) } },
      heap_mb: { [A.name]: Math.round((Math.max(...A.heap, 0)) / 1048576), [B.name]: Math.round((Math.max(...B.heap, 0)) / 1048576) },
      post_game_s: post, note: "Automated run, headless Chrome with SwiftShader (software rendering): FPS here is NOT a real-hardware measurement.",
    };
    fs.writeFileSync(path.join(out, "timing.json"), JSON.stringify(report, null, 2));
    log("timing", JSON.stringify(report));
  } catch (error) {
    check("flow completed without exceptions", false, String(error).slice(0, 300));
    await A.page.screenshot({ path: path.join(out, "zz-falha-a.png") }).catch(() => {});
    await B.page.screenshot({ path: path.join(out, "zz-falha-b.png") }).catch(() => {});
  }
  check(`no page errors (${A.name})`, A.errors.length === 0, A.errors.slice(0, 2).join(" | "));
  check(`no page errors (${B.name})`, B.errors.length === 0, B.errors.slice(0, 2).join(" | "));
  fs.writeFileSync(path.join(out, "results.json"), JSON.stringify(results, null, 2));
  await A.context.close(); await B.context.close();
  await browser.close();
  log(`${results.filter((r) => r.ok).length}/${results.length} checks passed`);
})();
