import { create } from "zustand";

export interface Server {
  id: string;
  name: string;
  description: string;
  host: string;
  port: number;
  vendor: string;
  color: string;
  poll_interval: number;
  fanpilot_enabled: boolean;
  is_online: boolean;
  last_seen: string | null;
}

interface ServerState {
  servers: Server[];
  contextServerId: string | null;
  setServers: (servers: Server[]) => void;
  setContextServer: (id: string) => void;
  updateServerStatus: (id: string, isOnline: boolean) => void;
}

export const useServerStore = create<ServerState>((set) => ({
  servers: [],
  contextServerId: null,

  setServers: (servers) =>
    set((state) => ({
      servers,
      contextServerId: state.contextServerId || servers[0]?.id || null,
    })),

  setContextServer: (id) => set({ contextServerId: id }),

  updateServerStatus: (id, isOnline) =>
    set((state) => ({
      servers: state.servers.map((s) =>
        s.id === id ? { ...s, is_online: isOnline } : s
      ),
    })),
}));
