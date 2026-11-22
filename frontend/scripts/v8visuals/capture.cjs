// V8 broadcast visuals: real captures of the Lab match (3D or 2D) at the moment a decision opens.
// node scripts/v8visuals/capture.cjs <outDir> <label> [3D|2D] [scenarios=BUILDUP,THROUGH,ONE_ON_ONE] [sizes=1672x941,1366x768] [format=ELEVEN_A_SIDE]
// Needs the Lab served (vite) with a backend. Read-only on the match: it only waits and screenshots.
const fs = require("fs"), path = require("path");
const { chromium } = require("playwright");
const APP = process.env.APP || "http://127.0.0.1:5185/";
const LABEL = { BUILDUP: "Construção pelo meio", COUNTER: "Contra-ataque", WING: "Ataque pela ponta", THROUGH: "Passe em profundidade", CROSS: "Cruzamento", REBOUND: "Chute de fora", ONE_ON_ONE: "Cara a cara", FREE_KICK: "Falta", PENALTY: "Pênalti" };
(async () => {
  const [out = "/tmp/v8v", label = "run", exp = "3D", scen = "BUILDUP,THROUGH,ONE_ON_ONE", sizes = "1672x941,1366x768", format = "ELEVEN_A_SIDE"] = process.argv.slice(2);
  fs.mkdirSync(out, { recursive: true });
  const b = await chromium.launch({ executablePath: "/usr/bin/google-chrome", headless: true, args: ["--no-sandbox", "--use-angle=gl", "--ignore-gpu-blocklist"] });
  for (const size of sizes.split(",")) {
    const [w, h] = size.split("x").map(Number);
    for (const kind of scen.split(",")) {
      const ctx = await b.newContext({ viewport: { width: w, height: h } });
      await ctx.addInitScript((e) => { localStorage.setItem("bm_match_experience", e); localStorage.setItem("bm_cam2d", "play"); localStorage.setItem("bm_quality", "high"); localStorage.setItem("bm_lab_engine", "v8"); }, exp);
      const p = await ctx.newPage();
      const errors = [];
      p.on("pageerror", (e) => errors.push(e.message));
      await p.goto(APP + "#lab");
      await p.getByRole("radio", { name: new RegExp(LABEL[kind]) }).first().click();
      await p.getByLabel("Formato").selectOption(format);
      await p.getByRole("button", { name: /Jogar cenário/ }).click();
      await p.waitForFunction(() => window.__bmMatch?.view()?.state === "DECISION", null, { timeout: 30000 }).catch(() => null);
      await p.waitForTimeout(1600);
      const file = path.join(out, `${label}-${exp}-${kind}-${w}.png`);
      await p.screenshot({ path: file });
      const info = await p.evaluate(() => ({ state: window.__bmMatch?.view()?.state, exp: window.__bmMatch?.experience() }));
      console.log(file, JSON.stringify(info), errors.length ? "ERR " + errors.slice(0, 2).join(" | ") : "");
      await ctx.close();
    }
  }
  await b.close();
})();
