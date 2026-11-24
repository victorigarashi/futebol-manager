// FIFA 14–16 migration: real screenshots of every main screen at desktop, tablet and phone sizes,
// with automatic checks (no horizontal page overflow, no console errors). Read-only on the game.
// node scripts/retro/sweep.cjs <states.json> <outDir> [sizes]
// states.json: { career, lobby, mercado, draft, pack, clube, fresh, anon } → each {room_id, tokens}
const fs = require("fs"), path = require("path");
const { chromium } = require("playwright");
const BASE = process.env.RETRO_URL || "http://localhost:5180";
const [statesFile, outDir, sizesArg = "1366x768,1600x900,1920x1080,820x1180,390x844,844x390"] = process.argv.slice(2);
const S = JSON.parse(fs.readFileSync(statesFile, "utf8"));
fs.mkdirSync(outDir, { recursive: true });
const nav = (name) => `await p.getByRole("button", { name: /^${name}$/ }).first().click(); await p.waitForTimeout(700);`;
const SCREENS = [
  ["01-onboarding", "anon", "", true],
  ["02-menu", "fresh", "", true],
  ["03-nova-liga", "fresh", `await p.getByRole("button", { name: /Nova carreira/ }).first().click(); await p.waitForTimeout(700);`, true],
  ["04-escolha-de-clube", "clube", ""],
  ["05-lobby", "lobby", ""],
  ["06-mercado-inicial", "mercado", ""],
  ["07-draft", "draft", ""],
  ["08-pack", "pack", ""],
  ["10-central", "career", ""],
  ["11-elenco-visao-geral", "career", nav("Elenco")],
  ["12-escalacao", "career", nav("Elenco") + nav("Escalação")],
  ["13-taticas", "career", nav("Elenco") + nav("Táticas")],
  ["14-mercado-carreira", "career", nav("Mercado")],
  ["15-calendario", "career", nav("Competições")],
  ["16-classificacao", "career", nav("Competições") + nav("Classificação")],
  ["17-estatisticas", "career", nav("Clube")],
  ["18-noticias", "career", nav("Clube") + nav("Notícias")],
  ["19-trofeus", "career", nav("Clube") + nav("Troféus")],
  ["20-configuracoes", "career", nav("Configurações")],
  ["21-pre-jogo", "career", `await p.getByRole("button", { name: /Próxima partida/ }).first().click(); await p.waitForTimeout(900);`],
];
const results = [];
(async () => {
  const b = await chromium.launch({ executablePath: "/usr/bin/google-chrome", headless: true, args: ["--no-sandbox", "--use-angle=gl"] });
  for (const size of sizesArg.split(",")) {
    const [w, h] = size.split("x").map(Number);
    const mobile = w < 900;
    for (const [name, key, steps, noRoom] of SCREENS) {
      const st = S[key]; if (!st) continue;
      const ctx = await b.newContext({ viewport: { width: w, height: h }, ...(mobile ? { isMobile: true, hasTouch: true, deviceScaleFactor: 2 } : {}) });
      await ctx.addInitScript(([t, r, nr]) => { localStorage.setItem("bm_session_token", t); if (nr) localStorage.removeItem("bm_active_room"); else { localStorage.setItem("bm_active_room", r); localStorage.setItem(`bm_tab_${r}`, "hub"); } }, [st.tokens[0], st.room_id, !!noRoom]);
      const p = await ctx.newPage();
      const errors = [];
      p.on("pageerror", (e) => errors.push(e.message));
      p.on("console", (m) => { if (m.type() === "error" && !/WebSocket|favicon|Failed to load resource/.test(m.text())) errors.push(m.text()); });
      let ok = true;
      try {
        await p.goto(BASE + "/"); await p.waitForTimeout(2200);
        if (steps) await new Function("p", `return (async () => { ${steps} })();`)(p);
        await p.waitForTimeout(500);
      } catch (e) { ok = false; errors.push("steps: " + e.message.split("\n")[0]); }
      const file = path.join(outDir, `${name}-${w}x${h}.png`);
      await p.screenshot({ path: file });
      const m = await p.evaluate(() => ({ overflowX: document.documentElement.scrollWidth > window.innerWidth + 1, legacy: Boolean(document.querySelector(".app-shell, .landing-shell")), retro: Boolean(document.querySelector(".rt, .rt-skin")) }));
      const row = { screen: name, size, ok: ok && !m.overflowX && !errors.length && !m.legacy, ...m, errors: errors.slice(0, 2) };
      results.push(row);
      console.log(`${row.ok ? "PASS" : "FAIL"} ${name} ${size}${m.overflowX ? " overflow-x" : ""}${m.legacy ? " legacy-shell" : ""}${errors.length ? " ERR " + errors[0].slice(0, 120) : ""}`);
      await ctx.close();
    }
  }
  await b.close();
  fs.writeFileSync(path.join(outDir, "sweep.json"), JSON.stringify({ date: new Date().toISOString(), results }, null, 2));
  console.log(`\n${results.filter((r) => r.ok).length}/${results.length} OK`);
})();
