// Retro Career UI: real screenshots of the running app (no mockups).
// node scripts/retro/capture.cjs <state.json> <outDir> <name> [who=0] [steps-js] [sizes=1366x768,1920x1080] [noRoom]
// state.json comes from backend/tools/career_acceptance.py ({room_id, tokens}).
const fs = require("fs"), path = require("path");
const { chromium } = require("playwright");
const BASE = process.env.RETRO_URL || "http://localhost:5180";
(async () => {
  const [stateFile, outDir, name, who = "0", steps = "", sizesArg = "1366x768,1920x1080", noRoom = ""] = process.argv.slice(2);
  const state = JSON.parse(fs.readFileSync(stateFile, "utf8"));
  fs.mkdirSync(outDir, { recursive: true });
  const b = await chromium.launch({ executablePath: "/usr/bin/google-chrome", headless: true, args: ["--no-sandbox", "--use-angle=gl"] });
  for (const size of sizesArg.split(",")) {
    const [w, h] = size.split("x").map(Number);
    const ctx = await b.newContext({ viewport: { width: w, height: h } });
    await ctx.addInitScript(([token, room, nr]) => { localStorage.setItem("bm_session_token", token); if (!nr) localStorage.setItem("bm_active_room", room); else localStorage.removeItem("bm_active_room"); }, [state.tokens[Number(who)], state.room_id, !!noRoom]);
    const p = await ctx.newPage();
    const errors = [];
    p.on("pageerror", (e) => errors.push(e.message));
    p.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
    await p.goto(BASE + "/");
    await p.waitForTimeout(2500);
    if (steps) { await new Function("p", `return (async () => { ${steps} })();`)(p); await p.waitForTimeout(900); }
    const file = path.join(outDir, `${name}-${w}.png`);
    await p.screenshot({ path: file });
    console.log(file, errors.length ? "ERRORS: " + errors.slice(0, 3).join(" | ") : "");
    await ctx.close();
  }
  await b.close();
})();
