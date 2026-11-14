// Browser acceptance for the career mode. Usage: node career-e2e.cjs <frontend dir> <state.json> <out dir>
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
const api = (token, p, init = {}) => fetch(API + p, { ...init, headers: { "content-type": "application/json", authorization: `Bearer ${token}`, ...(init.headers || {}) } }).then((r) => r.json());

async function open(browser, token, viewport, name) {
  const context = await browser.newContext({ viewport, deviceScaleFactor: 1 });
  await context.addInitScript(([t, room]) => { localStorage.setItem("bm_session_token", t); localStorage.setItem("bm_active_room", room); }, [token, state.room_id]);
  const page = await context.newPage();
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto(APP);
  return { page, errors, name };
}
const shot = (page, file) => page.screenshot({ path: path.join(out, file), fullPage: false });

(async () => {
  const browser = await chromium.launch({ executablePath: "/usr/bin/google-chrome", headless: true });
  const host = await open(browser, state.tokens[0], { width: 1440, height: 900 }, "host");
  const rival = await open(browser, state.tokens[1], { width: 390, height: 844 }, "rival");
  const { page } = host;
  try {
    await page.waitForSelector(".career-head", { timeout: 20000 });
    await page.getByRole("button", { name: /Central/ }).click();
    await page.waitForSelector(".hub-next");
    check("hub shows next match and table", await page.locator(".hub-next .hub-next__teams").count() === 1 && await page.locator(".mini-table li").count() > 0);
    await shot(page, "01-central.png");

    await page.getByRole("button", { name: /^▦?Elenco/ }).click();
    await page.waitForSelector(".formation-pitch .slot");
    const slots = await page.locator(".formation-pitch .slot").count();
    check("lineup shows 11 slots", slots === 11, String(slots));
    await page.locator(".formation-pitch .slot").nth(5).click();
    await page.locator(".bench-item").first().click();
    await page.getByRole("button", { name: "Salvar escalação" }).click();
    await page.waitForSelector(".cm-toast:has-text('validada pelo servidor')", { timeout: 8000 });
    check("lineup swap saved and validated by server", true);
    await page.locator(".formation-pitch .slot").nth(2).click();
    await page.waitForSelector(".player-sheet .attr-list li");
    await shot(page, "02-escalacao.png");
    await page.locator(".formation-pitch .slot").nth(2).click();

    await page.getByRole("button", { name: /Táticas/ }).click();
    await page.locator(".tactic-card", { hasText: "Ofensiva" }).first().click();
    await page.waitForSelector(".cm-toast:has-text('Plano de jogo salvo')", { timeout: 8000 });
    check("tactics saved", true);
    await shot(page, "03-taticas.png");

    await page.getByRole("button", { name: /Próxima partida/ }).click();
    await page.waitForSelector(".matchup");
    await shot(page, "04-pre-jogo.png");
    await page.getByRole("button", { name: "Confirmar equipe" }).click();
    await page.waitForSelector("button:has-text('✓ Pronto')", { timeout: 8000 });
    check("host confirmed readiness", true);

    // Lineup change after confirming cancels readiness, then confirm again.
    await page.getByRole("button", { name: /^▦?Elenco/ }).click();
    await page.locator(".formation-pitch .slot").nth(6).click();
    await page.locator(".bench-item").nth(1).click();
    await page.getByRole("button", { name: "Salvar escalação" }).click();
    await page.waitForSelector(".cm-toast:has-text('prontidão foi cancelada')", { timeout: 8000 });
    check("changing lineup cancels readiness", true);
    await page.getByRole("button", { name: /Próxima partida/ }).click();
    await page.getByRole("button", { name: "Confirmar equipe" }).click();
    await page.waitForSelector("button:has-text('✓ Pronto')", { timeout: 8000 });

    // Rival on a phone.
    const r = rival.page;
    await r.waitForSelector(".career-head", { timeout: 20000 });
    await shot(r, "05-mobile-central.png");
    await r.getByRole("button", { name: /Próxima partida/ }).click();
    await r.waitForSelector(".matchup");
    await shot(r, "06-mobile-pre-jogo.png");
    await r.getByRole("button", { name: "Confirmar equipe" }).click();

    await page.waitForSelector(".match-center", { timeout: 20000 });
    const intro = await page.locator(".pitch-overlay--intro").count();
    check("match presentation shown before kick-off", intro === 1);
    await shot(page, "07-apresentacao.png");
    await page.waitForSelector(".scorebug__status--first_half", { timeout: 20000 });
    await page.waitForTimeout(7000);
    await shot(page, "08-ao-vivo.png");

    // Two coaches: compare authoritative state from the server.
    const [a, b] = await Promise.all([api(state.tokens[0], `/rooms/${state.room_id}/season/live`), api(state.tokens[1], `/rooms/${state.room_id}/season/live`)]);
    const ids = (v) => v.data.match.events.map((e) => e.event_id).join(",");
    check("both coaches watch the same match", a.data.match.id === b.data.match.id, a.data.match.id);
    check("same score and event stream (prefix)", ids(a).startsWith(ids(b)) || ids(b).startsWith(ids(a)), `${a.data.match.home_goals}-${a.data.match.away_goals}`);

    await page.locator(".tactic-row button", { hasText: "Muito of." }).click();
    await page.waitForSelector(".cm-toast:has-text('Nova orientação')", { timeout: 8000 });
    check("live tactic change applied", true);
    await page.locator(".sub-list button").nth(6).click();
    await page.locator(".sub-picker .sub-list button").first().click();
    await page.waitForSelector(".compare");
    await shot(page, "09-substituicao.png");
    await page.getByRole("button", { name: "Confirmar substituição" }).click();
    await page.waitForSelector(".cm-toast:has-text('Substituição')", { timeout: 8000 });
    check("substitution requested", true, await page.locator(".cm-toast").first().innerText());
    await page.waitForSelector(".decisions .badge--applied", { timeout: 40000 }).then(() => check("substitution applied at a stoppage", true)).catch(() => check("substitution applied at a stoppage", false));
    await shot(r, "10-mobile-ao-vivo.png");

    const goal = await page.waitForSelector(".goal-overlay", { timeout: 60000 }).then(() => true).catch(() => false);
    if (goal) { await page.waitForTimeout(450); await shot(page, "11-gol.png"); }
    check("goal celebration appeared (if a goal happened)", true, goal ? "goal seen" : "no goal in window");

    await page.waitForSelector(".pitch-overlay--half", { timeout: 90000 });
    check("half-time screen", true);
    await shot(page, "12-intervalo.png");
    await page.getByRole("button", { name: "Estatísticas", exact: true }).click();
    await shot(page, "13-estatisticas.png");
    await page.getByRole("button", { name: "Lances", exact: true }).click();
    await shot(page, "14-lances.png");
    await page.getByRole("button", { name: "Técnico", exact: true }).click();

    await page.waitForSelector(".postmatch", { timeout: 150000 });
    check("post-match report after full time", true);
    await page.waitForSelector(".postmatch .ratings li");
    await shot(page, "15-pos-jogo.png");
    await page.screenshot({ path: path.join(out, "15b-pos-jogo-completo.png"), fullPage: true });
    await r.waitForSelector(".postmatch", { timeout: 30000 });
    const hostScore = await page.locator(".postmatch__score strong").innerText();
    const rivalScore = await r.locator(".postmatch__score strong").innerText();
    check("both coaches see the same final score", hostScore === rivalScore, `${hostScore} / ${rivalScore}`);
    await shot(r, "16-mobile-pos-jogo.png");
    await page.getByRole("button", { name: /Continuar carreira/ }).click();
    await page.waitForSelector(".hub-next");
    const season = await api(state.tokens[0], `/rooms/${state.room_id}/season`);
    check("round 2 open and table updated", season.data.current_round === 2 && season.data.table.every((row) => row.played === 1));
    await shot(page, "17-central-rodada-2.png");
    await page.getByRole("button", { name: /Temporada/ }).click();
    await shot(page, "18-temporada.png");
  } catch (error) {
    check("flow completed without exceptions", false, String(error).slice(0, 300));
    await shot(page, "zz-falha-host.png").catch(() => {});
    await shot(rival.page, "zz-falha-rival.png").catch(() => {});
  }
  check("no console errors (host)", host.errors.length === 0, host.errors.slice(0, 3).join(" | "));
  check("no console errors (rival)", rival.errors.length === 0, rival.errors.slice(0, 3).join(" | "));
  fs.writeFileSync(path.join(out, "results.json"), JSON.stringify(results, null, 2));
  await browser.close();
  log(`${results.filter((r) => r.ok).length}/${results.length} checks passed`);
})();
