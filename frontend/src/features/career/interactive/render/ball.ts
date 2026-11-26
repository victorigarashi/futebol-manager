/**
 * Visual rolling of the ball: the direction and amount of spin follow the official
 * displacement, so the ball always rolls the way it travels, never slides or
 * teleports-spins. Purely cosmetic — the trajectory is the server's.
 *
 * World axes: x along the pitch, z across it, y up.
 */
export type BallStep = {
  /** Unit rotation axis (right-hand rule), in world axes. */
  axis: [number, number, number];
  /** Rotation applied this frame, radians (capped so a snapshot jump cannot blur the ball). */
  angle: number;
  /** Distance travelled on the grass, metres. */
  distance: number;
};

/** A single frame can never spin the ball more than half a turn. */
const MAX_ANGLE = Math.PI;

/**
 * Rolling without slipping: ω = (up × v) / r, so the contact point is momentarily still.
 * For motion along +x the ball turns about -z (the top moves forward).
 */
export function rollStep(prev: { x: number; z: number }, next: { x: number; z: number }, radius: number): BallStep {
  const dx = next.x - prev.x;
  const dz = next.z - prev.z;
  const distance = Math.hypot(dx, dz);
  if (!(distance > 1e-6)) return { axis: [0, 0, -1], angle: 0, distance: 0 };
  const r = Math.max(0.03, radius);
  // up × v = (vz, 0, -vx)
  return { axis: [dz / distance, 0, -dx / distance], angle: Math.min(MAX_ANGLE, distance / r), distance };
}
