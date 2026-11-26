import * as THREE from "three";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  CAMERA_LIMITS, cameraShot, cyclePreset, defaultCameraSettings, normalizeCamera, presetSettings,
  PRESET_ORDER, readCameraSettings, writeCameraSettings, type CameraInput,
} from "./cameraPresets";

const store = new Map<string, string>();
vi.stubGlobal("localStorage", {
  getItem: (k: string) => store.get(k) ?? null,
  setItem: (k: string, v: string) => { store.set(k, v); },
  removeItem: (k: string) => { store.delete(k); },
  clear: () => store.clear(),
});

const input = (over: Partial<CameraInput> = {}): CameraInput => ({
  L: 105, W: 68, aspect: 16 / 9, ball: new THREE.Vector3(10, 0, 4), dir: 1, ...over,
});

const finite = (v: THREE.Vector3) => Number.isFinite(v.x) && Number.isFinite(v.y) && Number.isFinite(v.z);

describe("camera presets", () => {
  beforeEach(() => store.clear());

  it("has a sane default and a preset for every mode", () => {
    const d = defaultCameraSettings();
    expect(d.preset).toBe("broadcast");
    for (const preset of PRESET_ORDER) {
      const s = presetSettings(preset);
      expect(s.preset).toBe(preset);
      for (const value of [s.height, s.distance, s.zoom, s.fov, s.tilt, s.lateral, s.follow]) expect(Number.isFinite(value)).toBe(true);
    }
  });

  it("frames the play from above and outside the touchline for every preset", () => {
    for (const preset of PRESET_ORDER) {
      for (const z of [-34, 0, 34]) {
        const shot = cameraShot(presetSettings(preset), input({ ball: new THREE.Vector3(10, 0, z), aspect: 1.78 }));
        expect(finite(shot.pos)).toBe(true);
        expect(finite(shot.look)).toBe(true);
        expect(shot.pos.y).toBeGreaterThan(2);
        expect(shot.pos.z).toBeGreaterThan(68 / 2);            // outside the far touchline
        expect(shot.fov).toBeGreaterThanOrEqual(18);
        expect(shot.fov).toBeLessThanOrEqual(85);
        expect(shot.pos.distanceTo(shot.look)).toBeLessThan(400);
      }
    }
  });

  it("keeps the goal in the look direction on the attacking side", () => {
    const right = cameraShot(presetSettings("broadcast"), input({ dir: 1 }));
    const left = cameraShot(presetSettings("broadcast"), input({ dir: -1 }));
    expect(right.look.x).toBeGreaterThan(input().ball.x);
    expect(left.look.x).toBeLessThan(input().ball.x);
  });

  it("clamps corrupt or extreme settings instead of breaking the view", () => {
    const wild = normalizeCamera({ preset: "custom", height: 9999, distance: -50, zoom: 0, fov: 900, tilt: 5, lateral: -999, follow: 2 });
    expect(wild.height).toBe(CAMERA_LIMITS.height[1]);
    expect(wild.distance).toBe(CAMERA_LIMITS.distance[0]);
    expect(wild.zoom).toBe(CAMERA_LIMITS.zoom[0]);
    expect(wild.fov).toBe(CAMERA_LIMITS.fov[1]);
    expect(wild.tilt).toBe(1);
    expect(wild.lateral).toBe(CAMERA_LIMITS.lateral[0]);
    const shot = cameraShot(wild, input());
    expect(finite(shot.pos) && finite(shot.look)).toBe(true);
  });

  it("zooming in moves the camera closer", () => {
    const near = cameraShot({ ...presetSettings("custom"), distance: 60, zoom: 2 }, input());
    const far = cameraShot({ ...presetSettings("custom"), distance: 60, zoom: 0.6 }, input());
    expect(near.pos.distanceTo(input().ball)).toBeLessThan(far.pos.distanceTo(input().ball));
  });

  it("the dynamic preset steps in on the decisive moment", () => {
    const still = cameraShot(presetSettings("dynamic"), input({ cinematicK: 0 }));
    const decisive = cameraShot(presetSettings("dynamic"), input({ cinematicK: 1 }));
    expect(decisive.pos.distanceTo(input().ball)).toBeLessThan(still.pos.distanceTo(input().ball));
    expect(decisive.fov).toBeGreaterThan(still.fov);
  });

  it("puts the camera behind the taker on a set piece", () => {
    const shot = cameraShot(presetSettings("broadcast"), input({ ball: new THREE.Vector3(-35, 0, 0), dir: 1, setPiece: true }));
    expect(shot.pos.x).toBeLessThan(-35);      // behind the ball, own goal side
    expect(shot.look.x).toBeGreaterThan(0);    // the goal mouth is ahead
  });

  it("persists and restores the preference, falling back on garbage", () => {
    const custom = { ...presetSettings("tactical"), preset: "custom" as const, height: 33, lateral: 7 };
    writeCameraSettings(custom);
    const back = readCameraSettings();
    expect(back.preset).toBe("custom");
    expect(back.height).toBe(33);
    expect(back.lateral).toBe(7);

    store.set("bm_match_camera_v1", "{not json");
    expect(readCameraSettings().preset).toBe("broadcast");
  });

  it("cycles through every preset", () => {
    let preset = PRESET_ORDER[0];
    const seen = new Set([preset]);
    for (let i = 0; i < PRESET_ORDER.length - 1; i += 1) { preset = cyclePreset(preset); seen.add(preset); }
    expect(seen.size).toBe(PRESET_ORDER.length);
    expect(cyclePreset("custom")).toBe("broadcast");
  });
});
