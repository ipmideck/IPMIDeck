import { create } from "zustand";

/**
 * Live FanPilot status per server, fed by the backend `fanpilot_status`
 * WebSocket broadcast (and its snapshot replay on connect) instead of
 * per-widget REST polling (04-W4-01).
 *
 * The backend broadcast (backend/core/websocket.py broadcast_fanpilot_status)
 * is only emitted while FanPilot is actively driving a server's fans, so a
 * received broadcast implies `enabled = true`. useWebSocket.ts normalizes the
 * raw wire payload into this widget-facing shape (Decision Q — the widget reads
 * `enabled` + `profile.name`; the store deliberately avoids the raw wire key
 * names so it mirrors the REST status contract the widget already understood).
 */
export interface FanpilotStatus {
  enabled: boolean;
  profile: { name: string } | null;
  mode: string; // "auto" | "manual" | "fanpilot"
  speedPct: number | null;
}

interface FanpilotStore {
  // Decision C — server IDs are strings (TEXT primary key); keys typed as string.
  statusByServer: Record<string, FanpilotStatus | null>;
  setStatus: (serverId: string, status: FanpilotStatus) => void;
  clearServer: (serverId: string) => void;
}

export const useFanpilotStore = create<FanpilotStore>((set) => ({
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
