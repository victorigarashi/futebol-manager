import * as THREE from "three";

import { readLocal, writeLocal } from "../../../../lib/storage";

/**
 * Configurable match camera (presentation only). Five presets — broadcast, cooperative,
 * dynamic, tactical and custom — all rendered from the same official scene, so changing
 * the camera can never change a result and never touches the rival's screen.
 *
 * Every position is clamped to a safe envelope: the camera stays above the grass and
 * outside the touchlines, so it can never cross the pitch or end up inside a player.
 * The settings are a local preference of each coach (localStorage).
 */
export type CameraPreset = "broadcast" | "coop" | "dynamic" | "tactical" | "custom";

export type CameraSettings = {
  preset: CameraPreset;
  /** Height above the grass, in metres. */
  height: number;
  /** Base distance from the ball, in metres (divided by `zoom`). */
  distance: number;
  /** 0.5 (far) … 3 (close). */
  zoom: number;
  /** Vertical field of view, in degrees. */
  fov: number;
  /** 0 = looks at the ball, 1 = looks far ahead of it (towards the attacked goal). */
  tilt: number;
  /** Slide along the pitch length, in metres. */
  lateral: number;
  /** Follow smoothing, 0 (loose, cinematic) … 1 (tight). Never a cut. */
  follow: number;
};

export type CameraInput = {
  L: number;
  W: number;
  aspect: number;
  /** Ball position in world axes (metres). */
  ball: THREE.Vector3;
  /** Attacking direction along x. */
  dir: 1 | -1;
  /** 0..1 — a decisive moment (dynamic preset moves closer). */
  cinematicK?: number;
  /** Penalty / free kick: camera behind the taker, goal ahead. */
  setPiece?: boolean;
};

export type CameraShot = { pos: THREE.Vector3; look: THREE.Vector3; fov: number };

const PRESET_DEFAULTS: Record<CameraPreset, Omit<CameraSettings, "preset">> = {
  // TV main camera: high in the main stand, narrow lens, pans with the play.
  broadcast: { height: 17, distance: 52, zoom: 1, fov: 27, tilt: 0.32, lateral: 0, follow: 0.5 },
  // Further and wider: the whole collective movement is readable.
  coop: { height: 27, distance: 78, zoom: 1, fov: 38, tilt: 0.18, lateral: 0, follow: 0.38 },
  // Closer and lower; steps in during the decisive moment.
  dynamic: { height: 13, distance: 40, zoom: 1, fov: 34, tilt: 0.5, lateral: 0, follow: 0.72 },
  // High, angled down: positions and shape read like a tactics board.
  tactical: { height: 40, distance: 46, zoom: 1, fov: 46, tilt: 0.72, lateral: 0, follow: 0.3 },
  custom: { height: 17, distance: 52, zoom: 1, fov: 30, tilt: 0.35, lateral: 0, follow: 0.55 },
};

export const PRESET_ORDER: CameraPreset[] = ["broadcast", "coop", "dynamic", "tactical", "custom"];

export const PRESET_LABEL: Record<CameraPreset, string> = {
  broadcast: "Transmissão",
  coop: "Cooperativa",
  dynamic: "Dinâmica",
  tactical: "Tática",
  custom: "Personalizada",
};

export const PRESET_HINT: Record<CameraPreset, string> = {
  broadcast: "Visão lateral elevada, lente fechada, acompanha a bola como uma transmissão de TV.",
  coop: "Mais distante e ampla: mostra a movimentação coletiva dos dois times.",
  dynamic: "Mais próxima e baixa; aproxima ainda mais nas jogadas decisivas.",
  tactical: "Alta e inclinada: prioriza leitura de posições e da forma tática.",
  custom: "Seus próprios ajustes de altura, distância, zoom, ângulo e suavidade.",
};

export function presetSettings(preset: CameraPreset): CameraSettings {
  return { preset, ...PRESET_DEFAULTS[preset] };
}

export function defaultCameraSettings(): CameraSettings {
  return presetSettings("broadcast");
}

const clamp = (v: number, min: number, max: number): number => (Number.isFinite(v) ? Math.min(max, Math.max(min, v)) : min);

export const CAMERA_LIMITS = {
  height: [4, 60],
  distance: [16, 120],
  zoom: [0.5, 3],
  fov: [18, 85],
  tilt: [0, 1],
  lateral: [-40, 40],
  follow: [0, 1],
} as const;

/** Every field through its envelope; a corrupt stored value can never break the view. */
export function normalizeCamera(value: Partial<CameraSettings> | null | undefined): CameraSettings {
  const base = presetSettings(PRESET_ORDER.includes(value?.preset as CameraPreset) ? (value!.preset as CameraPreset) : "broadcast");
  if (!value) return base;
  return {
    preset: base.preset,
    height: clamp(Number(value.height ?? base.height), CAMERA_LIMITS.height[0], CAMERA_LIMITS.height[1]),
    distance: clamp(Number(value.distance ?? base.distance), CAMERA_LIMITS.distance[0], CAMERA_LIMITS.distance[1]),
    zoom: clamp(Number(value.zoom ?? base.zoom), CAMERA_LIMITS.zoom[0], CAMERA_LIMITS.zoom[1]),
    fov: clamp(Number(value.fov ?? base.fov), CAMERA_LIMITS.fov[0], CAMERA_LIMITS.fov[1]),
    tilt: clamp(Number(value.tilt ?? base.tilt), CAMERA_LIMITS.tilt[0], CAMERA_LIMITS.tilt[1]),
    lateral: clamp(Number(value.lateral ?? base.lateral), CAMERA_LIMITS.lateral[0], CAMERA_LIMITS.lateral[1]),
    follow: clamp(Number(value.follow ?? base.follow), CAMERA_LIMITS.follow[0], CAMERA_LIMITS.follow[1]),
  };
}

const KEY = "bm_match_camera_v1";

/** Stored camera; any parse/shape problem falls back to the broadcast preset. */
export function readCameraSettings(): CameraSettings {
  const raw = readLocal(KEY);
  if (!raw) return defaultCameraSettings();
  try { return normalizeCamera(JSON.parse(raw) as Partial<CameraSettings>); } catch { return defaultCameraSettings(); }
}

export function writeCameraSettings(settings: CameraSettings): void {
  writeLocal(KEY, JSON.stringify(normalizeCamera(settings)));
}

/** Next preset in the cycle (used by the in-match camera button). */
export function cyclePreset(preset: CameraPreset): CameraPreset {
  const i = PRESET_ORDER.indexOf(preset);
  return PRESET_ORDER[(i + 1) % PRESET_ORDER.length] ?? "broadcast";
}

/**
 * The camera shot for this frame. The camera sits on the main-stand side (+z) and is
 * clamped outside the touchline and above the grass. The look target leads the ball
 * towards the attacked goal, so the carrier, the options and the goal share the frame.
 */
export function cameraShot(settings: CameraSettings, input: CameraInput, out?: CameraShot): CameraShot {
  const s = normalizeCamera(settings);
  const k = Math.max(0.55, input.L / 105);
  const pos = out?.pos ?? new THREE.Vector3();
  const look = out?.look ?? new THREE.Vector3();
  const ball = input.ball;
  let fov = s.fov;

  // Narrow screens get a much wider lens and step back, so the play still fits.
  const portrait = input.aspect < 0.8;
  if (portrait) fov = Math.min(85, fov * 1.45 + 14);
  else if (input.aspect < 1.25) fov = Math.min(85, fov + 6);

  if (input.setPiece) {
    // Behind the taker: ball low in the frame, wall / keeper / goal mouth ahead.
    const goalX = input.dir * input.L / 2;
    const dx = goalX - ball.x, dz = -ball.z;
    const len = Math.hypot(dx, dz) || 1;
    const back = 9 * k;
    pos.set(ball.x - (dx / len) * back, Math.max(4.5, 6.5 * k), ball.z - (dz / len) * back);
    look.set(goalX - input.dir * 3 * k, 1, ball.z * 0.3);
    return { pos, look, fov: Math.min(80, fov * 0.9) };
  }

  let distance = (s.distance / s.zoom) * (portrait ? 1.1 : 1);
  if (s.preset === "dynamic") {
    const c = clamp(input.cinematicK ?? 0, 0, 1);
    distance *= 1 - 0.22 * c;      // steps in during the decisive moment
    fov += 3 * c;                  // a little wider, so the context stays in frame
  }

  const back = Math.max(6, distance * 0.45);
  const lateral = s.lateral;
  pos.set(
    ball.x + lateral - input.dir * distance * 0.12,
    Math.max(3.5, s.height),
    Math.max(ball.z + back, input.W / 2 + 4 * k),
  );
  // Never graze the grass at very low, very close settings.
  pos.y = Math.max(pos.y, 2.2 + Math.abs(pos.z - ball.z) * 0.05);

  const lead = s.tilt * 20 * k;
  look.set(ball.x + input.dir * lead + lateral * 0.35, 0.3, ball.z * 0.55 - 1.5 * k);
  return { pos, look, fov };
}
