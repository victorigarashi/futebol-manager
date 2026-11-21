import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { GLTFExporter } from "three/examples/jsm/exporters/GLTFExporter.js";
import { createHuman } from "../../../features/career/interactive/render/human";
import { createAthlete, type Athlete } from "../../../football/athlete/athlete";
import { triangleCount, type Detail } from "../../../football/athlete/body";
import { cosmeticFor, KIT_AWAY, KIT_HOME, KIT_KEEPER, type KitSpec, type Pattern } from "../../../football/athlete/kit";
import { BONES, type Pose } from "../../../football/athlete/rig";
import { POSES } from "../../../football/anim/poses";
import { button, createStage, el, select, slider, checkbox } from "../stage";

/** Characters: the new lofted athlete, keeper, kits and cosmetic variety, next to the V6 athlete and a CC0 baseline. */
export function mount(view: HTMLElement, panel: HTMLElement) {
  const stage = createStage(view, { shadows: true });
  stage.camera.position.set(0.3, 1.3, 6.4);
  stage.controls.target.set(0.1, 0.95, 0);
  const hud = el("div", { class: "hud" });
  view.append(hud);
  let detail: Detail = "high";
  let pose: keyof typeof POSES = "idle";
  let spin = false;
  let layout: "lineup" | "variety" | "closeup" = "lineup";
  const pattern: { home: Pattern; away: Pattern } = { home: KIT_HOME.pattern, away: KIT_AWAY.pattern };
  let athletes: Athlete[] = [];
  const extras: THREE.Object3D[] = [];
  let compareV6 = true, compareCC0 = false;
  let cc0: THREE.Object3D | null = null;
  let cc0Tris = 0;
  const holder = new THREE.Group();
  stage.scene.add(holder);

  const build = () => {
    for (const a of athletes) { holder.remove(a.group); a.dispose(); }
    for (const x of extras) holder.remove(x);
    athletes = []; extras.length = 0;
    const place = (a: Athlete, x: number, z = 0, yaw = 0) => { a.group.position.set(x, 0, z); a.group.rotation.y = yaw; holder.add(a.group); athletes.push(a); };
    const home: KitSpec = { ...KIT_HOME, pattern: pattern.home };
    const away: KitSpec = { ...KIT_AWAY, pattern: pattern.away };
    if (layout === "lineup") {
      place(createAthlete({ kit: home, detail, shadows: true, seed: 11 }), -0.6);
      place(createAthlete({ kit: KIT_KEEPER, keeper: true, detail, shadows: true, seed: 5, look: { ...cosmeticFor(5), hairStyle: 0 } }), 0.6);
      place(createAthlete({ kit: away, detail, shadows: true, seed: 23, look: { ...cosmeticFor(23), hairStyle: 1 } }), 1.8);
      if (compareV6) {
        const v6 = createHuman({ skin: "#c98f63", hair: "#1b120c", shirt: "#d81f26", trim: "#111111", shorts: "#111111", socks: "#111111", boots: "#111111", hands: "#c98f63", pattern: "stripes" }, 1, detail, true);
        v6.mesh.position.set(-1.8, 0, 0);
        const label = textSprite("V6 (atual)");
        label.position.set(-1.8, 2.05, 0);
        holder.add(v6.mesh, label); extras.push(v6.mesh, label);
      }
      if (compareCC0 && cc0) { cc0.position.set(3.0, 0, 0); holder.add(cc0); extras.push(cc0); const label = textSprite("CC0 Quaternius"); label.position.set(3.0, 2.05, 0); holder.add(label); extras.push(label); }
      const l2 = textSprite("Lab: linha · goleiro · visitante"); l2.position.set(0.6, 2.15, 0); holder.add(l2); extras.push(l2);
    } else if (layout === "variety") {
      for (let i = 0; i < 10; i += 1) {
        const seed = 101 + i * 37;
        const kit = { ...(i % 2 ? away : home), number: [2, 3, 4, 5, 6, 7, 8, 9, 10, 11][i] };
        place(createAthlete({ kit, detail, shadows: true, seed }), (i % 5 - 2) * 0.85, i < 5 ? 0 : -1.3, i < 5 ? 0 : Math.PI);
      }
    } else {
      place(createAthlete({ kit: home, detail, shadows: true, seed: 11 }), 0);
    }
    applyAll();
    info();
  };
  const applyAll = () => { for (const a of athletes) a.setPose(POSES[pose] as Pose); };
  const info = () => {
    const a = athletes[0];
    const tris = a ? triangleCount(a.mesh.geometry) : 0;
    const box = a ? new THREE.Box3().setFromObject(a.mesh) : null;
    hud.textContent = `Atleta lab: ${tris} triângulos (${detail}) · ${BONES.length} ossos · altura ${box ? box.max.y.toFixed(2) : "-"} m\n` +
      `Goleiro: mangas longas + luvas · Uniformes: ${pattern.home} × ${pattern.away}` + (cc0 ? `\nCC0 Quaternius: ${cc0Tris} triângulos, 31 juntas` : "");
  };
  stage.onFrame((dt) => { if (spin) holder.rotation.y += dt * 0.6; });

  // camera presets
  const cam = (p: [number, number, number], t: [number, number, number]) => { stage.camera.position.set(...p); stage.controls.target.set(...t); };
  panel.append(
    el("h3", { text: "Vista" }),
    el("div", { class: "btns" },
      button("Elenco", () => { layout = "lineup"; build(); cam([0.3, 1.3, 6.4], [0.1, 0.95, 0]); }),
      button("Variedade", () => { layout = "variety"; build(); cam([0, 2.2, 6.2], [0, 0.9, -0.6]); }),
      button("Close (rosto)", () => { layout = "closeup"; build(); cam([0.25, 1.68, 0.75], [0, 1.66, 0]); }),
      button("Costas", () => { cam([0, 1.3, -3.6], [0, 1.0, 0]); }),
      button("Perfil", () => { cam([3.6, 1.2, 0], [0, 0.95, 0]); }),
    ),
    select("Pose", Object.keys(POSES) as (keyof typeof POSES)[], pose, (v) => { pose = v; applyAll(); }),
    select("Detalhe", ["high", "medium", "low"] as const, detail, (v) => { detail = v; build(); }),
    select("Padrão mandante", ["plain", "hoops", "stripes", "sash", "halves"] as const, pattern.home, (v) => { pattern.home = v; build(); }),
    select("Padrão visitante", ["plain", "hoops", "stripes", "sash", "halves"] as const, pattern.away, (v) => { pattern.away = v; build(); }),
    checkbox("Girar", spin, (v) => { spin = v; if (!v) holder.rotation.y = 0; }),
    checkbox("Comparar com V6", compareV6, (v) => { compareV6 = v; build(); }),
    checkbox("Comparar com CC0 (Quaternius)", compareCC0, (v) => { compareCC0 = v; if (v && !cc0) loadCC0(); else build(); }),
    slider("Sol (azimute)", 0, 360, 1, 40, (v) => { const r = (v * Math.PI) / 180; stage.sun.position.set(Math.cos(r) * 9, 12, Math.sin(r) * 9); }, (v) => `${v}°`),
    el("h3", { text: "Exportar" }),
    el("div", { class: "btns" }, button("Baixar GLB (atleta + rig)", () => exportGlb())),
    el("p", { class: "note", text: "O GLB exportado contém malha, esqueleto de 21 ossos, pesos e as animações do Animation Lab (ver docs/research/football-lab/RIG.md)." }),
  );

  const loadCC0 = () => {
    // Optional, not committed: fetched by frontend/scripts/football-lab/fetch-cc0.cjs (CC0 1.0, Quaternius "Animated Men").
    new GLTFLoader().load("/lab-assets/third-party/quaternius-animated-man.glb", (gltf) => {
      cc0 = gltf.scene;
      const box = new THREE.Box3().setFromObject(cc0);
      const s = 1.82 / (box.max.y - box.min.y);
      cc0.scale.setScalar(s);
      cc0.traverse((o) => { const m = o as THREE.Mesh; if (m.isMesh) { m.castShadow = true; cc0Tris += triangleCount(m.geometry); } });
      build();
    }, undefined, () => { hud.textContent += "\nCC0: arquivo ausente (rode scripts/football-lab/fetch-cc0.cjs)"; });
  };

  const exportGlb = async () => {
    const { allClips } = await import("../../../football/anim/clips");
    const a = createAthlete({ kit: KIT_HOME, detail: "medium", seed: 11 });
    const clips = allClips();
    new GLTFExporter().parse(a.group, (res) => {
      const blob = new Blob([res as ArrayBuffer], { type: "model/gltf-binary" });
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob); link.download = "football-lab-athlete.glb"; link.click();
      a.dispose();
    }, (err) => console.error(err), { binary: true, animations: clips.map((c) => c.clip) });
  };

  build();
  (window as unknown as { __lab: unknown }).__lab = { setLayout: (l: typeof layout) => { layout = l; build(); }, setPose: (p: keyof typeof POSES) => { pose = p; applyAll(); }, cam, exportGlb, stage };
  return () => { for (const a of athletes) a.dispose(); stage.dispose(); };
}

export function textSprite(text: string, colour = "#ffffff"): THREE.Sprite {
  const c = document.createElement("canvas");
  c.width = 512; c.height = 64;
  const g = c.getContext("2d")!;
  g.font = "600 30px Inter, system-ui, sans-serif"; g.textAlign = "center"; g.textBaseline = "middle";
  g.fillStyle = "rgba(10,14,18,0.6)"; const w = g.measureText(text).width + 28; g.fillRect(256 - w / 2, 8, w, 48);
  g.fillStyle = colour; g.fillText(text, 256, 33);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace;
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: t, depthTest: false }));
  s.scale.set(1.6, 0.2, 1);
  return s;
}
