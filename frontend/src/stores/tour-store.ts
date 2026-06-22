import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * Onboarding-tour state (UX-02). Mirrors theme-store's persist pattern: the
 * "seen" flag is persisted under `ipmideck-tour-seen` so the guided tour only
 * auto-runs once per browser; the transient `run` flag drives react-joyride and
 * is intentionally NOT persisted (partialize keeps only `seen`).
 */
interface TourState {
  seen: boolean;
  run: boolean;
  markSeen: () => void;
  start: () => void;
}

export const useTourStore = create<TourState>()(
  persist(
    (set) => ({
      seen: false,
      run: false,
      markSeen: () => set({ seen: true, run: false }),
      start: () => set({ run: true }),
    }),
    { name: "ipmideck-tour-seen", partialize: (s) => ({ seen: s.seen }) }
  )
);
