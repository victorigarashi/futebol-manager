// Renders the original stadium backdrops (src/retro-tools/backdrop.ts) into public/retro/*.webp.
// Needs the dev server: npx vite --port 5180, then: node scripts/retro/render-backdrops.cjs
const fs = require("fs"), path = require("path");
const { chromium } = require("playwright");
const BASE = process.env.RETRO_URL || "http://localhost:5180";
(async () => {
  const b = await chromium.launch({ executablePath: "/usr/bin/google-chrome", headless: true, args: ["--no-sandbox", "--use-angle=gl", "--ignore-gpu-blocklist"] });
  const p = await b.newPage({ viewport: { width: 800, height: 450 } });
  await p.goto(`${BASE}/retro-backdrop.html`);
  await p.waitForFunction(() => document.body.dataset.ready === "1");
  await p.evaluate(() => document.fonts.ready);
  for (const view of (process.argv[2] || "menu,career,squad").split(",")) {
    const url = await p.evaluate((v) => window.renderBackdrop(v, 2560, 1440).toDataURL("image/webp", 0.84), view);
    const out = path.resolve(__dirname, `../../public/retro/stadium-${view}.webp`);
    fs.writeFileSync(out, Buffer.from(url.split(",")[1], "base64"));
    console.log(out, (fs.statSync(out).size / 1024).toFixed(0) + " KB");
  }
  await b.close();
})();
