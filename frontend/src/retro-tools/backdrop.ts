import * as THREE from "three";

/**
 * Original stadium backdrop generator for the Retro Career UI (dev tool, not shipped).
 *
 * Renders a daytime football stadium from pitch level (tiered stands, seat rows, an
 * instanced crowd, a truss roof, floodlights, fictitious "Resenha" boards and a mown
 * pitch) and exposes the canvas so scripts/retro/render-backdrops.cjs can save WebP files
 * into public/retro/. Everything is generated in code: no photo or game asset is used.
 */
type View = { name: string; cam: [number, number, number]; look: [number, number, number]; fov: number };
const VIEWS: Record<string, View> = {
  // looking across the pitch at the main stand (menus)
  menu: { name: "menu", cam: [-6, 1.7, 30], look: [8, 9, -22], fov: 46 },
  // along the touchline towards a corner (career hub)
  career: { name: "career", cam: [-44, 2.2, 26], look: [10, 8, -10], fov: 50 },
  // behind a goal, wide (squad / pitch screens)
  squad: { name: "squad", cam: [58, 3.2, 6], look: [-10, 7, -4], fov: 52 },
};

function rng(seed: number) { let s = seed; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296); }

function grassTexture(): THREE.CanvasTexture {
  const c = document.createElement("canvas"); c.width = 2048; c.height = 1024;
  const g = c.getContext("2d")!;
  const stripes = 18;
  for (let i = 0; i < stripes; i += 1) { g.fillStyle = i % 2 ? "#4a8648" : "#53904f"; g.fillRect((i * 2048) / stripes, 0, 2048 / stripes + 1, 1024); }
  const r = rng(7);
  for (let i = 0; i < 60000; i += 1) { g.fillStyle = r() < 0.5 ? "rgba(20,60,20,0.07)" : "rgba(230,255,220,0.05)"; g.fillRect(r() * 2048, r() * 1024, 1 + r() * 2, 1 + r() * 4); }
  // markings (105 x 68 m mapped on 2048 x 1024 with margin)
  const X = (x: number) => 1024 + (x / 120) * 2048, Y = (y: number) => 512 + (y / 80) * 1024;
  g.strokeStyle = "rgba(255,255,255,0.9)"; g.lineWidth = 5;
  g.strokeRect(X(-52.5), Y(-34), X(52.5) - X(-52.5), Y(34) - Y(-34));
  g.beginPath(); g.moveTo(X(0), Y(-34)); g.lineTo(X(0), Y(34)); g.stroke();
  g.beginPath(); g.ellipse(X(0), Y(0), (9.15 / 120) * 2048, (9.15 / 80) * 1024, 0, 0, Math.PI * 2); g.stroke();
  for (const s of [-1, 1]) {
    g.strokeRect(s < 0 ? X(-52.5) : X(52.5 - 16.5), Y(-20.16), (16.5 / 120) * 2048, Y(20.16) - Y(-20.16));
    g.strokeRect(s < 0 ? X(-52.5) : X(52.5 - 5.5), Y(-9.16), (5.5 / 120) * 2048, Y(9.16) - Y(-9.16));
  }
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 16;
  return t;
}

function boardTexture(): THREE.CanvasTexture {
  const c = document.createElement("canvas"); c.width = 4096; c.height = 64;
  const g = c.getContext("2d")!;
  const words = ["RESENHA", "BRASILEIRÃO MANAGER", "TEMPORADA", "RESENHA FC", "DOMINGO TEM FUTEBOL", "A RESENHA TAMBÉM"];
  const cols = [["#168ca3", "#ffffff"], ["#f4f7f8", "#263945"], ["#d6e642", "#263945"], ["#263945", "#d6e642"]];
  let x = 0, i = 0;
  while (x < 4096) {
    const [bg, fg] = cols[i % cols.length]; const w = 340 + (i % 3) * 60;
    g.fillStyle = bg; g.fillRect(x, 0, w, 64);
    g.fillStyle = fg; g.font = "800 34px 'Barlow Condensed', 'Arial Narrow', sans-serif"; g.textAlign = "center"; g.textBaseline = "middle";
    g.fillText(words[i % words.length], x + w / 2, 33);
    x += w; i += 1;
  }
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.wrapS = THREE.RepeatWrapping;
  return t;
}

function seatTexture(primary: string, secondary: string): THREE.CanvasTexture {
  const c = document.createElement("canvas"); c.width = 256; c.height = 256;
  const g = c.getContext("2d")!;
  g.fillStyle = "#59656d"; g.fillRect(0, 0, 256, 256);
  for (let row = 0; row < 16; row += 1) {
    g.fillStyle = row % 5 === 0 ? secondary : primary;
    g.fillRect(0, row * 16 + 2, 256, 9);
    g.fillStyle = "rgba(0,0,0,0.25)"; g.fillRect(0, row * 16 + 11, 256, 3);
  }
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.wrapS = t.wrapT = THREE.RepeatWrapping;
  return t;
}

/** One straight stand along an edge: two tiers, concourse band, crowd, roof. */
function buildStand(scene: THREE.Scene, length: number, depthFrom: number, rot: number, seed: number, seatCol: [string, string]) {
  const grp = new THREE.Group();
  const r = rng(seed);
  const seats = seatTexture(seatCol[0], seatCol[1]);
  const concrete = new THREE.MeshStandardMaterial({ color: "#b9c3c8", roughness: 0.9 });
  const tiers = [{ y0: 0.8, y1: 13, d0: depthFrom, d1: depthFrom + 22 }, { y0: 16, y1: 31, d0: depthFrom + 20, d1: depthFrom + 40 }];
  for (const t of tiers) {
    const rise = t.y1 - t.y0, run = t.d1 - t.d0, slope = Math.hypot(rise, run);
    const tex = seats.clone(); tex.needsUpdate = true; tex.repeat.set(length / 6, slope / 5);
    const plane = new THREE.Mesh(new THREE.PlaneGeometry(length, slope), new THREE.MeshStandardMaterial({ map: tex, roughness: 0.85 }));
    plane.position.set(0, (t.y0 + t.y1) / 2, -(t.d0 + t.d1) / 2);
    plane.rotation.x = -(Math.PI / 2 - Math.atan2(rise, run));
    grp.add(plane);
    // front wall of the tier
    const wall = new THREE.Mesh(new THREE.BoxGeometry(length, 1.3, 0.6), concrete);
    wall.position.set(0, t.y0 - 0.1, -t.d0 + 0.3); grp.add(wall);
    // crowd: small coloured boxes on the rows (sparse, varied)
    const rows = Math.floor(slope / 0.9);
    const perRow = Math.floor(length / 0.62);
    const count = Math.floor(rows * perRow * 0.62);
    const crowd = new THREE.InstancedMesh(new THREE.BoxGeometry(0.42, 0.5, 0.3), new THREE.MeshStandardMaterial({ roughness: 1 }), count);
    const m = new THREE.Matrix4(), col = new THREE.Color();
    const palette = ["#e9ecee", "#c9cfd3", "#9aa4ab", "#6f7b83", "#4a5560", "#b84a4a", "#3d5f8a", "#d8d2c4", "#7f8c6d", "#2f6f80"];
    let n = 0;
    for (let row = 0; row < rows && n < count; row += 1) for (let k = 0; k < perRow && n < count; k += 1) {
      if (r() > 0.62) continue;
      const f = (row + 0.5) / rows;
      const x = -length / 2 + (k + 0.5) * (length / perRow) + (r() - 0.5) * 0.2;
      m.makeTranslation(x, t.y0 + rise * f + 0.55, -(t.d0 + run * f));
      crowd.setMatrixAt(n, m); crowd.setColorAt(n, col.set(palette[Math.floor(r() * palette.length)]).multiplyScalar(0.8 + r() * 0.2)); n += 1;
    }
    crowd.count = n; grp.add(crowd);
  }
  // concourse band (dark) between tiers with a light strip
  const band = new THREE.Mesh(new THREE.BoxGeometry(length, 3.2, 1), new THREE.MeshStandardMaterial({ color: "#2b3a44", roughness: 0.6 }));
  band.position.set(0, 14.4, -(depthFrom + 21)); grp.add(band);
  const strip = new THREE.Mesh(new THREE.BoxGeometry(length, 0.25, 0.2), new THREE.MeshBasicMaterial({ color: "#e9f6ff" }));
  strip.position.set(0, 13.2, -(depthFrom + 20.4)); grp.add(strip);
  // back wall + roof with trusses
  const back = new THREE.Mesh(new THREE.BoxGeometry(length, 34, 1.2), concrete);
  back.position.set(0, 17, -(depthFrom + 41)); grp.add(back);
  const roofMat = new THREE.MeshStandardMaterial({ color: "#dfe7ea", emissive: "#a9b6bd", emissiveIntensity: 0.55, roughness: 0.6, metalness: 0.0, side: THREE.DoubleSide });
  const roof = new THREE.Mesh(new THREE.PlaneGeometry(length + 4, 38), roofMat);
  roof.position.set(0, 37, -(depthFrom + 22)); roof.rotation.x = -Math.PI / 2 + 0.12; grp.add(roof);
  const steel = new THREE.MeshStandardMaterial({ color: "#6d7a82", roughness: 0.5, metalness: 0.6 });
  for (let x = -length / 2; x <= length / 2; x += 12) {
    const beam = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.9, 40), steel);
    beam.position.set(x, 36.2, -(depthFrom + 22)); beam.rotation.x = 0.12; grp.add(beam);
    const col2 = new THREE.Mesh(new THREE.CylinderGeometry(0.35, 0.35, 36, 8), steel);
    col2.position.set(x, 18, -(depthFrom + 40)); grp.add(col2);
  }
  // roof edge with floodlight strip
  const edge = new THREE.Mesh(new THREE.BoxGeometry(length + 4, 1.4, 1.2), steel);
  edge.position.set(0, 39.2, -(depthFrom + 3)); grp.add(edge);
  for (let x = -length / 2 + 4; x < length / 2; x += 6) {
    const lamp = new THREE.Mesh(new THREE.BoxGeometry(1.6, 0.9, 0.4), new THREE.MeshBasicMaterial({ color: "#fffdf2" }));
    lamp.position.set(x, 38.2, -(depthFrom + 2.4)); grp.add(lamp);
  }
  grp.rotation.y = rot;
  scene.add(grp);
}

export function renderBackdrop(viewName: string, width: number, height: number): HTMLCanvasElement {
  const view = VIEWS[viewName] ?? VIEWS.menu;
  const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(1);
  renderer.setSize(width, height);
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.08;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  const scene = new THREE.Scene();
  // soft daytime sky (gradient dome)
  const skyGeo = new THREE.SphereGeometry(900, 32, 16);
  const skyMat = new THREE.ShaderMaterial({
    side: THREE.BackSide, depthWrite: false,
    uniforms: { top: { value: new THREE.Color("#93b6cf") }, mid: { value: new THREE.Color("#b8cedb") }, bot: { value: new THREE.Color("#dde8ee") } },
    vertexShader: "varying vec3 vP; void main(){ vP = normalize(position); gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }",
    fragmentShader: "uniform vec3 top; uniform vec3 mid; uniform vec3 bot; varying vec3 vP; void main(){ float h = vP.y; vec3 c = h > 0.15 ? mix(mid, top, smoothstep(0.15, 0.7, h)) : mix(bot, mid, smoothstep(-0.05, 0.15, h)); gl_FragColor = vec4(c,1.0); }",
  });
  scene.add(new THREE.Mesh(skyGeo, skyMat));
  scene.fog = new THREE.Fog("#cfdde5", 90, 360);
  scene.add(new THREE.HemisphereLight("#eef6ff", "#9aa89a", 1.45));
  const sun = new THREE.DirectionalLight("#fff3df", 2.6);
  sun.position.set(-80, 140, 60); sun.castShadow = true;
  sun.shadow.mapSize.set(4096, 4096);
  Object.assign(sun.shadow.camera, { left: -140, right: 140, top: 140, bottom: -140, near: 10, far: 400 });
  sun.shadow.bias = -0.0003;
  scene.add(sun);
  // pitch
  const pitch = new THREE.Mesh(new THREE.PlaneGeometry(120, 80), new THREE.MeshStandardMaterial({ map: grassTexture(), roughness: 0.95 }));
  pitch.rotation.x = -Math.PI / 2; pitch.receiveShadow = true; scene.add(pitch);
  const apron = new THREE.Mesh(new THREE.PlaneGeometry(260, 220), new THREE.MeshStandardMaterial({ color: "#4a8346", roughness: 1 }));
  apron.rotation.x = -Math.PI / 2; apron.position.y = -0.02; apron.receiveShadow = true; scene.add(apron);
  // ad boards around the pitch
  const boards = boardTexture();
  for (const [len, x, z, ry] of [[110, 0, -38.5, 0], [110, 0, 38.5, Math.PI], [72, -57, 0, Math.PI / 2], [72, 57, 0, -Math.PI / 2]] as const) {
    const t = boards.clone(); t.needsUpdate = true; t.repeat.set(len / 60, 1);
    const b = new THREE.Mesh(new THREE.BoxGeometry(len, 0.9, 0.15), new THREE.MeshBasicMaterial({ map: t }));
    b.position.set(x, 0.45, z); b.rotation.y = ry; scene.add(b);
  }
  // goals
  const white = new THREE.MeshStandardMaterial({ color: "#f5f5f5" });
  for (const s of [-1, 1]) {
    for (const z of [-3.66, 3.66]) { const p = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.06, 2.44, 10), white); p.position.set(s * 52.5, 1.22, z); p.castShadow = true; scene.add(p); }
    const bar = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.06, 7.32, 10), white); bar.rotation.x = Math.PI / 2; bar.position.set(s * 52.5, 2.44, 0); scene.add(bar);
  }
  // four stands
  buildStand(scene, 118, 42, 0, 3, ["#1d7f96", "#d6e642"]);
  buildStand(scene, 118, 42, Math.PI, 5, ["#1d7f96", "#f4f7f8"]);
  buildStand(scene, 78, 62, Math.PI / 2, 9, ["#2a5f7a", "#d6e642"]);
  buildStand(scene, 78, 62, -Math.PI / 2, 11, ["#2a5f7a", "#f4f7f8"]);
  // corner stands close the bowl (no gaps showing the city)
  for (const a of [Math.PI / 4, -Math.PI / 4, (3 * Math.PI) / 4, (-3 * Math.PI) / 4]) buildStand(scene, 56, 66, a, 13 + Math.round(a * 10), ["#2a5f7a", "#f4f7f8"]);
  // corner floodlight masts
  const steel = new THREE.MeshStandardMaterial({ color: "#7d8a92", metalness: 0.6, roughness: 0.4 });
  for (const [x, z] of [[-96, -78], [96, -78], [-96, 78], [96, 78]]) {
    const mast = new THREE.Mesh(new THREE.CylinderGeometry(0.8, 1.3, 70, 10), steel); mast.position.set(x, 35, z); scene.add(mast);
    const head = new THREE.Mesh(new THREE.BoxGeometry(10, 6, 1), new THREE.MeshBasicMaterial({ color: "#fffbe8" })); head.position.set(x * 0.98, 70, z * 0.98); head.lookAt(0, 0, 0); scene.add(head);
  }
  // distant city skyline beyond the stands (horizon)
  const r = rng(21);
  for (let i = 0; i < 90; i += 1) {
    const a = (i / 90) * Math.PI * 2, d = 260 + r() * 60, h = 20 + r() * 55;
    const b = new THREE.Mesh(new THREE.BoxGeometry(14 + r() * 18, h, 14), new THREE.MeshStandardMaterial({ color: new THREE.Color("#9fb3bf").multiplyScalar(0.85 + r() * 0.2), roughness: 1 }));
    b.position.set(Math.cos(a) * d, h / 2, Math.sin(a) * d); scene.add(b);
  }
  scene.traverse((o) => { const m = o as THREE.Mesh; if (m.isMesh && !(m.material instanceof THREE.ShaderMaterial)) { m.castShadow = true; m.receiveShadow = true; } });
  const cam = new THREE.PerspectiveCamera(view.fov, width / height, 0.5, 1500);
  cam.position.set(...view.cam); cam.lookAt(...view.look);
  renderer.render(scene, cam);
  return renderer.domElement;
}

(window as unknown as { renderBackdrop: typeof renderBackdrop }).renderBackdrop = renderBackdrop;
document.body.dataset.ready = "1";
