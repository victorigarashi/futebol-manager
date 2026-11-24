// Production-build check of the 2D sprite path: atlases load and recolour, three.js is not in
// the initial download of a 2D page. node scripts/check-sprites-2d.cjs <app> <out>
const { chromium } = require("playwright");
const APP = process.argv[2], out = process.argv[3];
(async () => {
  const browser = await chromium.launch({ executablePath: "/usr/bin/google-chrome", headless: true, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
  const context = await browser.newContext({ viewport: { width: 1280, height: 760 } });
  await context.addInitScript(() => { localStorage.setItem("bm_match_experience", "2D"); localStorage.setItem("bm_lab_engine", "v8"); });
  const page = await context.newPage();
  const js = [], errors = [];
  page.on("requestfinished", (r) => { if (/\.js$/.test(r.url())) js.push(r.url().split("/").pop()); });
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  await page.goto(APP);
  await page.waitForTimeout(2500);
  const homeJs = [...js];
  await page.goto(APP + "#lab");
  await page.getByRole("radio", { name: /Construção pelo meio/ }).first().click();
  await page.getByRole("button", { name: /Jogar cenário/ }).click();
  await page.waitForFunction(() => window.__bmMatch && window.__bmMatch.view(), null, { timeout: 30000 });
  let status = null;
  for (let i = 0; i < 40; i += 1) {
    status = await page.evaluate(() => (window.__bmSprites ? window.__bmSprites() : null));
    if (status && status.sheets > 0 && Object.values(status.banks).every((b) => b === "ready")) break;
    await page.waitForTimeout(500);
  }
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${out}/sprites-2d-prod.png` });
  const result = { initial_js: homeJs, lab_js: js.filter((x) => !homeJs.includes(x)), sprites: status, errors };
  console.log(JSON.stringify(result, null, 1));
  await browser.close();
})();
