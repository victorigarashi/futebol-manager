// Football Lab evidence: real screenshots, videos and benchmarks of the running prototypes.
// Usage: (lab served on :5190) node scripts/football-lab/evidence.cjs [only=section,section]
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");
const { launch, BASE } = require("./browser.cjs");
const OUT = path.resolve(__dirname, "../../../docs/research/football-lab/evidence");
fs.mkdirSync(OUT, { recursive: true });
const only = (process.argv.find((a) => a.startsWith("only=")) || "").slice(5).split(",").filter(Boolean);
const want = (s) => !only.length || only.includes(s);
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

async function open(browser, hash, { video = null, size = [1280, 760] } = {}) {
  const ctx = await browser.newContext({ viewport: { width: size[0], height: size[1] }, ...(video ? { recordVideo: { dir: OUT, size: { width: size[0], height: size[1] } } } : {}) });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(`${BASE}/football-lab.html#${hash}`);
  await page.waitForFunction(() => document.body.dataset.ready === "1", null, { timeout: 30000 });
  await wait(500);
  return { ctx, page, errors, async close(name) { await ctx.close(); if (video) { const v = await page.video().path(); fs.renameSync(v, path.join(OUT, name)); } if (errors.length) console.log(`  ! ${name}: ${errors.join(" | ")}`); } };
}
const shot = async (page, name) => { await page.screenshot({ path: path.join(OUT, name) }); console.log("  shot", name); };

(async () => {
  const browser = await launch(chromium);
  if (want("characters")) {
    const s = await open(browser, "tab=characters");
    await wait(800); await shot(s.page, "01-atletas-elenco.png");
    await s.page.evaluate(() => window.__lab.cam([0, 1.3, -4.2], [0.1, 1.0, 0])); await wait(500); await shot(s.page, "02-atletas-costas.png");
    await s.page.evaluate(() => { window.__lab.setLayout("closeup"); window.__lab.cam([0.32, 1.7, 0.62], [0, 1.66, 0]); }); await wait(600); await shot(s.page, "03-atleta-rosto.png");
    await s.page.evaluate(() => { window.__lab.setLayout("variety"); window.__lab.cam([0, 2.2, 6.2], [0, 0.9, -0.6]); }); await wait(800); await shot(s.page, "04-atletas-variedade.png");
    await s.page.evaluate(() => { window.__lab.setLayout("lineup"); window.__lab.setPose("goleiro_espera"); window.__lab.cam([1.2, 1.3, 3.2], [0.6, 0.9, 0]); }); await wait(600); await shot(s.page, "05-goleiro-espera.png");
    await s.page.evaluate(() => { window.__lab.setPose("sprint"); window.__lab.cam([4.5, 1.2, 0.4], [0.6, 0.9, 0]); }); await wait(600); await shot(s.page, "06-perfil-sprint.png");
    await s.close();
  }
  if (want("anim")) {
    // contact frames of ball actions
    const s = await open(browser, "tab=animation");
    for (const [clip, file, cam] of [["shot", "10-chute-contato.png", [2.4, 1.2, 2.0]], ["pass_short", "11-passe-contato.png", [2.2, 1.2, 2.2]], ["header", "12-cabeceio-contato.png", [2.8, 1.8, 2.6]], ["slide_tackle", "13-carrinho-contato.png", [3, 1.4, 1.2]], ["gk_catch", "14-encaixe-contato.png", [2.2, 1.3, 2.6]], ["cross", "15-cruzamento-contato.png", [2.4, 1.2, 2.0]]]) {
      await s.page.evaluate(([c, cm]) => { window.__lab.pickClip(c); const m = window.__lab.metadata().find((x) => x.name === c); window.__lab.play(true); window.__lab.timeScale(1); window.__lab.cam(cm, [0, 0.8, 0.3]); window.__contactU = m.contact.u; }, [clip, cam]);
      await s.page.waitForFunction(() => document.querySelector(".hud").textContent.includes("● contato"), null, { timeout: 5000 }).catch(() => {});
      await s.page.evaluate(() => window.__lab.play(false)); await wait(200); await shot(s.page, file);
    }
    await s.close();
    for (const [name, setup, ms] of [
      ["video-corrida.webm", () => { window.__lab.setMode("loco"); window.__lab.loco({ path: "figure8", speed: 5, mode: "synced+ik" }); }, 8000],
      ["video-conducao.webm", () => { window.__lab.setMode("loco"); window.__lab.loco({ path: "circle", speed: 4.2, mode: "synced+ik", dribble: true }); }, 8000],
      ["video-passe.webm", () => { window.__lab.pickClip("pass_short"); window.__lab.cam([3.4, 1.4, 2.6], [0, 0.8, 1.2]); }, 3000],
      ["video-chute.webm", () => { window.__lab.pickClip("shot"); window.__lab.timeScale(0.5); window.__lab.cam([3.6, 1.4, 1.6], [0, 0.8, 1.5]); }, 4500],
      ["video-lancamento-cabeceio.webm", () => { window.__lab.pickClip("pass_long"); window.__lab.cam([4.5, 1.8, 2.6], [0, 1, 3]); setTimeout(() => window.__lab.pickClip("header"), 2600); }, 5200],
      ["video-deslize-ingenuo.webm", () => { window.__lab.setMode("loco"); window.__lab.loco({ path: "straight", speed: 4.5, mode: "naive" }); }, 6000],
    ]) {
      const v = await open(browser, "tab=animation", { video: true, size: [960, 540] });
      await v.page.evaluate(setup); await wait(ms);
      if (name.includes("corrida") || name.includes("ingenuo")) console.log("  slide", name, JSON.stringify(await v.page.evaluate(() => window.__lab.slide())));
      await v.close(name); console.log("  video", name);
    }
  }
  if (want("keeper")) {
    const s = await open(browser, "tab=goalkeeper");
    for (const [id, times, cam] of [["left_low", [0.3, 0.48, 0.62, 0.8], [2.5, 2.0, -6.5]], ["right_mid", [0.35, 0.5, 0.7, 0.95], [-2.5, 2.0, -6.5]], ["cross", [0.9, 1.25, 1.5, 1.7], [12, 3, 4]], ["dip", [0.7, 0.9, 1.05, 1.25], [6, 2.2, -5]]]) {
      for (const tt of times) { await s.page.evaluate(([i, t, c]) => { window.__lab.run(i, 85); window.__lab.slow(0.0001); window.__lab.setT(t); window.__lab.cam(c, [0.3, 1.0, 4]); }, [id, tt, cam]); await wait(300); await shot(s.page, `gk-${id}-${tt.toFixed(2)}.png`); }
    }
    await s.page.evaluate(() => window.__lab.batch()); await wait(300);
    await s.page.evaluate(() => { document.getElementById("panel").scrollTop = 10000; }); await shot(s.page, "20-goleiro-tabela.png");
    await s.close();
    for (const [name, seq] of [["video-mergulho.webm", [["left_low", 0.5], ["right_low", 0.5], ["right_mid", 0.5]]], ["video-defesas.webm", [["central", 0.7], ["cross", 0.8], ["dip", 0.6], ["out_of_reach", 0.6], ["rebound", 0.6]]]]) {
      const v = await open(browser, "tab=goalkeeper", { video: true, size: [960, 540] });
      for (const [id, slow] of seq) {
        const r = await v.page.evaluate(([i, sl]) => { window.__lab.run(i, 85); window.__lab.slow(sl); window.__lab.cam(i === "cross" ? [14, 4, 2] : [2.5, 2.0, -6.5], [0.3, 1.0, i === "cross" ? 3 : 4]); return window.__lab.result(); }, [id, slow]);
        console.log("  keeper", id, JSON.stringify(r));
        await wait(((r.contact ?? 1) + 1.6) / slow * 1000 + 600);
      }
      await v.close(name); console.log("  video", name);
    }
  }
  if (want("physics")) { const s = await open(browser, "tab=physics", { size: [1440, 1180] }); await wait(2500); await shot(s.page, "30-fisica.png"); await s.close(); }
  if (want("ai")) {
    const s = await open(browser, "tab=ai");
    for (const id of ["2v1", "3v2", "counter", "organised", "through", "onetwo", "overlap", "cross", "lowblock", "highpress"]) { await s.page.evaluate((i) => window.__lab.scenario(i, 1), id); await wait(3500); await shot(s.page, `ai-${id}.png`); }
    await s.page.evaluate(() => { window.__lab.scenario("organised", 1); window.__lab.naive(true); }); await wait(3500); await shot(s.page, "ai-organised-baseline.png");
    await s.close();
    const v = await open(browser, "tab=ai", { video: true, size: [1100, 640] });
    for (const [id, ms, naive] of [["organised", 9000, false], ["counter", 7000, false], ["onetwo", 6000, false], ["overlap", 6000, false], ["organised", 5000, true]]) { await v.page.evaluate(([i, n]) => { window.__lab.scenario(i, 1); window.__lab.naive(n); }, [id, naive]); await wait(ms); }
    await v.close("video-coletivo.webm"); console.log("  video video-coletivo.webm");
  }
  if (want("sprites")) {
    const s = await open(browser, "tab=sprites");
    await s.page.waitForFunction(() => window.__lab.meta && window.__lab.meta(), null, { timeout: 60000 });
    await s.page.evaluate(() => window.__lab.view(24, 1.5)); await wait(2500); await shot(s.page, "40-sprites-2d.png");
    for (const [mask, file] of [[true, "sprite-atlas-mascara.png"], [false, "sprite-atlas-mandante.png"]]) { const url = await s.page.evaluate((m) => window.__lab.atlasDataUrl(m), mask); fs.writeFileSync(path.join(OUT, file), Buffer.from(url.split(",")[1], "base64")); console.log("  atlas", file); }
    fs.writeFileSync(path.join(OUT, "sprite-atlas.json"), JSON.stringify(await s.page.evaluate(() => window.__lab.meta()), null, 2));
    await s.close();
    const v = await open(browser, "tab=sprites", { video: true, size: [1100, 640] });
    await v.page.waitForFunction(() => window.__lab.meta && window.__lab.meta(), null, { timeout: 60000 });
    await v.page.evaluate(() => window.__lab.view(24, 1.5)); await wait(9000);
    await v.close("video-sprites-2d.webm"); console.log("  video video-sprites-2d.webm");
  }
  await browser.close();
  if (want("perf")) {
    for (const [label, args] of [["vsync", []], ["uncapped", ["--disable-gpu-vsync", "--disable-frame-rate-limit"]]]) {
      const b = await launch(chromium, { args });
      const s = await open(b, "tab=performance");
      const res = await s.page.evaluate(() => window.__lab.matrix());
      const sizes = label === "vsync" ? await s.page.evaluate(() => window.__lab.assetSizes()) : null;
      await shot(s.page, `50-performance-${label}.png`);
      fs.writeFileSync(path.join(OUT, `../data/performance-${label}.json`), JSON.stringify({ mode: label, flags: args, date: new Date().toISOString(), ...res, assetSizes: sizes }, null, 2));
      console.log("  perf", label, res.env.renderer);
      await s.close(); await b.close();
    }
  }
})();
