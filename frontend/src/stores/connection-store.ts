import { create } from "zustand";

export type WSStatus = "connecting" | "connected" | "disconnected";

interface ConnectionState {
  /** Current WebSocket status. The single source of truth for the whole app. */
  wsStatus: WSStatus;
  /** Updated by useWebSocket whenever the connection transitions. */
  setWsStatus: (s: WSStatus) => void;
}

/**
 * Global WS status used by widgets and the page-level banner to decide whether
 * the data they're rendering is live or stale. Set from useWebSocket (called
 * once at the PageLayout level) and read everywhere else.
 */
export const useConnectionStore = create<ConnectionState>((set) => ({
  wsStatus: "disconnected",
  setWsStatus: (s) => set({ wsStatus: s }),
}));

/** Convenience selector hook — true only when WS is fully connected. */
export function useBackendOnline(): boolean {
  return useConnectionStore((s) => s.wsStatus === "connected");
}
