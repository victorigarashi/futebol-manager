import type { Pose } from "../athlete/rig";
import { CLIPS, GK_READY_POSE, samplePose } from "./clips";

/** Static poses for the Characters tab (sampled from the clips, so they are grounded). */
export const POSES: Record<string, Pose> = {
  get idle() { return samplePose(CLIPS.idle, 0); },
  get bind() { return { rootY: 0 }; },
  get corrida() { return samplePose(CLIPS.run, 0.12); },
  get sprint() { return samplePose(CLIPS.sprint, 0.21); },
  get chute_contato() { return samplePose(CLIPS.shot, CLIPS.shot.meta.contact!.u); },
  get passe_contato() { return samplePose(CLIPS.pass_short, CLIPS.pass_short.meta.contact!.u); },
  get cabeceio() { return samplePose(CLIPS.header, CLIPS.header.meta.contact!.u); },
  get goleiro_espera() { return samplePose(CLIPS.gk_ready, 0) ?? GK_READY_POSE; },
  get goleiro_salto() { return samplePose(CLIPS.gk_jump, CLIPS.gk_jump.meta.contact!.u); },
};
