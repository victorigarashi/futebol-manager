// Browser acceptance for the Draft mode.
// Usage: node scripts/verify-draft.cjs <frontend dir> <out dir> [app url] [api url]
const path = require("node:path");
const fs = require("node:fs");
const { chromium } = require(path.join(process.argv[2], "node_modules", "playwright"));
const out = process.argv[3];
const APP = process.argv[4] || "http://127.0.0.1:5174/";
const API = process.argv[5] || "http://127.0.0.1:8000/api/v1";
fs.mkdirSync(out, { recursive: true });
const results = [];
const log = (...args) => console.log(new Date().toISOString().slice(11, 19), ...args);
const check = (name, ok, detail = "") => { results.push({ name, ok: Boolean(ok), detail }); log(ok ? "PASS" : "FAIL", name, detail); };
const call = async (token, p, init = {}) => {
  const response = await fetch(API + p, { ...init, headers: { "content-type": "application/json", ...(token ? { authorization: `Bearer ${token}` } : {}), ...(init.headers || {}) } });
  return { status: response.status, body: await response.json() };
};

let guests = 0;
async function guest() {
  const { body } = await call(null, "/auth/guest", { method: "POST" });
  const token = body.data.session_token;
  guests += 1;
  const renamed = await call(token, "/me", { method: "PUT", body: JSON.stringify({ display_name: `Resenha ${guests}` }) });
  return renamed.body.data?.session_token ?? token;  // the name travels in a new signed token
}

(async () => {
  const [host, friend] = [await guest(), await guest()];
  const bad = await call(host, "/rooms", { method: "POST", body: JSON.stringify({ name: "Draft inviável", mode: "ELEVEN_A_SIDE", max_human_participants: 2, game_mode: "DRAFT", draft_min_overall: 80 }) });
  check("infeasible minimum overall is refused with a suggestion", bad.status === 422 && /viável/.test(bad.body.detail), bad.body.detail);
  const created = await call(host, "/rooms", { method: "POST", body: JSON.stringify({ name: "Draft dos parças", mode: "ELEVEN_A_SIDE", max_human_participants: 2, game_mode: "DRAFT", draft_catalog: "WORLD", draft_min_overall: 75, initial_market_duration_seconds: 600 }) });
  const room = created.body.data;
  check("draft room created with the world catalog", room.game_mode === "DRAFT" && room.draft_catalog === "WORLD");
  await call(friend, `/rooms/${room.id}/join`, { method: "POST" });
  await call(host, `/rooms/${room.id}/participants/me/club`, { method: "PUT", body: JSON.stringify({ club_code: "FLA" }) });
  await call(friend, `/rooms/${room.id}/participants/me/club`, { method: "PUT", body: JSON.stringify({ club_code: "PAL" }) });
  const started = await call(host, `/rooms/${room.id}/start`, { method: "POST" });
  check("start goes straight to the Draft phase", started.body.data.phase === "DRAFT");

  const browser = await chromium.launch({ executablePath: "/usr/bin/google-chrome", headless: true });
  const open = async (token, viewport) => {
    const context = await browser.newContext({ viewport });
    await context.addInitScript(([t, r]) => { localStorage.setItem("bm_session_token", t); localStorage.setItem("bm_active_room", r); }, [token, room.id]);
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
    await page.goto(APP);
    return { page, errors };
  };
  const desktop = await open(host, { width: 1440, height: 900 });
  const mobile = await open(friend, { width: 390, height: 844 });
  const page = desktop.page;
  try {
    await page.waitForSelector(".draft-page", { timeout: 20000 });
    check("draft page renders", true);
    await page.screenshot({ path: path.join(out, "01-draft-formations.png") });
    await page.getByRole("button", { name: /4-3-3/ }).click();
    await page.waitForSelector(".draft-pitch .draft-slot--open");
    check("formation shows 11 empty positions", await page.locator(".draft-pitch .draft-slot--open").count() === 11);
    await page.locator(".draft-pitch .draft-slot--open").first().click();
    await page.waitForSelector(".draft-offer .draft-card");
    const cards = page.locator(".draft-offer .draft-card");
    check("an offer has exactly three cards", await cards.count() === 3);
    const names = await page.locator(".draft-offer .draft-card__name").allTextContents();
    check("the three cards are different athletes", new Set(names).size === 3, names.join(" | "));
    check("world cards carry the editorial-rating notice", await page.locator(".draft-offer .draft-card__notice").count() === 3);
    await page.waitForTimeout(700);  // let the card entrance animation finish
    await page.screenshot({ path: path.join(out, "02-draft-offer.png") });
    const firstName = names[0];
    await cards.first().click();
    await page.waitForSelector(".draft-pitch .draft-slot--filled");
    check("the chosen card fills the position", await page.locator(".draft-pitch .draft-slot--filled").count() === 1);
    // Re-opening another slot and closing it keeps the same three cards (no re-roll).
    await page.locator(".draft-pitch .draft-slot--open").first().click();
    await page.waitForSelector(".draft-offer .draft-card");
    const before = await page.locator(".draft-offer .draft-card__name").allTextContents();
    await page.keyboard.press("Escape");
    await page.locator(".draft-pitch .draft-slot--open").first().click();
    await page.waitForSelector(".draft-offer .draft-card");
    const after = await page.locator(".draft-offer .draft-card__name").allTextContents();
    check("closing and reopening an offer shows the same cards", JSON.stringify(before) === JSON.stringify(after));
    await page.keyboard.press("Escape");
    check("rival progress is listed (bots already drafted)", await page.locator(".draft-progress li").count() >= 19);
    await mobile.page.waitForSelector(".draft-page", { timeout: 20000 });
    await mobile.page.screenshot({ path: path.join(out, "03-draft-mobile.png"), fullPage: true });
    const overflow = await mobile.page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    check("no horizontal scroll at phone width", overflow <= 1, `overflow=${overflow}`);
    await page.getByRole("button", { name: /Encerrar Draft agora/ }).click();
    await page.waitForFunction(() => !document.querySelector(".draft-page"), null, { timeout: 20000 });
    check("forcing completion moves the room to squad management", true);
    await page.screenshot({ path: path.join(out, "04-after-draft.png") });
    const squad = await call(host, `/rooms/${room.id}/squad`);
    const players = squad.body.data.players;
    check("drafted squad has 16 instances including the first pick", players.length === 16 && players.some((p) => p.name === firstName), firstName);
    check("no browser errors", desktop.errors.length === 0 && mobile.errors.length === 0, [...desktop.errors, ...mobile.errors].join(" | "));
  } catch (error) {
    check("unexpected failure", false, String(error));
    await page.screenshot({ path: path.join(out, "99-failure.png") });
  } finally {
    await browser.close();
    fs.writeFileSync(path.join(out, "results.json"), JSON.stringify(results, null, 2));
    const failed = results.filter((r) => !r.ok).length;
    log(`${results.length - failed}/${results.length} checks passed`);
    process.exit(failed ? 1 : 0);
  }
})();
