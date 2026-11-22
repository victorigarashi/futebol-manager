import * as THREE from "three";

/**
 * V8 broadcast camera (presentation only). Like a TV main camera: it sits high in the main
 * stand on the +z side, pans along the touchline with the play and uses a narrow lens, so
 * the pitch, the players and the options read like the approved references 01–03. Near the
 * goal it slides towards that end and turns to keep the goal mouth in frame (reference 06).
 * The renderer keeps its own set-piece, wide, cinematic and portrait framings.
 */
export type BroadcastInput = {
  L: number; W: number;
  ball: THREE.Vector3;          // world position of the ball (y ignored)
  dir: 1 | -1;                  // attacking direction along x
  mates: THREE.Vector3[];       // attacking outfield players (world), to keep options in frame
  aspect: number;
};
export type BroadcastShot = { pos: THREE.Vector3; look: THREE.Vector3; fov: number };

export function broadcastShot(i: BroadcastInput, out?: BroadcastShot): BroadcastShot {
  const s = i.L / 105;
  const k = Math.max(0.5, s);
  const goalX = i.dir * i.L / 2;
  const toGoal = Math.abs(goalX - i.ball.x);
  const near = Math.max(0, Math.min(1, 1 - (toGoal - 14 * k) / (26 * k)));   // 0 midfield … 1 inside the box
  // focus: the ball, pulled towards where the play goes (team-mates ahead) and the goal when near
  let ahead = 0, n = 0;
  for (const m of i.mates) { const d = (m.x - i.ball.x) * i.dir; if (d > -8 * k && d < 30 * k && Math.abs(m.z - i.ball.z) < 26 * k) { ahead += Math.max(0, d); n += 1; } }
  const lead = Math.min(10 * k, 4 * k + (n ? ahead / n : 0) * 0.35);
  // near goal the focus is between the ball and the goal mouth, so carrier, keeper and goal share the frame (ref 06)
  const fx = i.ball.x + i.dir * lead * (1 - near) + (goalX - i.dir * 6 * k - i.ball.x) * near * 0.5;
  const fz = i.ball.z * 0.55 * (1 - near * 0.3);
  // camera: main stand (+z), high, panning along x; near goal it moves towards that end
  // ~53 m from the ball with a ~22° lens: ~80 px athletes on a 941 px frame, ~37 m of play in width
  const standZ = i.W / 2 + 22 * k - near * 10 * k;
  const height = 16 * k - near * 3 * k;
  const camX = fx - i.dir * (4 * k) * (1 - near) - i.dir * near * 6 * k;
  const pos = out?.pos ?? new THREE.Vector3(), look = out?.look ?? new THREE.Vector3();
  pos.set(camX, height, standZ);
  look.set(fx, 0, fz - 2 * k);
  // narrow lens like TV; a bit wider on squarer screens and near the goal (goal + keeper + box)
  const base = i.aspect < 1.25 ? 36 : i.aspect < 1.6 ? 29 : 26;
  const fov = base + near * 3;
  return { pos, look, fov };
}
