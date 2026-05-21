import { create } from "zustand";

export type ChartRange = "live" | "1h" | "24h" | "7d";

interface RangeState {
  range: ChartRange;
  setRange: (r: ChartRange) => void;
}

export const useRangeStore = create<RangeState>((set) => ({
  range: "live",
  setRange: (range) => set({ range }),
}));
