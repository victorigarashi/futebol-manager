// Captures the match-visual panel (Lab) against a server: shows whether external engines are listed.
// node scripts/capture-engine-notice.cjs <app> <out.png>
const { chromium } = require("playwright");
(async () => {
  const [APP, out] = process.argv.slice(2);
  const browser = await chromium.launch({ executablePath: "/usr/bin/google-chrome", headless: true, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto(APP + "#lab");
  const panel = page.locator(".xp").first();
  await panel.waitFor({ state: "visible", timeout: 30000 });
  await page.waitForTimeout(1500);
  await panel.screenshot({ path: out });
  const notice = await page.locator(".xp-ext").count();
  console.log(JSON.stringify({ app: APP, external_engine_notice: notice > 0, text: notice ? await page.locator(".xp-ext").innerText() : null, errors }));
  await browser.close();
})();
