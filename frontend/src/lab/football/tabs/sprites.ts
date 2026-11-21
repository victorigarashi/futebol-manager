import { KIT_AWAY, KIT_HOME, KIT_KEEPER, SKIN_TONES, HAIR_COLOURS, type Pattern } from "../athlete/kit";
import { measureStride, CLIPS } from "../anim/clips";
import { bakeAtlas, cellXY, directionIndex, paletteFor, recolour, DIRECTIONS, type AtlasMeta } from "../sprites/bake";
import { button, checkbox, el, select, slider } from "../stage";

/**
 * Sprite Generation Lab: bakes the 3D athlete into an 8-direction mask atlas, recolours it
 * per team and plays it on a 2D pitch. Sprite frames advance with distance run (stride
 * measured from the 3D clip), so 2D players do not slide either.
 */
type Mover = { x: number; y: number; vx: number; vy: number; team: "home" | "away" | "keeper"; dist: number; anim: string; t: number; look: number; phase: number; path: (t: number) => [number, number] };

export function mount(view: HTMLElement, panel: HTMLElement) {
  view.style.display = "grid"; view.style.gridTemplateRows = "62% 38%";
  const pitch = el("canvas", { class: "fill" });
  const atlasView = el("div", { style: "overflow:auto;border-top:1px solid #26313a;background:#0b0f12" });
  const atlasImg = el("canvas", { style: "image-rendering:pixelated;display:block" });
  atlasView.append(atlasImg);
  view.append(pitch, atlasView);
  const hud = el("div", { class: "hud" });
  view.append(hud);
  let cell = 80, elevation = 52, pattern: Pattern = "stripes", outline = true, posterize = 6, zoom = 1, showMask = false, spriteScale = 1.0, viewW = 30;
  let atlas: HTMLCanvasElement | null = null, meta: AtlasMeta | null = null;
  const teams: Record<string, HTMLCanvasElement[]> = {};
  const status = el("div", { class: "note" });
  const runStride = measureStride(CLIPS.run).stride, sprintStride = measureStride(CLIPS.sprint).stride, dribbleStride = measureStride(CLIPS.dribble).stride;

  const bake = async () => {
    status.textContent = "Gerando…";
    const res = await bakeAtlas({ cell, elevationDeg: elevation, pattern, outline, posterize, onProgress: (k) => { status.textContent = `Gerando… ${(k * 100).toFixed(0)}%`; } });
    atlas = res.canvas; meta = res.meta;
    // three looks per team share the same atlas (skin/hair vary): recolour once per look
    teams.home = [0, 2, 4].map((i) => recolour(atlas!, paletteFor({ ...KIT_HOME, pattern }, SKIN_TONES[i], HAIR_COLOURS[i % 6], "#111111"), outline));
    teams.away = [1, 3, 5].map((i) => recolour(atlas!, paletteFor({ ...KIT_AWAY, pattern: "plain" }, SKIN_TONES[i], HAIR_COLOURS[(i + 1) % 6], "#f4f4f4"), outline));
    teams.keeper = [recolour(atlas!, paletteFor(KIT_KEEPER, SKIN_TONES[2], HAIR_COLOURS[0], "#111111", true), outline)];
    const bytes = atlas.width * atlas.height * 4;
    status.textContent = `Atlas ${atlas.width}×${atlas.height} px · ${meta.rows} linhas × ${meta.cols} quadros · ${(meta.rows * meta.cols)} células · ${(bytes / 1048576).toFixed(1)} MB RGBA na GPU · gerado em ${meta.bakeMs} ms`;
    drawAtlas();
  };
  const drawAtlas = () => {
    if (!atlas) return;
    const src = showMask ? atlas : teams.home[0];
    atlasImg.width = src.width * zoom; atlasImg.height = src.height * zoom;
    atlasImg.style.width = `${src.width * zoom * 0.5}px`;
    const g = atlasImg.getContext("2d")!;
    g.imageSmoothingEnabled = false;
    g.fillStyle = "#2f7d3a"; g.fillRect(0, 0, atlasImg.width, atlasImg.height);
    g.drawImage(src, 0, 0, src.width * zoom, src.height * zoom);
    g.font = `${12 * zoom}px Inter, sans-serif`; g.fillStyle = "#fff";
    if (meta) for (const a of meta.anims) { const [x, y] = cellXY(meta, a.row0, 0); g.fillText(a.name, x * zoom + 4, (y + 12) * zoom); }
  };

  // ---- 2D preview: the same atlas, recoloured per team; frame index from distance run
  const movers: Mover[] = [];
  const add = (team: Mover["team"], look: number, path: Mover["path"]) => movers.push({ x: 0, y: 0, vx: 0, vy: 0, team, dist: 0, anim: "idle", t: 0, look, phase: 0, path });
  add("home", 0, (t) => [24 + Math.cos(t * 0.6) * 6, 18 + Math.sin(t * 0.6) * 5]);
  add("home", 1, (t) => [28 + Math.sin(t * 0.7) * 8, 12 + Math.sin(t * 1.4) * 3]);
  add("home", 2, (t) => [16 + (t * 3.2) % 20, 23]);
  add("away", 0, (t) => [30 + Math.cos(-t * 0.65) * 5, 20 + Math.sin(-t * 0.65) * 5]);
  add("away", 1, (t) => [20 + Math.sin(t * 0.4) * 5, 14 + Math.cos(t * 0.4) * 4]);
  add("away", 2, (t) => [38 - (t * 6.5) % 22, 25]);
  add("keeper", 0, () => [46, 18]);
  let last = performance.now(), raf = 0, T = 0;
  const pxPerM = () => Math.min(pitch.clientWidth / viewW, pitch.clientHeight / (viewW * 0.62) / Math.sin(elevation * Math.PI / 180));
  const frame = (now: number) => {
    const dt = Math.min(0.05, (now - last) / 1000); last = now; T += dt;
    const W = pitch.clientWidth, H = pitch.clientHeight, dpr = Math.min(2, devicePixelRatio || 1);
    pitch.width = W * dpr; pitch.height = H * dpr;
    const g = pitch.getContext("2d")!;
    g.scale(dpr, dpr);
    const s = pxPerM(), sy = Math.sin(elevation * Math.PI / 180);
    // camera follows the action centre (like a 2D match camera) over a 52 x 36 m area
    const cx = Math.min(52 - viewW / 2, Math.max(viewW / 2, 30 + Math.sin(T * 0.2) * 4)), cyv = 18;
    const ox = W / 2 - cx * s, oy = H / 2 - cyv * s * sy;
    const X = (x: number) => ox + x * s, Y = (y: number) => oy + y * s * sy;
    for (let i = 0; i < 13; i += 1) { g.fillStyle = i % 2 ? "#3d8f3f" : "#459c46"; g.fillRect(X(i * 4), Y(0), 4 * s + 1, 36 * s * sy); }
    g.strokeStyle = "rgba(255,255,255,.85)"; g.lineWidth = 2; g.strokeRect(X(0), Y(0), 52 * s, 36 * s * sy);
    g.strokeRect(X(52 - 16.5), Y(18 - 13), 16.5 * s, 26 * s * sy);
    g.fillStyle = "#fff"; g.fillRect(X(52) - 2, Y(18 - 3.66), 4, 7.32 * s * sy);
    if (!atlas || !meta) { g.fillStyle = "#fff"; g.fillText("Gere o atlas no painel →", 20, 30); raf = requestAnimationFrame(frame); return; }
    const m = meta;
    const anim = (name: string) => m.anims.find((a) => a.name === name)!;
    const sorted = [...movers].sort((a, b) => a.y - b.y);
    for (const mv of movers) {
      if (mv.team === "keeper") {
        mv.t += dt;
        const cyc = mv.t % 3.2;
        mv.anim = cyc < 1.6 ? "gk_ready" : "gk_dive";
        const [x, y] = mv.path(T); mv.x = x; mv.y = y + (cyc >= 1.6 ? Math.min(1, (cyc - 1.6) / 0.6) * -2.6 : 0); mv.vx = 0; mv.vy = 0;
        mv.phase = cyc < 1.6 ? (cyc * anim("gk_ready").fps) : Math.min(anim("gk_dive").frames - 1, (cyc - 1.6) * anim("gk_dive").fps);
        continue;
      }
      const [x, y] = mv.path(T);
      mv.vx = (x - mv.x) / Math.max(dt, 1e-3); mv.vy = (y - mv.y) / Math.max(dt, 1e-3);
      const sp = mv.t > 0 ? Math.hypot(mv.vx, mv.vy) : 0;
      mv.t += dt;
      const d = Math.hypot(x - mv.x, y - mv.y);
      if (d > 5) { mv.x = x; mv.y = y; continue; }      // path wrap: no slide accounting on the jump
      mv.x = x; mv.y = y;
      mv.anim = sp < 0.4 ? "idle" : mv.look === 2 && mv.team === "home" ? "dribble" : sp > 6 ? "sprint" : "run";
      const stride = mv.anim === "sprint" ? sprintStride : mv.anim === "dribble" ? dribbleStride : runStride;
      const A = anim(mv.anim);
      if (mv.anim === "idle") mv.phase += dt * A.fps; else mv.phase += (d / stride) * A.frames;   // frames advance with distance (no sliding)
    }
    for (const mv of sorted) {
      const A = anim(mv.anim);
      const dir = mv.team === "keeper" ? (mv.anim === "gk_dive" ? 6 : 0) : directionIndex(mv.vx, mv.vy * sy);
      const f = Math.floor(mv.phase) % A.frames;
      const sheet = (teams[mv.team] ?? teams.home)[mv.look % (teams[mv.team]?.length ?? 1)];
      const size = m.metresPerCell * s * spriteScale;
      const [sx, syy] = cellXY(m, A.row0 + dir, f);
      // shadow
      g.fillStyle = "rgba(0,0,0,.25)"; g.beginPath(); g.ellipse(X(mv.x), Y(mv.y), 0.38 * s, 0.16 * s, 0, 0, Math.PI * 2); g.fill();
      g.imageSmoothingEnabled = true;
      g.drawImage(sheet, sx, syy, m.cell, m.cell, X(mv.x) - (m.anchor[0] / m.cell) * size, Y(mv.y) - (m.anchor[1] / m.cell) * size, size, size);
      if (mv.anim === "dribble") { g.fillStyle = "#fff"; g.beginPath(); g.arc(X(mv.x + Math.sign(mv.vx || 1) * 0.6), Y(mv.y + 0.1), Math.max(2.5, 0.12 * s), 0, Math.PI * 2); g.fill(); }
    }
    // compass: one sprite cycling through the 8 directions
    const A = anim("run"), cs = 96;
    const dirK = Math.floor(T / 0.9) % 8;
    g.fillStyle = "rgba(10,14,18,.7)"; g.fillRect(W - cs - 16, H - cs - 34, cs + 8, cs + 26);
    const [qx, qy] = cellXY(m, A.row0 + dirK, Math.floor(T * A.fps) % A.frames);
    g.drawImage(teams.away[0], qx, qy, m.cell, m.cell, W - cs - 12, H - cs - 30, cs, cs);
    g.fillStyle = "#fff"; g.font = "12px Inter, sans-serif"; g.fillText(`direção ${DIRECTIONS[dirK]}`, W - cs - 8, H - 12);
    hud.textContent = `2D com sprites gerados do atleta 3D · escala visual ${spriteScale.toFixed(1)}× (colisão oficial inalterada) · ${movers.length} atletas · 1 atlas, recolorido por time`;
    raf = requestAnimationFrame(frame);
  };
  raf = requestAnimationFrame(frame);

  panel.append(
    el("h3", { text: "Pipeline" }),
    el("p", { class: "note", text: "Modelo → rig → clip → câmera ortográfica elevada → 8 direções → passes de sombra e máscara → atlas único → recolorir por uniforme." }),
    select("Célula", ["64", "80", "96", "128"] as const, String(cell) as "80", (v) => { cell = Number(v); }),
    slider("Elevação da câmera", 30, 75, 1, elevation, (v) => { elevation = v; }, (v) => `${v}°`),
    select("Padrão (atlas)", ["plain", "stripes", "hoops", "sash", "halves"] as const, pattern, (v) => { pattern = v; }),
    slider("Níveis de sombra", 0, 10, 1, posterize, (v) => { posterize = v; }, (v) => (v < 2 ? "contínuo" : `${v}`)),
    checkbox("Contorno de 1 px", outline, (v) => { outline = v; }),
    el("div", { class: "btns" }, button("Gerar atlas", () => void bake()), button("Baixar PNG (máscara)", () => download("football-lab-atlas-mask.png", atlas)), button("Baixar PNG (time)", () => download("football-lab-atlas-home.png", teams.home?.[0])), button("Baixar JSON", () => downloadJson())),
    status,
    el("h3", { text: "Prévia 2D" }),
    slider("Largura da câmera", 18, 52, 1, viewW, (v) => { viewW = v; }, (v) => `${v} m`),
    slider("Escala visual", 1, 2.2, 0.1, spriteScale, (v) => { spriteScale = v; }, (v) => `${v.toFixed(1)}×`),
    el("h3", { text: "Visualização do atlas" }),
    checkbox("Mostrar máscara (R = sombra, G = região)", showMask, (v) => { showMask = v; drawAtlas(); }),
    slider("Zoom", 1, 4, 1, zoom, (v) => { zoom = v; drawAtlas(); }, (v) => `${v}×`),
    el("p", { class: "note", text: "As colisões oficiais não mudam com o tamanho do sprite: o sprite é desenhado na escala real e ancorado nos pés (âncora no JSON)." }),
  );
  const download = (name: string, c?: HTMLCanvasElement | null) => { if (!c) return; const a = document.createElement("a"); a.href = c.toDataURL("image/png"); a.download = name; a.click(); };
  const downloadJson = () => { if (!meta) return; const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([JSON.stringify(meta, null, 2)], { type: "application/json" })); a.download = "football-lab-atlas.json"; a.click(); };
  void bake();
  (window as unknown as { __lab: unknown }).__lab = { bake: async (o: { cell?: number; elevation?: number; pattern?: Pattern }) => { cell = o.cell ?? cell; elevation = o.elevation ?? elevation; pattern = o.pattern ?? pattern; await bake(); return meta; }, meta: () => meta, atlasDataUrl: (mask = false) => (mask ? atlas : teams.home?.[0])?.toDataURL("image/png"), setZoom: (z: number) => { zoom = z; drawAtlas(); }, view: (w: number, sc: number) => { viewW = w; spriteScale = sc; } };
  return () => cancelAnimationFrame(raf);
}
