// Retro Career — nostalgia gate: real screenshots + functional checks of the 3 approved screens.
// Needs: backend tools.career_acceptance on :8010 and the dev server on :5180.
// node scripts/retro/gate.cjs <state.json> [outDir=../docs/design/retro/gate] [lobby.json]
const fs = require("fs"), path = require("path");
const { chromium } = require("playwright");
const BASE = process.env.RETRO_URL || "http://localhost:5180";
const [stateFile, outArg, lobbyFile] = process.argv.slice(2);
const OUT = path.resolve(outArg || path.join(__dirname, "../../../docs/design/retro/gate"));
fs.mkdirSync(OUT, { recursive: true });
const state = JSON.parse(fs.readFileSync(stateFile, "utf8"));
const checks = [];
const check = (name, ok, detail = "") => { checks.push({ name, ok: !!ok, detail }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " — " + detail : ""}`); };
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

async function session(browser, who, size, opts = {}) {
  const ctx = await browser.newContext({ viewport: { width: size[0], height: size[1] }, ...(opts.mobile ? { isMobile: true, hasTouch: true, deviceScaleFactor: 2 } : {}) });
  await ctx.addInitScript(([t, r]) => { localStorage.setItem("bm_session_token", t); localStorage.setItem("bm_active_room", r); localStorage.setItem(`bm_tab_${r}`, "hub"); }, [state.tokens[who], state.room_id]);
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => { if (m.type() === "error" && !/WebSocket|favicon|Failed to load resource/.test(m.text())) errors.push(m.text()); });
  await page.goto(BASE + "/");
  await page.waitForSelector(".ch", { timeout: 20000 });
  await wait(1500);
  return { ctx, page, errors };
}
const shot = (page, name) => page.screenshot({ path: path.join(OUT, name) });
const noPageScroll = (page) => page.evaluate(() => document.documentElement.scrollHeight <= window.innerHeight + 2);

(async () => {
  const browser = await chromium.launch({ executablePath: "/usr/bin/google-chrome", headless: true, args: ["--no-sandbox", "--use-angle=gl"] });
  for (const size of [[1366, 768], [1920, 1080]]) {
    const tag = `${size[0]}`;
    const { ctx, page, errors } = await session(browser, 0, size);
    // ---------------- Central
    await shot(page, `02-central-${tag}.png`);
    check(`[${tag}] Central sem rolagem da página`, await noPageScroll(page));
    check(`[${tag}] Ação principal visível sem rolar`, await page.locator(".ch-advance .rt-btn").isVisible() && (await page.locator(".ch-advance").boundingBox()).y + 40 < size[1]);
    // keyboard: arrow navigation between tiles
    await page.locator(".ch-advance").focus();
    await page.keyboard.press("ArrowRight");
    const afterRight = await page.evaluate(() => document.activeElement?.closest(".ch-story") ? "story" : document.activeElement?.className);
    await page.keyboard.press("ArrowDown");
    const afterDown = await page.evaluate(() => (document.activeElement?.className || "").toString());
    check(`[${tag}] Setas movem o foco entre os tiles`, afterRight === "story" && /ch-(table|col|squad|money|next)/.test(afterDown), `${afterRight} → ${afterDown}`);
    await page.locator(".ch-next").focus(); await wait(150);
    await shot(page, `02b-central-foco-${tag}.png`);
    // ---------------- Squad hub (Elenco · visão geral), then the lineup editor (Escalação)
    await page.getByRole("button", { name: /^Elenco$/ }).click();
    await page.waitForSelector(".sh-xi");
    await wait(600);
    await shot(page, `03a-elenco-visao-geral-${tag}.png`);
    check(`[${tag}] Elenco abre a visão geral sem rolagem`, await noPageScroll(page));
    check(`[${tag}] Visão geral mostra os 11 titulares`, await page.locator(".sh-slot").count() === 11);
    await page.locator(".sh-xi").click();
    await page.waitForSelector(".sq-slot");
    await wait(600);
    await shot(page, `03-elenco-${tag}.png`);
    check(`[${tag}] Elenco sem rolagem da página`, await noPageScroll(page));
    const slots = await page.locator(".sq-slot").count();
    check(`[${tag}] Campo mostra os 11 titulares`, slots === 11, `${slots} vagas`);
    const overlap = await page.evaluate(() => {
      const r = Array.from(document.querySelectorAll(".sq-slot__name")).map((e) => e.getBoundingClientRect());
      let n = 0; for (let i = 0; i < r.length; i += 1) for (let j = i + 1; j < r.length; j += 1) if (r[i].left < r[j].right && r[j].left < r[i].right && r[i].top < r[j].bottom && r[j].top < r[i].bottom) n += 1;
      return n;
    });
    check(`[${tag}] Nomes no campo sem sobreposição`, overlap === 0, `${overlap} sobreposições`);
    await page.locator(".sq-slot").nth(6).click(); await wait(300);
    await shot(page, `03b-elenco-atleta-${tag}.png`);
    // Esc returns to Central
    await page.locator("body").click({ position: { x: 5, y: 5 } });
    await page.keyboard.press("Escape"); await wait(500);
    check(`[${tag}] Esc volta à Central`, await page.locator(".ch").isVisible());
    // ---------------- Main menu through the real "Menu" action, then Continue
    await page.getByRole("button", { name: /^Menu$/ }).click();
    await page.waitForSelector(".mm-home", { timeout: 10000 });
    await wait(900);
    await shot(page, `01-menu-${tag}.png`);
    check(`[${tag}] Menu mostra Continuar carreira com o clube`, await page.locator(".mm-hero").filter({ hasText: "Continuar carreira" }).isVisible() && await page.locator(".mm-hero .club-crest").count() > 0);
    check(`[${tag}] Menu sem rolagem da página`, await noPageScroll(page));
    await page.getByRole("button", { name: /^Jogar$/ }).click(); await wait(400);
    await shot(page, `01b-menu-jogar-${tag}.png`);
    check(`[${tag}] Aba Jogar lista os 5 modos reais`, await page.locator(".mm-mode").count() === 5);
    await page.keyboard.press("Escape"); await wait(300);
    check(`[${tag}] Esc volta ao Início do menu`, await page.locator(".mm-home").isVisible());
    await page.getByRole("button", { name: /^Online$/ }).click(); await wait(400);
    await shot(page, `01c-menu-online-${tag}.png`);
    await page.getByRole("button", { name: /^Início$/ }).click(); await wait(300);
    await page.locator(".mm-hero").click();
    await page.waitForSelector(".ch", { timeout: 10000 });
    check(`[${tag}] Continuar volta à carreira`, true);
    check(`[${tag}] Sem erros no console`, errors.length === 0, errors.slice(0, 2).join(" | "));
    await ctx.close();
  }
  // ---------------- Real swap saved and validated by the server (1366)
  {
    const { ctx, page } = await session(browser, 0, [1366, 768]);
    await page.getByRole("button", { name: /^Elenco$/ }).click();
    await page.getByRole("button", { name: /^Escalação$/ }).click();
    await page.waitForSelector(".sq-slot"); await wait(500);
    const before = await page.locator(".sq-slot").nth(5).getAttribute("aria-label");
    await page.locator(".sq-slot").nth(5).click(); await wait(150);
    await page.locator(".sq-card").first().click(); await wait(300);
    const dirty = await page.getByRole("button", { name: /Salvar escalação/ }).isEnabled();
    await shot(page, `03c-elenco-troca-${1366}.png`);
    await page.getByRole("button", { name: /Salvar escalação/ }).click();
    await page.waitForSelector(".rt-toast--ok", { timeout: 10000 }).catch(() => null);
    const toast = await page.locator(".sq-notices").innerText().catch(() => "");
    const after = await page.locator(".sq-slot").nth(5).getAttribute("aria-label");
    check("Troca titular ↔ reserva salva e validada pelo servidor", dirty && /validada pelo servidor|Escalação salva/.test(toast) && before !== after, `${before} → ${after}`);
    await shot(page, `03d-elenco-salvo-${1366}.png`);
    // undo: restore the auto lineup so the seed stays comparable
    await page.getByRole("button", { name: /Automática/ }).click(); await wait(200);
    if (await page.getByRole("button", { name: /Salvar escalação/ }).isEnabled()) { await page.getByRole("button", { name: /Salvar escalação/ }).click(); await wait(800); }
    await ctx.close();
  }
  // ---------------- Second coach on a phone (portrait): layout reorganises, nothing cut
  {
    const { ctx, page, errors } = await session(browser, 1, [390, 844], { mobile: true });
    await shot(page, `04-central-celular-rival.png`);
    const wide = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
    check("Celular: sem rolagem horizontal na Central", wide);
    await page.getByRole("button", { name: /^Elenco$/ }).click(); await wait(800);
    await shot(page, `04a-elenco-visao-geral-celular-rival.png`);
    check("Celular: sem rolagem horizontal na visão geral do elenco", await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1));
    await page.getByRole("button", { name: /^Escalação$/ }).click(); await wait(800);
    await shot(page, `04b-elenco-celular-rival.png`);
    check("Celular: sem rolagem horizontal no Elenco", await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1));
    const clipped = await page.evaluate(() => Array.from(document.querySelectorAll(".sq-slot")).filter((el) => { const r = el.getBoundingClientRect(), p = el.closest(".sq-left").getBoundingClientRect(); return r.left < p.left - 1 || r.right > p.right + 1; }).length);
    check("Celular: nenhum titular cortado pelo painel", clipped === 0, `${clipped} cortados`);
    const overlapM = await page.evaluate(() => { const r = Array.from(document.querySelectorAll(".sq-slot__name")).map((e) => e.getBoundingClientRect()); let n = 0; for (let i = 0; i < r.length; i += 1) for (let j = i + 1; j < r.length; j += 1) if (r[i].left < r[j].right && r[j].left < r[i].right && r[i].top < r[j].bottom && r[j].top < r[i].bottom) n += 1; return n; });
    check("Celular: nomes no campo sem sobreposição", overlapM === 0, `${overlapM} sobreposições`);
    check("Celular: sem erros no console", errors.length === 0, errors.slice(0, 2).join(" | "));
    await ctx.close();
  }
  // ---------------- Lobby (sala da liga) of a room still waiting: optional second state file
  if (lobbyFile) {
    const lobby = JSON.parse(fs.readFileSync(lobbyFile, "utf8"));
    for (const [size, mobile] of [[[1366, 768], false], [[1920, 1080], false], [[390, 844], true]]) {
      const ctx = await browser.newContext({ viewport: { width: size[0], height: size[1] }, ...(mobile ? { isMobile: true, hasTouch: true, deviceScaleFactor: 2 } : {}) });
      await ctx.addInitScript(([t, r]) => { localStorage.setItem("bm_session_token", t); localStorage.setItem("bm_active_room", r); }, [lobby.tokens[0], lobby.room_id]);
      const page = await ctx.newPage();
      const errors = [];
      page.on("pageerror", (e) => errors.push(e.message));
      page.on("console", (m) => { if (m.type() === "error" && !/WebSocket|favicon|Failed to load resource/.test(m.text())) errors.push(m.text()); });
      await page.goto(BASE + "/");
      await page.waitForSelector(".lb", { timeout: 20000 });
      await wait(1500);
      const tag = mobile ? "celular" : `${size[0]}`;
      await shot(page, `05-lobby-${tag}.png`);
      const start = page.getByRole("button", { name: /Começar a resenha/ });
      if (!mobile) {
        check(`[${tag}] Lobby sem rolagem da página`, await noPageScroll(page));
        const box = await start.boundingBox();
        check(`[${tag}] Lobby: iniciar visível sem rolar`, Boolean(box && box.y + box.height <= size[1]));
      } else check("Celular: lobby sem rolagem horizontal", await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1));
      check(`[${tag}] Lobby lista os participantes reais`, await page.locator(".lb .participant-card").count() === 3);
      check(`[${tag}] Lobby sem erros no console`, errors.length === 0, errors.slice(0, 2).join(" | "));
      await ctx.close();
    }
  }
  await browser.close();
  fs.writeFileSync(path.join(OUT, "checks.json"), JSON.stringify({ date: new Date().toISOString(), checks }, null, 2));
  const failed = checks.filter((c) => !c.ok).length;
  console.log(`\n${checks.length - failed}/${checks.length} verificações OK`);
})();
