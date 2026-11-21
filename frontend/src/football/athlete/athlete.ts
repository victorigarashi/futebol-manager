import * as THREE from "three";
import { bodyGeometry, REGIONS, type Detail, type Region } from "./body";
import { cosmeticFor, regionPalette, shirtTexture, type Cosmetic, type KitSpec } from "./kit";
import { applyPose, createSkeleton, type Pose, type Rig } from "./rig";

export type Athlete = {
  group: THREE.Group;          // world placement (position = feet on the ground, rotation.y = facing)
  mesh: THREE.SkinnedMesh;
  rig: Rig;
  keeper: boolean;
  setPose: (p: Pose) => void;
  dispose: () => void;
};
export type AthleteOptions = { kit: KitSpec; keeper?: boolean; detail?: Detail; shadows?: boolean; look?: Cosmetic; seed?: number; regionColours?: Partial<Record<Region, string>> };

/** Per-player colours over the shared geometry. */
function colourAttribute(shared: THREE.BufferGeometry, palette: Record<Region, string>): THREE.BufferAttribute {
  const region = shared.getAttribute("region") as THREE.BufferAttribute;
  const pos = shared.getAttribute("position") as THREE.BufferAttribute;
  const cols = REGIONS.map((r) => new THREE.Color(palette[r]));
  const out = new Float32Array(region.count * 3);
  for (let i = 0; i < region.count; i += 1) {
    const c = cols[Math.round(region.getX(i))];
    out[i * 3] = c.r; out[i * 3 + 1] = c.g; out[i * 3 + 2] = c.b;
    // cheap baked occlusion (no texture): darker towards the ground, under the chin, inner thighs and armpits
    const x = pos.getX(i), y = pos.getY(i), z = pos.getZ(i);
    let ao = 0.8 + 0.2 * Math.min(1, y / 1.25);
    if (y > 1.52 && y < 1.62 && z < 0.06) ao *= 0.86 + 0.14 * Math.min(1, (y - 1.52) / 0.1);   // under the jaw
    if (y < 0.9 && Math.abs(x) < 0.06) ao *= 0.82;                                             // between the legs
    if (y > 1.3 && y < 1.42 && Math.abs(x) > 0.14 && Math.abs(x) < 0.2) ao *= 0.88;            // armpits
    out[i * 3] *= ao; out[i * 3 + 1] *= ao; out[i * 3 + 2] *= ao;
  }
  return new THREE.BufferAttribute(out, 3);
}

export function createAthlete(opts: AthleteOptions): Athlete {
  const keeper = !!opts.keeper;
  const look = opts.look ?? cosmeticFor(opts.seed ?? 7);
  const shared = bodyGeometry(opts.detail ?? "high", { keeper, hair: look.hairStyle, build: look.build });
  const geo = new THREE.BufferGeometry();
  for (const name of ["position", "normal", "uv", "skinIndex", "skinWeight", "region"]) geo.setAttribute(name, shared.getAttribute(name));
  geo.setIndex(shared.index);
  geo.boundingSphere = shared.boundingSphere;
  geo.setAttribute("color", colourAttribute(shared, { ...regionPalette(opts.kit, look, keeper), ...opts.regionColours }));
  const map = shirtTexture(opts.kit, look);
  const material = new THREE.MeshStandardMaterial({ vertexColors: true, map, roughness: 0.78, metalness: 0 });
  const rig = createSkeleton();
  const mesh = new THREE.SkinnedMesh(geo, material);
  mesh.add(rig.root);
  mesh.updateMatrixWorld(true);
  mesh.bind(rig.skeleton);
  mesh.castShadow = !!opts.shadows;
  mesh.receiveShadow = false;
  mesh.frustumCulled = false;
  const group = new THREE.Group();
  group.add(mesh);
  return {
    group, mesh, rig, keeper,
    setPose: (p) => applyPose(rig, p),
    dispose: () => { geo.dispose(); map.dispose(); material.dispose(); },
  };
}
