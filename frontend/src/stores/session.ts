import { create } from "zustand";
import { writeLocal } from "../lib/storage";

type SessionState = {
  userId: string | null;
  displayName: string | null;
  setUser: (user: { id: string; display_name: string }) => void;
};

export const useSession = create<SessionState>((set) => ({
  userId: null,
  displayName: null,
  setUser: (user) => {
    writeLocal("bm_guest_id", user.id);
    writeLocal("bm_manager_name", user.display_name);
    set({ userId: user.id, displayName: user.display_name });
  },
}));
