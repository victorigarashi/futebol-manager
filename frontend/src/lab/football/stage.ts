import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

/** Shared 3D stage for every lab tab: renderer, lights, grass, orbit camera and a frame loop. */
export type Stage = {
  renderer: THREE.WebGLRenderer;
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  controls: OrbitControls;
  sun: THREE.DirectionalLight;
  onFrame: (fn: (dt: number, t: number) => void) => void;
  setShadows: (on: boolean) => void;
  dispose: () => void;
  canvas: HTMLCanvasElement;
};
export type StageOptions = { shadows?: boolean; pixelRatio?: number; antialias?: boolean; ground?: "grass" | "none"; groundSize?: number; fov?: number };

export function grassTexture(): THREE.CanvasTexture {
  const c = document.createElement("canvas");
  c.width = 512; c.height = 512;
  const g = c.getContext("2d")!;
  const stripes = 8;
  for (let i = 0; i < stripes; i += 1) { g.fillStyle = i % 2 ? "#3d8f3f" : "#459c46"; g.fillRect(0, (i * 512) / stripes, 512, 512 / stripes); }
  // deterministic grain
  let s = 12345;
  const rnd = () => ((s = (s * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff);
  for (let i = 0; i < 14000; i += 1) {
    g.fillStyle = rnd() < 0.5 ? "rgba(0,0,0,0.05)" : "rgba(255,255,255,0.04)";
    g.fillRect(rnd() * 512, rnd() * 512, 1 + rnd() * 2, 1 + rnd() * 3);
  }
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.anisotropy = 8;
  return t;
}

export function createStage(host: HTMLElement, opts: StageOptions = {}): Stage {
  const renderer = new THREE.WebGLRenderer({ antialias: opts.antialias ?? true, preserveDrawingBuffer: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(opts.pixelRatio ?? Math.min(2, window.devicePixelRatio || 1));
  renderer.shadowMap.enabled = !!opts.shadows;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  host.appendChild(renderer.domElement);
  renderer.domElement.style.display = "block";
  const scene = new THREE.Scene();
  scene.background = new THREE.Color("#9fc6e8");
  scene.fog = new THREE.Fog("#9fc6e8", 60, 160);
  const camera = new THREE.PerspectiveCamera(opts.fov ?? 35, 1, 0.05, 400);
  camera.position.set(2.6, 1.6, 3.6);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(0, 0.95, 0);
  controls.enableDamping = true;
  scene.add(new THREE.HemisphereLight("#dfefff", "#3c5a2c", 1.15));
  const sun = new THREE.DirectionalLight("#fff4e0", 2.4);
  sun.position.set(6, 12, 7);
  sun.castShadow = !!opts.shadows;
  sun.shadow.mapSize.set(2048, 2048);
  const sc = sun.shadow.camera;
  sc.left = sc.bottom = -12; sc.right = sc.top = 12; sc.near = 1; sc.far = 40;
  sun.shadow.bias = -0.0004;
  sun.shadow.normalBias = 0.02;
  scene.add(sun, sun.target);
  const fill = new THREE.DirectionalLight("#cfe2ff", 0.55);
  fill.position.set(-6, 5, -4);
  scene.add(fill);
  if ((opts.ground ?? "grass") === "grass") {
    const size = opts.groundSize ?? 120;
    const tex = grassTexture();
    tex.repeat.set(size / 16, size / 16);
    const ground = new THREE.Mesh(new THREE.PlaneGeometry(size, size), new THREE.MeshStandardMaterial({ map: tex, roughness: 1 }));
    ground.rotation.x = -Math.PI / 2;
    ground.receiveShadow = true;
    ground.name = "ground";
    scene.add(ground);
  }
  const callbacks: ((dt: number, t: number) => void)[] = [];
  let raf = 0, last = performance.now(), elapsed = 0, alive = true;
  const resize = () => {
    const w = host.clientWidth || 800, h = host.clientHeight || 600;
    renderer.setSize(w, h, false);
    renderer.domElement.style.width = `${w}px`; renderer.domElement.style.height = `${h}px`;
    camera.aspect = w / h; camera.updateProjectionMatrix();
  };
  const ro = new ResizeObserver(resize);
  ro.observe(host);
  resize();
  const loop = (now: number) => {
    if (!alive) return;
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now; elapsed += dt;
    for (const cb of callbacks) cb(dt, elapsed);
    controls.update();
    renderer.render(scene, camera);
    raf = requestAnimationFrame(loop);
  };
  raf = requestAnimationFrame(loop);
  return {
    renderer, scene, camera, controls, sun, canvas: renderer.domElement,
    onFrame: (fn) => callbacks.push(fn),
    setShadows: (on) => { renderer.shadowMap.enabled = on; sun.castShadow = on; scene.traverse((o) => { if ((o as THREE.Mesh).isMesh) ((o as THREE.Mesh).material as THREE.Material).needsUpdate = true; }); },
    dispose: () => {
      alive = false; cancelAnimationFrame(raf); ro.disconnect(); controls.dispose();
      scene.traverse((o) => {
        const m = o as THREE.Mesh;
        if (m.geometry) m.geometry.dispose();
      });
      renderer.dispose(); renderer.domElement.remove();
    },
  };
}

/** Small DOM helpers for the lab panels. */
export function el<K extends keyof HTMLElementTagNameMap>(tag: K, attrs: Record<string, string> = {}, ...children: (Node | string)[]): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "text") e.textContent = v; else e.setAttribute(k, v);
  }
  for (const c of children) e.append(c);
  return e;
}

export function slider(label: string, min: number, max: number, step: number, value: number, onInput: (v: number) => void, fmt = (v: number) => v.toFixed(2)): HTMLElement {
  const out = el("span", { class: "val", text: fmt(value) });
  const input = el("input", { type: "range", min: String(min), max: String(max), step: String(step), value: String(value) });
  input.addEventListener("input", () => { const v = Number(input.value); out.textContent = fmt(v); onInput(v); });
  return el("label", { class: "row" }, el("span", { text: label }), input, out);
}

export function select<T extends string>(label: string, options: readonly T[], value: T, onChange: (v: T) => void, names?: Partial<Record<T, string>>): HTMLElement {
  const s = el("select");
  for (const o of options) { const opt = el("option", { value: o, text: names?.[o] ?? o }); if (o === value) opt.selected = true; s.append(opt); }
  s.addEventListener("change", () => onChange(s.value as T));
  return el("label", { class: "row" }, el("span", { text: label }), s);
}

export function button(label: string, onClick: () => void, attrs: Record<string, string> = {}): HTMLButtonElement {
  const b = el("button", { type: "button", ...attrs, text: label });
  b.addEventListener("click", onClick);
  return b;
}

export function checkbox(label: string, value: boolean, onChange: (v: boolean) => void): HTMLElement {
  const c = el("input", { type: "checkbox" });
  c.checked = value;
  c.addEventListener("change", () => onChange(c.checked));
  return el("label", { class: "row check" }, c, el("span", { text: label }));
}
