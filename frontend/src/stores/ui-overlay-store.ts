import { create } from "zustand";

/**
 * Transient open-flags for full-screen overlays (NO persist — these are session-only).
 * The keyboard-shortcuts hook reads these imperatively to suppress page/server
 * shortcuts while any modal/dialog is open (D-07). `commandOpen` is mirrored from
 * CommandPalette's local useState so the guard also covers the Cmd+K palette
 * (REVIEWS MED #9) without querying the DOM for "is a modal open".
 */
interface UIOverlayState {
  helpOpen: boolean;
  tourOpen: boolean; // set by the onboarding tour (03-05); guard reads it now
  commandOpen: boolean; // mirrored from CommandPalette local useState (REVIEWS MED #9)
  setHelpOpen: (v: boolean) => void;
  setTourOpen: (v: boolean) => void;
  setCommandOpen: (v: boolean) => void;
  anyOverlayOpen: () => boolean;
}

export const useUIOverlayStore = create<UIOverlayState>((set, get) => ({
  helpOpen: false,
  tourOpen: false,
  commandOpen: false,
  setHelpOpen: (v) => set({ helpOpen: v }),
  setTourOpen: (v) => set({ tourOpen: v }),
  setCommandOpen: (v) => set({ commandOpen: v }),
  anyOverlayOpen: () => get().helpOpen || get().tourOpen || get().commandOpen,
}));
