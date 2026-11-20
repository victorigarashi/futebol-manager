// Browser acceptance for knockouts (backend: tools/knockout_acceptance.py).
// Usage: node scripts/verify-knockout.cjs <frontend dir> <state.json> <out dir>
// Two coaches in the same semi-final of a 4-club knockout: the loser must watch the
// final as a spectator (the situation that used to freeze the competition), with a
// reconnection in the middle of the final, and a champion at the end — no manual unlock.
const path = require("node:path");
const fs = require("node:fs");
const { chromium } = require(path.join(process.argv[2], "node_modules", "playwright"));
const state = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const out = process.argv[4];
fs.mkdirSync(out, { recursive: true });
const APP = "http://127.0.0.1:5174/";
const API = "http://127.0.0.1:8000/api/v1";
const log = (...args) => console.log(new Date().toISOString().slice(11, 19), ...args);
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok: Boolean(ok), detail }); log(ok ? "PASS" : "FAIL", name, detail); };
const api = (token, p) => fetch(API + p, { headers: { authorization: `Bearer ${token}` } }).then((r) => r.json());
const season = () => api(state.tokens[0], `/rooms/${state.room_id}/season`).then((r) => r.data);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function open(browser, token, viewport, name) {
  const context = await browser.newContext({ viewport, deviceScaleFactor: 1 });
  await context.addInitScript(([t, room]) => { localStorage.setItem("bm_session_token", t); localStorage.setItem("bm_active_room", room); }, [token, state.room_id]);
  const page = await context.newPage();
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error" && !/ERR_ABORTED|net::ERR_NETWORK_CHANGED/.test(m.text())) errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto(APP);
  return { page, errors, name };
}
const shot = (page, file) => page.screenshot({ path: path.join(out, file), fullPage: false });
async function acknowledgeReport(page) {
  const button = page.getByRole("button", { name: /Continuar carreira/ });
  if (await button.count()) await button.first().click();
}
async function waitFor(fn, timeout, every = 1000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) { const value = await fn(); if (value) return value; await sleep(every); }
  return null;
}

(async () => {
  const browser = await chromium.launch({ executablePath: "/usr/bin/google-chrome", headless: true });
  const a = await open(browser, state.tokens[0], { width: 1440, height: 900 }, "A");
  const b = await open(browser, state.tokens[1], { width: 390, height: 844 }, "B");
  try {
    for (const coach of [a, b]) {
      await coach.page.waitForSelector(".career-head", { timeout: 20000 });
      await coach.page.locator(".career-head__cta button").click();
      await coach.page.waitForSelector(".matchup", { timeout: 20000 });
    }
    check("both coaches see their semi-final", true, state.clubs.join(" × "));
    await shot(a.page, "01-semifinal-prejogo.png");
    for (const coach of [a, b]) {
      await coach.page.getByRole("button", { name: "Confirmar equipe" }).click();
    }
    const live = await waitFor(async () => (await season()).live_round, 20000);
    check("semi-final starts when both confirm", Boolean(live), live?.label);
    await a.page.waitForSelector(".match-center", { timeout: 30000 });
    await b.page.waitForSelector(".match-center", { timeout: 30000 });
    await shot(a.page, "02-semifinal-ao-vivo.png");
    const afterSemi = await waitFor(async () => { const s = await season(); return !s.live_round && Object.values(s.knockout.ties).find((t) => t.stage === "SF" && t.high === state.clubs[0])?.winner ? s : null; }, 150000, 2000);
    check("semi-final ends with a winner (penalties if level)", Boolean(afterSemi));
    const tie = Object.values(afterSemi.knockout.ties).find((t) => t.stage === "SF" && (t.high === state.clubs[0] || t.low === state.clubs[0]));
    const winnerIndex = state.clubs.indexOf(tie.winner);
    const winner = winnerIndex === 0 ? a : b;
    const loser = winnerIndex === 0 ? b : a;
    check("final drawn by the server (no click)", Boolean(Object.values(afterSemi.knockout.ties).find((t) => t.stage === "FINAL")));
    await sleep(2500);
    await acknowledgeReport(loser.page);
    await acknowledgeReport(winner.page);
    await loser.page.locator(".career-head__cta button").click();
    const waiting = await loser.page.waitForSelector(".prematch--blocked", { timeout: 20000 }).then(() => loser.page.locator(".prematch--blocked").innerText()).catch(() => "");
    check("eliminated coach sees that the final starts by itself", /começa sozinha/.test(waiting), waiting.replace(/\s+/g, " ").slice(0, 140));
    await shot(loser.page, "03-eliminado-aguardando.png");
    await winner.page.locator(".career-head__cta button").click();
    await winner.page.waitForSelector(".matchup", { timeout: 20000 });
    await winner.page.getByRole("button", { name: "Confirmar equipe" }).click();
    const finalLive = await waitFor(async () => (await season()).live_round, 20000);
    check("final starts when the only coach playing it confirms", Boolean(finalLive), finalLive?.label);
    await loser.page.waitForSelector(".match-center", { timeout: 30000 });
    const banner = await loser.page.locator(".pitch-banner--info").innerText().catch(() => "");
    check("eliminated coach watches the final as a spectator", /assistindo/.test(banner), banner);
    check("spectator has no coach controls", await loser.page.getByRole("button", { name: "Técnico" }).count() === 0);
    await shot(loser.page, "04-espectador-final.png");
    await loser.page.reload();
    await loser.page.waitForSelector(".match-center", { timeout: 30000 });
    check("spectator view survives a reload in the middle of the final", true);
    const done = await waitFor(async () => { const s = await season(); return s.champion ? s : null; }, 150000, 2000);
    check("tournament crowns a champion", Boolean(done), done?.champion);
    await sleep(3000);
    await acknowledgeReport(winner.page);
    await winner.page.getByRole("button", { name: /Competições/ }).click();
    await sleep(1500);
    await shot(winner.page, "05-campeao.png");
    check("champion shown in the competition area", /campe/i.test(await winner.page.locator(".career-body").innerText()));
  } catch (error) {
    check("flow completed without exceptions", false, String(error).slice(0, 300));
    await shot(a.page, "zz-falha-a.png").catch(() => {});
    await shot(b.page, "zz-falha-b.png").catch(() => {});
  }
  check("no console errors (A)", a.errors.length === 0, a.errors.slice(0, 3).join(" | "));
  check("no console errors (B)", b.errors.length === 0, b.errors.slice(0, 3).join(" | "));
  fs.writeFileSync(path.join(out, "results.json"), JSON.stringify(results, null, 2));
  await browser.close();
  log(`${results.filter((r) => r.ok).length}/${results.length} checks passed`);
})();
