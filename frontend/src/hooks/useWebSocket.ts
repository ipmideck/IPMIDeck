import { useEffect, useRef } from "react";
import { toast } from "sonner";
import i18n from "@/i18n";
import { useSensorStore } from "@/stores/sensor-store";
import { useAlertingStore } from "@/stores/alerting-store";
import { usePowerStore } from "@/stores/power-store";
import { useFanpilotStore } from "@/stores/fanpilot-store";
import { useConnectionStore, type WSStatus } from "@/stores/connection-store";

// Re-export so existing call sites that import WSStatus from this module keep working.
export type { WSStatus };

// Direct store write — no local React state, no return value. PageLayout is the only
// caller and only invokes the hook for its side effect (open + maintain the socket).
const setStatus = (s: WSStatus) => useConnectionStore.getState().setWsStatus(s);

/**
 * Single global WebSocket. Mounted exactly once at the PageLayout shell.
 *
 * Status transitions are written straight to the connection store; every component
 * that needs the value (Header badge, ConnectionBanner, widgets via useBackendOnline)
 * subscribes to the store instead of calling this hook. This avoids opening multiple
 * sockets and avoids re-rendering PageLayout on every transition.
 */
export function useWebSocket(): void {
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);

  useEffect(() => {
    let cancelled = false;
    let retryTimeout: ReturnType<typeof setTimeout> | undefined;

    // Reset the store on mount so a remount (e.g. logout→login, or React StrictMode's
    // dev-time double-mount) never leaks the previous session's "connected" state into
    // the first paint of the new shell.
    setStatus("connecting");

    function scheduleRetry() {
      if (cancelled) return;
      const delays = [1000, 3000, 5000, 10000];
      const delay = delays[Math.min(retryRef.current, delays.length - 1)];
      retryRef.current++;
      retryTimeout = setTimeout(connect, delay);
    }

    function connect() {
      if (cancelled) return;
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";

      // new WebSocket(...) can throw synchronously on malformed URLs or in sandboxed
      // contexts (SecurityError). If it does, no onclose ever fires — we have to
      // schedule the retry ourselves, otherwise the UI is stuck.
      let ws: WebSocket;
      try {
        ws = new WebSocket(`${protocol}//${window.location.host}/ws`);
      } catch {
        setStatus("disconnected");
        scheduleRetry();
        return;
      }
      wsRef.current = ws;
      setStatus("connecting");

      ws.onopen = () => {
        if (cancelled) { ws.close(); return; }
        setStatus("connected");
        retryRef.current = 0;
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === "sensor_update") {
            useSensorStore.getState().updateSensors(msg.server_id, msg.sensors);
          } else if (msg.type === "power_status") {
            // 04-W4-01: consume the backend broadcast (+ snapshot replay) instead of
            // per-widget REST polling. Wire shape: { type, server_id, status }.
            usePowerStore.getState().setStatus(msg.server_id, { status: msg.status });
          } else if (msg.type === "fanpilot_status") {
            // 04-W4-01: consume the backend broadcast (+ snapshot replay) instead of
            // per-widget REST polling. The broadcast wire shape is
            // { type, server_id, mode, active_profile, current_speed_pct, source_temp };
            // normalize it into the widget-facing store shape here (Decision Q — the
            // store mirrors the REST status contract the widget already read). A
            // broadcast is only emitted while FanPilot drives the fans, so enabled=true.
            useFanpilotStore.getState().setStatus(msg.server_id, {
              enabled: msg.mode === "fanpilot",
              profile: msg.active_profile ? { name: msg.active_profile } : null,
              mode: msg.mode ?? "auto",
              speedPct: msg.current_speed_pct ?? null,
            });
          } else if (
            msg.type === "alert" &&
            (msg.severity === "critical" || msg.severity === "warning")
          ) {
            // 04-W3-01: SEL critical/warning alerts. Severity filter — `info` is silently
            // dropped (it stays in the Event Log only). The broadcast wire shape is
            // { type, server_id, severity, sensor, message, value } (broadcast_alert).
            const text = `${msg.sensor || ""}${msg.sensor ? ": " : ""}${msg.message || ""}`.trim();
            const notifEnabled = useAlertingStore.getState().notificationsEnabled;

            // Pitfall 3: gate the system Notification on document.hidden read AT message
            // arrival (not mount) so we never double-fire (toast + notification) when the
            // tab is focused. When hidden + opted-in + granted → Notification; else → toast.
            if (
              notifEnabled &&
              document.hidden &&
              typeof Notification !== "undefined" &&
              Notification.permission === "granted"
            ) {
              const n = new Notification(
                msg.severity === "critical"
                  ? i18n.t("alert.criticalTitle")
                  : i18n.t("alert.warningTitle"),
                { body: text, tag: `sel-${msg.server_id}-${Date.now()}` }
              );
              // Auto-close the notification once the user returns to the tab.
              const onVis = () => {
                if (!document.hidden) {
                  n.close();
                  document.removeEventListener("visibilitychange", onVis);
                }
              };
              document.addEventListener("visibilitychange", onVis);
            } else {
              if (msg.severity === "critical") toast.error(text);
              else toast.warning(text);
            }
          }
        } catch {
          // ignore parse errors
        }
      };

      ws.onclose = () => {
        if (cancelled) return;
        setStatus("disconnected");
        wsRef.current = null;
        scheduleRetry();
      };

      ws.onerror = () => {
        ws.close();
      };
    }

    connect();

    return () => {
      cancelled = true;
      if (retryTimeout) clearTimeout(retryTimeout);
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      // Don't leak "connected" across remounts.
      setStatus("disconnected");
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // No dependencies — runs once
}
