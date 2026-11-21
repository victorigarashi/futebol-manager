// Football Lab: one screenshot of the dev lab (node shot.cjs "<hash>" out.png ["js to eval"] [waitMs] [WxH]).
// The lab must be served: npx vite --port 5190 (see docs/research/football-lab/README.md).
const { chromium } = require("playwright");
const { launch, BASE } = require("./browser.cjs");
(async () => {
  const [hash = "tab=characters", out = "shot.png", js = "", wait = "1500", size = "1280x760"] = process.argv.slice(2);
  const [w, h] = size.split("x").map(Number);
  const browser = await launch(chromium);
  const page = await browser.newPage({ viewport: { width: w, height: h } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  await page.goto(`${BASE}/football-lab.html#${hash}`);
  await page.waitForFunction(() => document.body.dataset.ready === "1", null, { timeout: 30000 }).catch((e) => { console.log("ERRORS:", errors.join("\n")); throw e; });
  await page.waitForTimeout(600);
  if (js) console.log("eval:", JSON.stringify(await page.evaluate(js)));
  await page.waitForTimeout(Number(wait));
  await page.screenshot({ path: out });
  if (errors.length) console.log("ERRORS:\n" + errors.join("\n"));
  await browser.close();
})();
