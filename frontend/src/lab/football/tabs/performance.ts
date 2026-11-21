import * as THREE from "three";
import { GLTFExporter } from "three/examples/jsm/exporters/GLTFExporter.js";
import { createAthlete, type Athlete } from "../../../football/athlete/athlete";
import { bodyGeometry, triangleCount, REGIONS, type Detail } from "../../../football/athlete/body";
import { cosmeticFor, KIT_AWAY, KIT_HOME, regionPalette } from "../../../football/athlete/kit";
import { allClips, CLIPS, samplePose } from "../../../football/anim/clips";
import { button, checkbox, createStage, el, select } from "../stage";

/**
 * Performance Lab: N independently animated athletes, quality presets, shadows, LOD and
 * pixel ratio. Measures real frame times (rAF), draw calls, triangles, animation CPU cost,
 * JS heap (Chrome) and load time. Nothing here is estimated: every number is measured in
 * the browser it runs in, and the GPU/browser are reported with the results.
 */
type Config = { n: number; detail: Detail; shadows: boolean; lod: boolean; pixelRatio: number; anim: "mixer" | "sampler" };
type Result = Config & { fps: number; frameMs: number; p95: number; calls: number; tris: number; animMs: number; heapMB: number | null; loadMs: number; frames: number };

export function mount(view: HTMLElement, panel: HTMLElement) {
  let cfg: Config = { n: 22, detail: "medium", shadows: true, lod: false, pixelRatio: Math.min(2, devicePixelRatio || 1), anim: "mixer" };
  let stage = createStage(view, { shadows: cfg.shadows, pixelRatio: cfg.pixelRatio, groundSize: 140 });
  const hud = el("div", { class: "hud" });
  view.append(hud);
  let athletes: { a: Athlete; mixer: THREE.AnimationMixer | null; low: THREE.SkinnedMesh | null; phase: number; r: number; cx: number; cz: number; speed: number }[] = [];
  let loadMs = 0;
  const clips = allClips();
  const byName = Object.fromEntries(clips.map((c) => [c.meta.name, c.clip]));
  let animMs = 0;
  let measuring: { start: number; dts: number[]; anim: number[]; resolve: (r: Result) => void } | null = null;
  let last = performance.now();

  const glInfo = () => {
    const gl = stage.renderer.getContext();
    const ext = gl.getExtension("WEBGL_debug_renderer_info");
    return { renderer: ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : "?", vendor: ext ? gl.getParameter(ext.UNMASKED_VENDOR_WEBGL) : "?", ua: navigator.userAgent, cores: navigator.hardwareConcurrency, dpr: devicePixelRatio, canvas: `${stage.canvas.width}×${stage.canvas.height}` };
  };

  const build = () => {
    for (const x of athletes) { stage.scene.remove(x.a.group); x.a.dispose(); x.mixer?.stopAllAction(); }
    athletes = [];
    const t0 = performance.now();
    for (let i = 0; i < cfg.n; i += 1) {
      const home = i < cfg.n / 2;
      const seed = 100 + i * 31;
      const a = createAthlete({ kit: { ...(home ? KIT_HOME : KIT_AWAY), number: (i % 11) + 1 }, detail: cfg.detail, shadows: cfg.shadows, seed });
      // formation-ish spread over ~60 x 40 m, each runs its own loop
      const col = i % 6, row = Math.floor(i / 6);
      const cx = (col - 2.5) * 10 + (home ? -3 : 3), cz = (row - 1.5) * 10;
      stage.scene.add(a.group);
      let mixer: THREE.AnimationMixer | null = null;
      if (cfg.anim === "mixer") {
        mixer = new THREE.AnimationMixer(a.mesh);
        const run = mixer.clipAction(byName.run), idle = mixer.clipAction(byName.idle), sprint = mixer.clipAction(byName.sprint);
        for (const act of [run, idle, sprint]) { act.play(); act.time = (i * 0.137) % act.getClip().duration; }
        run.setEffectiveWeight(0.7); sprint.setEffectiveWeight(0.2); idle.setEffectiveWeight(0.1);
      }
      let low: THREE.SkinnedMesh | null = null;
      if (cfg.lod) {
        const look = cosmeticFor(seed);
        const shared = bodyGeometry("low", { keeper: false, hair: look.hairStyle, build: look.build });
        const g = new THREE.BufferGeometry();
        for (const name of ["position", "normal", "uv", "skinIndex", "skinWeight"]) g.setAttribute(name, shared.getAttribute(name));
        g.setIndex(shared.index);
        const pal = regionPalette(home ? KIT_HOME : KIT_AWAY, look, false);
        const reg = shared.getAttribute("region") as THREE.BufferAttribute;
        const colours = new Float32Array(reg.count * 3);
        for (let k = 0; k < reg.count; k += 1) { const c = new THREE.Color(pal[REGIONS[Math.round(reg.getX(k))]]); colours.set([c.r, c.g, c.b], k * 3); }
        g.setAttribute("color", new THREE.BufferAttribute(colours, 3));
        low = new THREE.SkinnedMesh(g, a.mesh.material);
        low.bind(a.rig.skeleton, a.mesh.bindMatrix);
        low.frustumCulled = false; low.castShadow = cfg.shadows;
        a.group.add(low);
      }
      athletes.push({ a, mixer, low, phase: i * 0.37, r: 3 + (i % 4), cx, cz, speed: 0.25 + (i % 5) * 0.05 });
    }
    // compile shaders now so the first measured frame is not a compile
    stage.renderer.compile(stage.scene, stage.camera);
    loadMs = performance.now() - t0;
  };

  const setupStage = () => {
    stage.dispose();
    stage = createStage(view, { shadows: cfg.shadows, pixelRatio: cfg.pixelRatio, groundSize: 140 });
    view.append(hud);
    stage.camera.position.set(0, 28, 46); stage.controls.target.set(0, 0, 0);
    stage.sun.shadow.camera.left = stage.sun.shadow.camera.bottom = -40; stage.sun.shadow.camera.right = stage.sun.shadow.camera.top = 40; stage.sun.shadow.camera.updateProjectionMatrix();
    stage.onFrame(tick);
    build();
  };

  const camPos = new THREE.Vector3();
  const tick = (dt: number, t: number) => {
    const now = performance.now();
    const frameDt = now - last; last = now;
    const a0 = performance.now();
    stage.camera.getWorldPosition(camPos);
    for (const x of athletes) {
      const ang = t * x.speed + x.phase;
      x.a.group.position.set(x.cx + Math.cos(ang) * x.r, 0, x.cz + Math.sin(ang) * x.r);
      x.a.group.rotation.y = -ang;
      if (x.mixer) x.mixer.update(dt);
      else x.a.setPose(samplePose(CLIPS.run, (t * 1.4 + x.phase) % 1));
      if (x.low) { const far = x.a.group.position.distanceTo(camPos) > 25; x.low.visible = far; x.a.mesh.visible = !far; }
    }
    animMs = performance.now() - a0;
    if (measuring) { measuring.dts.push(frameDt); measuring.anim.push(animMs); }
    const info = stage.renderer.info.render;
    hud.textContent = `${cfg.n} atletas · ${cfg.detail}${cfg.lod ? "+LOD" : ""} · sombras ${cfg.shadows ? "sim" : "não"} · DPR ${cfg.pixelRatio} · ${cfg.anim}\n` +
      `quadro ${frameDt.toFixed(1)} ms · draw calls ${info.calls} · triângulos ${info.triangles.toLocaleString("pt-BR")} · animação ${animMs.toFixed(2)} ms\n` +
      `carga ${loadMs.toFixed(0)} ms · GPU: ${glInfo().renderer}`;
  };

  const measure = (warm = 800, dur = 3000): Promise<Result> => new Promise((resolve) => {
    setTimeout(() => {
      measuring = { start: performance.now(), dts: [], anim: [], resolve };
      setTimeout(() => {
        const m = measuring!; measuring = null;
        const d = [...m.dts].sort((a, b) => a - b);
        const mean = d.reduce((s, x) => s + x, 0) / d.length;
        const info = stage.renderer.info.render;
        const mem = (performance as unknown as { memory?: { usedJSHeapSize: number } }).memory;
        resolve({ ...cfg, fps: 1000 / mean, frameMs: mean, p95: d[Math.floor(d.length * 0.95)] ?? mean, calls: info.calls, tris: info.triangles, animMs: m.anim.reduce((s, x) => s + x, 0) / m.anim.length, heapMB: mem ? mem.usedJSHeapSize / 1048576 : null, loadMs, frames: d.length });
      }, dur);
    }, warm);
  });

  const results: Result[] = [];
  const table = el("table");
  const renderTable = () => table.replaceChildren(el("tr", {}, ...["N", "Detalhe", "Sombra", "LOD", "DPR", "Anim", "FPS", "ms (p95)", "Calls", "Tris", "Anim ms", "Carga"].map((h) => el("th", { text: h }))),
    ...results.map((r) => el("tr", {}, ...[r.n, r.detail, r.shadows ? "s" : "n", r.lod ? "s" : "n", r.pixelRatio, r.anim, r.fps.toFixed(0), `${r.frameMs.toFixed(1)} (${r.p95.toFixed(1)})`, r.calls, (r.tris / 1000).toFixed(0) + "k", r.animMs.toFixed(2), `${r.loadMs.toFixed(0)}`].map((c) => el("td", { text: String(c) })))));
  const runOne = async (c: Partial<Config>) => {
    const needsStage = c.shadows !== undefined && c.shadows !== cfg.shadows || c.pixelRatio !== undefined && c.pixelRatio !== cfg.pixelRatio;
    cfg = { ...cfg, ...c };
    if (needsStage) setupStage(); else build();
    const r = await measure();
    results.push(r); renderTable();
    return r;
  };
  const matrix = async () => {
    results.length = 0;
    for (const n of [1, 5, 10, 22]) await runOne({ n, detail: "medium", shadows: true, lod: false, anim: "mixer" });
    for (const detail of ["low", "high"] as Detail[]) await runOne({ n: 22, detail, shadows: true, lod: false });
    await runOne({ n: 22, detail: "high", shadows: false, lod: false });
    await runOne({ n: 22, detail: "high", shadows: true, lod: true });
    await runOne({ n: 22, detail: "medium", shadows: true, lod: false, anim: "sampler" });
    await runOne({ n: 22, detail: "medium", shadows: true, lod: false, anim: "mixer", pixelRatio: 1 });
    return { results: [...results], env: glInfo() };
  };
  const assetSizes = async () => {
    const out: Record<string, number> = {};
    for (const d of ["low", "medium", "high"] as Detail[]) {
      const a = createAthlete({ kit: KIT_HOME, detail: d, seed: 11 });
      const buf = await new GLTFExporter().parseAsync(a.group, { binary: true, animations: d === "medium" ? clips.map((c) => c.clip) : [] }) as ArrayBuffer;
      out[`glb_${d}${d === "medium" ? "_with_30_clips" : ""}`] = buf.byteLength;
      out[`tris_${d}`] = triangleCount(a.mesh.geometry);
      a.dispose();
    }
    return out;
  };

  panel.append(
    el("h3", { text: "Configuração" }),
    select("Atletas", ["1", "5", "10", "22"] as const, String(cfg.n) as "22", (v) => { cfg.n = Number(v); build(); }),
    select("Detalhe", ["low", "medium", "high"] as const, cfg.detail, (v) => { cfg.detail = v; build(); }),
    select("Animação", ["mixer", "sampler"] as const, cfg.anim, (v) => { cfg.anim = v; build(); }, { mixer: "AnimationMixer (clips assados)", sampler: "amostrador de poses (CPU)" }),
    select("Pixel ratio", ["1", "1.5", "2"] as const, String(cfg.pixelRatio) as "1", (v) => { cfg.pixelRatio = Number(v); setupStage(); }),
    checkbox("Sombras", cfg.shadows, (v) => { cfg.shadows = v; setupStage(); }),
    checkbox("LOD (low além de 25 m)", cfg.lod, (v) => { cfg.lod = v; build(); }),
    el("div", { class: "btns" }, button("Medir (3 s)", async () => { results.push(await measure()); renderTable(); }), button("Rodar matriz", () => void matrix()), button("Limpar", () => { results.length = 0; renderTable(); })),
    el("h3", { text: "Resultados" }), table,
    el("p", { class: "note", text: "FPS medido por requestAnimationFrame (limitado pelo vsync do monitor, salvo flags de benchmark). 'Anim ms' é o custo de CPU da atualização de todos os esqueletos no quadro. Ambiente e GPU são exibidos no HUD e salvos com os resultados." }),
  );
  setupStage();
  (window as unknown as { __lab: unknown }).__lab = { matrix, runOne, measure, glInfo, assetSizes, results: () => results, cam: (p: [number, number, number], t: [number, number, number]) => { stage.camera.position.set(...p); stage.controls.target.set(...t); } };
  return () => { for (const x of athletes) x.a.dispose(); stage.dispose(); };
}
