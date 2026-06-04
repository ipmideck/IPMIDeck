import { create } from "zustand";

/**
 * Session-only edit-mode flag for the Dashboard widget grid. When ON,
 * drag/resize are enabled and each widget shows a dashed-border indicator +
 * an X delete button. When OFF (default, also after page reload), the layout
 * is locked and per-widget view/mode toggles still work.
 *
 * Not persisted to localStorage or backend by design — the safe, locked-down
 * state should be what you come back to after a refresh.
 */
interface EditModeState {
  editMode: boolean;
  setEditMode: (v: boolean) => void;
  toggleEditMode: () => void;
}

export const useEditModeStore = create<EditModeState>((set) => ({
  editMode: false,
  setEditMode: (editMode) => set({ editMode }),
  toggleEditMode: () => set((s) => ({ editMode: !s.editMode })),
}));
