// V8 HUD: the strip just above the action bar must hit the pitch input (.im-input), never a HUD element.
// node scripts/v8visuals/hud-check.cjs
const { chromium } = require("playwright");
const APP = process.env.APP || "http://127.0.0.1:5185/";
(async () => {
  const b = await chromium.launch({ executablePath: "/usr/bin/google-chrome", headless: true, args: ["--no-sandbox", "--use-angle=gl", "--ignore-gpu-blocklist"] });
  let fail = 0;
  for (const exp of ["3D", "2D"]) for (const [w, h] of [[1672, 941], [1366, 768], [390, 844]]) {
    const ctx = await b.newContext({ viewport: { width: w, height: h } });
    await ctx.addInitScript((e) => { localStorage.setItem("bm_match_experience", e); localStorage.setItem("bm_lab_engine", "v8"); }, exp);
    const p = await ctx.newPage();
    await p.goto(APP + "#lab");
    await p.getByRole("radio", { name: /Construção/ }).first().click();
    await p.getByRole("button", { name: /Jogar cenário/ }).click();
    await p.waitForFunction(() => window.__bmMatch?.view()?.state === "DECISION", null, { timeout: 30000 }).catch(() => null);
    await p.waitForTimeout(800);
    const r = await p.evaluate(() => {
      const bar = document.querySelector(".im-actions").getBoundingClientRect();
      const bad = [];
      for (let dy = 8; dy <= 120; dy += 16) for (let x = bar.left; x <= bar.right; x += 24) {
        const el = document.elementFromPoint(x, bar.top - dy);
        if (!el || !el.closest(".im-input")) bad.push(`${Math.round(x)},${Math.round(bar.top - dy)}:${el?.className}`);
      }
      return bad;
    });
    console.log(`${exp} ${w}x${h}: ${r.length ? "FAIL " + r.slice(0, 3).join(" ") : "PASS"}`);
    if (r.length) fail += 1;
    await ctx.close();
  }
  await b.close();
  process.exitCode = fail ? 1 : 0;
})();
