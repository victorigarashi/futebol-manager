// Compose PNGs into a labelled grid (node montage.cjs out.png cols cropTop "label1=img1.png" ...).
const fs = require("fs");
const { chromium } = require("playwright");
(async () => {
  const [out, colsArg = "2", cropArg = "0", ...items] = process.argv.slice(2);
  const cols = Number(colsArg), crop = Number(cropArg);
  const imgs = items.map((it) => { const i = it.lastIndexOf("="); const [label, file] = i > 0 ? [it.slice(0, i), it.slice(i + 1)] : ["", it]; return { label, src: "data:image/png;base64," + fs.readFileSync(file).toString("base64") }; });
  const browser = await chromium.launch({ executablePath: "/usr/bin/google-chrome", headless: true, args: ["--no-sandbox"] });
  const page = await browser.newPage();
  const data = await page.evaluate(async ({ imgs, cols, crop }) => {
    const loaded = await Promise.all(imgs.map((m) => new Promise((res) => { const im = new Image(); im.onload = () => res({ im, label: m.label }); im.src = m.src; })));
    const w = loaded[0].im.width, h = loaded[0].im.height - crop, scale = Math.min(1, 1400 / (w * cols));
    const cw = Math.round(w * scale), ch = Math.round(h * scale), rows = Math.ceil(loaded.length / cols);
    const c = document.createElement("canvas"); c.width = cw * cols; c.height = ch * rows;
    const g = c.getContext("2d"); g.fillStyle = "#0f1418"; g.fillRect(0, 0, c.width, c.height);
    loaded.forEach(({ im, label }, i) => {
      const x = (i % cols) * cw, y = Math.floor(i / cols) * ch;
      g.drawImage(im, 0, crop, w, h, x, y, cw, ch);
      if (label) { g.font = "600 18px sans-serif"; const tw = g.measureText(label).width; g.fillStyle = "rgba(0,0,0,.7)"; g.fillRect(x + 8, y + ch - 34, tw + 16, 26); g.fillStyle = "#fff"; g.fillText(label, x + 16, y + ch - 15); }
    });
    return c.toDataURL("image/png").split(",")[1];
  }, { imgs, cols, crop });
  fs.writeFileSync(out, Buffer.from(data, "base64"));
  await browser.close();
})();
