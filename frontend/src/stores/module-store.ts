import { create } from "zustand";
import { get } from "@/api/client";

interface ModuleState {
  enabled: Record<string, boolean>; // module_id -> enabled
  loadModules: () => Promise<void>;
  isEnabled: (moduleId: string) => boolean;
}

export const useModuleStore = create<ModuleState>((set, getState) => ({
  enabled: {},
  loadModules: async () => {
    try {
      const data = await get<{ modules: { id: string; enabled: boolean }[] }>(
        "/api/admin/modules"
      );
      const map: Record<string, boolean> = {};
      for (const m of data.modules) map[m.id] = m.enabled;
      set({ enabled: map });
    } catch {
      /* ignore */
    }
  },
  isEnabled: (moduleId) => {
    const e = getState().enabled;
    // default true when unknown so widgets render before hydration completes
    return e[moduleId] ?? true;
  },
}));
