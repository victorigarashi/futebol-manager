// V8 broadcast visuals: frames per second of the Lab match in 3D (rAF count over 5 s) per quality.
// node scripts/v8visuals/fps.cjs [scenario label regex=Construção] [size=1672x941]
const { chromium } = require("playwright");
const APP = process.env.APP || "http://127.0.0.1:5185/";
(async () => {
  const [scen = "Construção", size = "1672x941"] = process.argv.slice(2);
  const [w, h] = size.split("x").map(Number);
  const b = await chromium.launch({ executablePath: "/usr/bin/google-chrome", headless: true, args: ["--no-sandbox", "--use-angle=gl", "--ignore-gpu-blocklist"] });
  for (const q of ["low", "medium", "high"]) {
    const ctx = await b.newContext({ viewport: { width: w, height: h } });
    await ctx.addInitScript((qq) => { localStorage.setItem("bm_match_experience", "3D"); localStorage.setItem("bm_quality", qq); localStorage.setItem("bm_lab_engine", "v8"); }, q);
    const p = await ctx.newPage();
    await p.goto(APP + "#lab");
    await p.getByRole("radio", { name: new RegExp(scen) }).first().click();
    await p.getByRole("button", { name: /Jogar cenário/ }).click();
    await p.waitForFunction(() => window.__bmMatch?.view()?.state === "DECISION", null, { timeout: 30000 }).catch(() => null);
    await p.waitForTimeout(1500);
    const fps = await p.evaluate(() => new Promise((res) => { let n = 0; const t0 = performance.now(); const tick = () => { n += 1; if (performance.now() - t0 < 5000) requestAnimationFrame(tick); else res(n / ((performance.now() - t0) / 1000)); }; requestAnimationFrame(tick); }));
    const gl = await p.evaluate(() => { const c = document.querySelector(".im-3d canvas"); return Boolean(c); });
    console.log(`${q}\t${fps.toFixed(1)} fps\tcanvas3d=${gl}`);
    await ctx.close();
  }
  await b.close();
})();
