// Creates a player through the real UI (Elenco > Criar jogador) and checks he is in the squad.
// node scripts/check-custom-player.cjs <state.json> <app> <api> <outDir>
const { chromium } = require("playwright");
const fs = require("node:fs");
(async () => {
  const [statePath, APP, API, out] = process.argv.slice(2);
  const state = JSON.parse(fs.readFileSync(statePath, "utf8"));
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ executablePath: "/usr/bin/google-chrome", headless: true, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  await context.addInitScript(([t, room]) => { localStorage.setItem("bm_session_token", t); localStorage.setItem("bm_active_room", room); }, [state.tokens[0], state.room_id]);
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto(APP);
  await page.getByRole("button", { name: /^Elenco$/i }).first().click();
  await page.getByRole("button", { name: /Criar jogador/ }).first().click();
  await page.waitForSelector(".cpf__form", { timeout: 30000 });
  await page.getByLabel("Nome").fill("Craque da Várzea");
  await page.locator(".cpf__positions label", { hasText: "MEI" }).click();
  const sliders = page.locator(".cpf__attr input[type=range]");
  for (let i = 0; i < await sliders.count(); i += 1) await sliders.nth(i).fill("72");
  const overall = await page.locator(".cpf__overall b").innerText();
  const select = page.locator(".cpf__field select");
  const options = await select.locator("option").allInnerTexts();
  await select.selectOption({ index: 1 });
  const replaced = options[1];
  await page.screenshot({ path: `${out}/criar-jogador-form.png`, fullPage: true });
  await page.getByRole("button", { name: /^Criar jogador$/ }).last().click();
  await page.waitForSelector(".cpf__ok, .cpf__error", { timeout: 15000 });
  const outcome = await page.locator(".cpf__ok, .cpf__error").first().innerText();
  await page.screenshot({ path: `${out}/criar-jogador-ok.png`, fullPage: true });
  const squad = await fetch(`${API}/rooms/${state.room_id}/squad`, { headers: { authorization: `Bearer ${state.tokens[0]}` } }).then((r) => r.json());
  const created = squad.data.players.find((p) => p.name === "Craque da Várzea");
  console.log(JSON.stringify({ preview_overall: overall, replaced, outcome, in_squad: Boolean(created), id: created?.id, server_overall: created?.overall, position: created?.position, errors }, null, 1));
  await browser.close();
})();
