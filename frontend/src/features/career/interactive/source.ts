import { api, type InteractiveActionPayload, type InteractiveView } from "../../../lib/api";

/** Where a Modo Jogável screen reads the official state and sends gestures (a league room, or the Gameplay Lab). */
export type MatchSource = {
  key: string;
  fetch: (revision?: number) => Promise<InteractiveView>;
  act: (payload: InteractiveActionPayload) => Promise<{ status: string; revision: number; match: InteractiveView }>;
};

export function roomSource(roomId: string): MatchSource {
  return {
    key: roomId,
    fetch: (revision) => api.interactive(roomId, revision).then((r) => r.data),
    act: (payload) => api.interactiveAction(roomId, payload).then((r) => r.data),
  };
}

