// Plays Lab scenarios using ONLY the keyboard (no mouse/touch on the pitch) and checks that the
// server applied the coach's actions. node scripts/keyboard-play.cjs <app> <outDir> [2D|3D] [scenarios]
const { chromium } = require("playwright");
const fs = require("node:fs");
(async () => {
  const [APP, out, exp = "2D", list = "Construção pelo meio,Contra-ataque"] = process.argv.slice(2);
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ executablePath: "/usr/bin/google-chrome", headless: true, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
  const report = [];
  for (const scenario of list.split(",")) {
    const context = await browser.newContext({ viewport: { width: 1280, height: 760 }, recordVideo: { dir: out, size: { width: 1280, height: 760 } } });
    await context.addInitScript((e) => { localStorage.setItem("bm_match_experience", e); localStorage.setItem("bm_lab_engine", "v8"); }, exp);
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    await page.goto(APP + "#lab");
    await page.getByRole("radio", { name: new RegExp(scenario) }).first().click();
    await page.getByRole("button", { name: /Jogar cenário/ }).click();
    await page.waitForFunction(() => window.__bmMatch && window.__bmMatch.view(), null, { timeout: 30000 });
    const keys = [];
    const t0 = Date.now();
    let shots = 0;
    while (Date.now() - t0 < 90000) {
      const v = await page.evaluate(() => window.__bmMatch.view());
      if (!v || v.opportunity?.status !== "LIVE" && v.state !== "DECISION" && v.state !== "EXECUTING" && v.state !== "CLOCK") break;
      if (v.your_turn && v.state === "DECISION") {
        // Near the goal: aim with the arrows at goal and shoot (5 = shot); otherwise Tab to a mate.
        const o = v.opportunity, i = o.roster.findIndex((p) => p.id === o.carrier), x = o.positions[i][0];
        const near = o.right === false ? x < 0.25 : x > 0.75;
        const seq = near || o.actions >= 4 ? ["5", "ArrowUp", "ArrowUp", "Enter"] : ["Tab", "Enter"];
        for (const k of seq) { await page.keyboard.press(k); keys.push(k); await page.waitForTimeout(120); }
        if (seq[0] === "5") shots += 1;
        await page.waitForTimeout(400);
      } else {
        await page.waitForTimeout(250);
      }
      if (v.opportunity && v.opportunity.status !== "LIVE" && v.state !== "DECISION") break;
    }
    await page.waitForTimeout(1500);
    await page.screenshot({ path: `${out}/teclado-${exp}-${scenario.split(" ")[0]}.png` });
    const fin = await page.evaluate(() => window.__bmMatch.view());
    const steps = fin?.opportunity?.replay ?? [];
    const last = fin?.opportunity?.last;
    report.push({ scenario, renderer: exp, keys_pressed: keys.length, keys: keys.join(" "), result: fin?.opportunity?.result, status: fin?.opportunity?.status,
      actions_applied: fin?.opportunity?.actions, last_by: last?.by ?? null, shots_attempted: shots, page_errors: errors });
    await context.close();
  }
  console.log(JSON.stringify(report, null, 1));
  await browser.close();
})();
