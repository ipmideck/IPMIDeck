import { create } from "zustand";

/**
 * Live power status per server, fed by the backend `power_status` WebSocket
 * broadcast (and its snapshot replay on connect) instead of per-widget REST
 * polling (04-W4-01). Wire shape from backend/core/websocket.py
 * broadcast_power_status: { type: "power_status", server_id, status }.
 */
export interface PowerStatus {
  /** "on" | "off" | "unknown" — verbatim from get_power_status. */
  status: string;
}

interface PowerStore {
  // Decision C — server IDs are strings (TEXT primary key); keys typed as string.
  statusByServer: Record<string, PowerStatus | null>;
  setStatus: (serverId: string, status: PowerStatus) => void;
  clearServer: (serverId: string) => void;
}

export const usePowerStore = create<PowerStore>((set) => ({
  statusByServer: {},
  setStatus: (serverId, status) =>
    set((s) => ({
      statusByServer: { ...s.statusByServer, [serverId]: status },
    })),
  clearServer: (serverId) =>
    set((s) => {
      const next = { ...s.statusByServer };
      delete next[serverId];
      return { statusByServer: next };
    }),
}));
