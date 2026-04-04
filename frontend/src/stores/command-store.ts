import { create } from "zustand";

export interface CommandEntry {
  id: number;
  server_id: string;
  command_type: string;
  command_detail: string;
  result: string;
  error_message: string | null;
  timestamp: string;
}

interface CommandState {
  entries: CommandEntry[];
  isOpen: boolean;
  addEntry: (entry: CommandEntry) => void;
  setEntries: (entries: CommandEntry[]) => void;
  toggle: () => void;
}

export const useCommandStore = create<CommandState>((set) => ({
  entries: [],
  isOpen: false,

  addEntry: (entry) =>
    set((state) => ({
      entries: [entry, ...state.entries].slice(0, 200),
    })),

  setEntries: (entries) => set({ entries }),

  toggle: () => set((state) => ({ isOpen: !state.isOpen })),
}));
