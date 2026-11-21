import * as THREE from "three";

/** Shared scene props: ball, goal (real 7.32 x 2.44 m), simple pitch lines, aim (dashed line + dot). */
export function ballTexture(): THREE.CanvasTexture {
  const c = document.createElement("canvas");
  c.width = 256; c.height = 128;
  const g = c.getContext("2d")!;
  g.fillStyle = "#f7f7f2"; g.fillRect(0, 0, 256, 128);
  g.fillStyle = "#1b1b1b";
  // equirectangular-ish patches (reads as a classic ball while spinning)
  const spots: [number, number, number][] = [[32, 64, 16], [96, 30, 14], [96, 98, 14], [160, 64, 16], [224, 30, 14], [224, 98, 14], [0, 30, 14], [0, 98, 14], [256, 64, 16], [128, 6, 20], [128, 122, 20]];
  for (const [x, y, r] of spots) {
    g.beginPath();
    for (let i = 0; i < 5; i += 1) { const a = (i / 5) * Math.PI * 2 - Math.PI / 2; g.lineTo(x + Math.cos(a) * r, y + Math.sin(a) * r * 0.9); }
    g.closePath(); g.fill();
  }
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

export function makeBall(shadows = true): THREE.Mesh {
  const m = new THREE.Mesh(new THREE.SphereGeometry(0.11, 24, 16), new THREE.MeshStandardMaterial({ map: ballTexture(), roughness: 0.45 }));
  m.castShadow = shadows;
  return m;
}

/** Goal with the mouth centred on (0,0,0) world, opening towards +Z (the pitch), width along X. */
export function makeGoal(width = 7.32, height = 2.44, depth = 2.0): THREE.Group {
  const g = new THREE.Group();
  const white = new THREE.MeshStandardMaterial({ color: "#f5f5f5", roughness: 0.4 });
  const r = 0.06;
  const post = new THREE.CylinderGeometry(r, r, height + r, 16);
  for (const x of [-width / 2 - r, width / 2 + r]) { const p = new THREE.Mesh(post, white); p.position.set(x, (height + r) / 2, 0); p.castShadow = true; g.add(p); }
  const bar = new THREE.Mesh(new THREE.CylinderGeometry(r, r, width + 4 * r, 16), white);
  bar.rotation.z = Math.PI / 2; bar.position.set(0, height + r / 2, 0); bar.castShadow = true; g.add(bar);
  // net: line segments
  const pts: number[] = [];
  const back = -depth, top = height * 0.85;
  const step = 0.18;
  for (let x = -width / 2; x <= width / 2 + 1e-6; x += step) { pts.push(x, height, 0, x, top, back * 0.6, x, top, back * 0.6, x, 0, back); }
  for (let y = 0; y <= height; y += step) { const k = y / height; const z = back * (1 - k) + back * 0.6 * k; pts.push(-width / 2, y, z, width / 2, y, z); }
  for (let z = 0; z >= back; z -= step) for (const x of [-width / 2, width / 2]) { const k = z / back; pts.push(x, 0, z, x, height * (1 - k) + top * k, z); }
  for (let y = 0; y <= height; y += step) for (const x of [-width / 2, width / 2]) pts.push(x, y, 0, x, Math.min(y, top), back * (y > top ? 0.6 : 1 - (y / height) * 0.4));
  const net = new THREE.LineSegments(new THREE.BufferGeometry().setAttribute("position", new THREE.Float32BufferAttribute(pts, 3)), new THREE.LineBasicMaterial({ color: "#ffffff", transparent: true, opacity: 0.55 }));
  g.add(net);
  return g;
}

/** Penalty box lines in front of a goal at the origin (goal line along X, pitch towards +Z). */
export function makeBoxLines(): THREE.LineSegments {
  const w = 40.32 / 2, d = 16.5, sw = 18.32 / 2, sd = 5.5, y = 0.01;
  const pts = [-30, y, 0, 30, y, 0, -w, y, 0, -w, y, d, -w, y, d, w, y, d, w, y, d, w, y, 0, -sw, y, 0, -sw, y, sd, -sw, y, sd, sw, y, sd, sw, y, sd, sw, y, 0];
  // penalty arc
  const arc: number[] = [];
  for (let i = 0; i < 24; i += 1) {
    const a0 = Math.PI * (0.18 + 0.64 * i / 24), a1 = Math.PI * (0.18 + 0.64 * (i + 1) / 24);
    arc.push(Math.cos(a0) * 9.15, y, 11 + Math.sin(a0) * 9.15, Math.cos(a1) * 9.15, y, 11 + Math.sin(a1) * 9.15);
  }
  return new THREE.LineSegments(new THREE.BufferGeometry().setAttribute("position", new THREE.Float32BufferAttribute([...pts, ...arc], 3)), new THREE.LineBasicMaterial({ color: "#ffffff" }));
}

/** Approved minimal aim: dashed line + a dot at the destination; nothing else. */
export class Aim {
  line: THREE.Line;
  dot: THREE.Mesh;
  group = new THREE.Group();
  constructor(colour = "#ffffff") {
    this.line = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineDashedMaterial({ color: colour, dashSize: 0.35, gapSize: 0.22, transparent: true, opacity: 0.95, depthTest: false }));
    this.dot = new THREE.Mesh(new THREE.SphereGeometry(0.13, 16, 10), new THREE.MeshBasicMaterial({ color: colour, depthTest: false }));
    this.line.renderOrder = this.dot.renderOrder = 10;
    this.group.add(this.line, this.dot);
    this.group.visible = false;
  }
  set(points: THREE.Vector3[]) {
    this.line.geometry.dispose();
    this.line.geometry = new THREE.BufferGeometry().setFromPoints(points);
    this.line.computeLineDistances();
    this.dot.position.copy(points[points.length - 1]);
    this.group.visible = true;
  }
  hide() { this.group.visible = false; }
}

/** Lab coordinates (x pitch, y left, z up) -> three.js (X = y, Y = z, Z = x). */
export const toThree = (p: { x: number; y: number; z: number }, out = new THREE.Vector3()) => out.set(p.y, p.z, p.x);
