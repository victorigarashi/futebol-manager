// Offline bake of the 2D sprite mask atlases (one per shirt pattern) from the 3D athlete.
// The game loads these static PNGs and recolours them per team at runtime (instant); the
// in-browser bake stays as a fallback. Run with the dev server up:
//   node scripts/bake-sprites.cjs http://127.0.0.1:5181/
const path = require("node:path");
const fs = require("node:fs");
const { chromium } = require(path.join(__dirname, "..", "node_modules", "playwright"));
const APP = process.argv[2] || "http://127.0.0.1:5173/";
const out = path.join(__dirname, "..", "public", "sprites");
(async () => {
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ executablePath: "/usr/bin/google-chrome", headless: true, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
  const page = await (await browser.newContext()).newPage();
  await page.goto(APP + "football-lab.html");
  for (const pattern of ["plain", "stripes", "hoops", "sash"]) {
    const res = await page.evaluate(async (pattern) => {
      const m = await import("/src/football/sprites/bake.ts");
      const { canvas, meta } = await m.bakeAtlas({ cell: 64, elevationDeg: 56, pattern, outline: true, posterize: 6 });
      return { png: canvas.toDataURL("image/png"), meta };
    }, pattern);
    fs.writeFileSync(path.join(out, `atlas-${pattern}.png`), Buffer.from(res.png.split(",")[1], "base64"));
    fs.writeFileSync(path.join(out, `atlas-${pattern}.json`), JSON.stringify(res.meta));
    console.log(pattern, res.meta.bakeMs, "ms");
  }
  await browser.close();
})();
