// 04-W2-07: energy-counter reset state — mirrors app_config energy_reset:{id}.
// Server IDs are STRINGS (Decision C). API access via NAMED imports (Decision D).
// resetAll merges against the backend's AUTHORITATIVE affected_ids (Decision P)
// so servers loaded after this store hydrated still get a fresh timestamp.
import { create } from "zustand";
import { get, post } from "@/api/client";

interface EnergyResetStore {
  /** server_id (string — Decision C) -> ISO timestamp of its last reset, or null. */
  resets: Record<string, string | null>;
  hydrated: boolean;
  hydrate: () => Promise<void>;
  resetServer: (serverId: string) => Promise<void>;
  resetAll: () => Promise<void>;
}

export const useEnergyResetStore = create<EnergyResetStore>((set, getState) => ({
  resets: {},
  hydrated: false,
  hydrate: async () => {
    if (getState().hydrated) return;
    try {
      const res = await get<{ success: boolean; resets?: Record<string, string | null> }>(
        "/api/system/energy-resets"
      );
      if (res?.resets) {
        set({ resets: res.resets, hydrated: true });
      } else {
        set({ hydrated: true });
      }
    } catch {
      set({ hydrated: true });
    }
  },
  resetServer: async (serverId: string) => {
    const res = await post<{ success: boolean; timestamp?: string }>(
      "/api/system/energy-reset",
      { server_id: serverId }
    );
    if (res?.success && res.timestamp) {
      const ts = res.timestamp;
      set((s) => ({ resets: { ...s.resets, [serverId]: ts } }));
    }
  },
  // Decision P (Codex MEDIUM fix): merge against the AFFECTED IDS returned by the
  // backend, NOT just keys already present in the local map.
  resetAll: async () => {
    const res = await post<{ success: boolean; affected_ids?: string[]; timestamp?: string }>(
      "/api/system/energy-reset",
      { server_id: null }
    );
    if (res?.success && res.affected_ids && res.timestamp) {
      const ts = res.timestamp;
      const affected = res.affected_ids;
      set((s) => {
        const next: Record<string, string | null> = { ...s.resets };
        for (const id of affected) {
          next[id] = ts;
        }
        return { resets: next };
      });
    }
  },
}));
