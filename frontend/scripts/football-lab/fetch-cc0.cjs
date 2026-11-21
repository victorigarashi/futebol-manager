// Optional comparison asset (NOT committed): Quaternius "Animated Men" GLB, CC0 1.0.
// Source used in research: github.com/kendrekaran/striker-3d (assets/player.glb + LICENSE-quaternius.txt).
// For production, re-download from quaternius.com instead (see docs/research/football-lab/LICENCAS.md).
const fs = require("fs"), path = require("path");
const dir = path.resolve(__dirname, "../../public/lab-assets/third-party");
fs.mkdirSync(dir, { recursive: true });
const base = "https://raw.githubusercontent.com/kendrekaran/striker-3d/main/assets/";
(async () => {
  for (const [src, dst] of [["player.glb", "quaternius-animated-man.glb"], ["LICENSE-quaternius.txt", "LICENSE-quaternius.txt"]]) {
    const r = await fetch(base + src);
    if (!r.ok) throw new Error(`${src}: HTTP ${r.status}`);
    fs.writeFileSync(path.join(dir, dst), Buffer.from(await r.arrayBuffer()));
    console.log("saved", dst);
  }
})();
