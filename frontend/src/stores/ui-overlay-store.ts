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
  // Inward "request open" flag the onboarding tour sets to DRIVE the cmdk palette
  // open/closed during its command-palette step (260608-7kj). CommandPalette
  // owns its own local open state and mirrors it OUT to commandOpen; it does not
  // read commandOpen back, so setting commandOpen cannot open it. This separate
  // flag lets the tour open/close the palette while the outward mirror (and thus
  // the keyboard ?-guard) keeps working.
  commandOpenRequest: boolean;
  setHelpOpen: (v: boolean) => void;
  setTourOpen: (v: boolean) => void;
  setCommandOpen: (v: boolean) => void;
  requestCommandOpen: (v: boolean) => void;
  anyOverlayOpen: () => boolean;
}

export const useUIOverlayStore = create<UIOverlayState>((set, get) => ({
  helpOpen: false,
  tourOpen: false,
  commandOpen: false,
  commandOpenRequest: false,
  setHelpOpen: (v) => set({ helpOpen: v }),
  setTourOpen: (v) => set({ tourOpen: v }),
  setCommandOpen: (v) => set({ commandOpen: v }),
  requestCommandOpen: (v) => set({ commandOpenRequest: v }),
  anyOverlayOpen: () => get().helpOpen || get().tourOpen || get().commandOpen,
}));
