import { useEffect, useRef, useState } from "react";
import { useSensorStore } from "@/stores/sensor-store";

export type WSStatus = "connecting" | "connected" | "disconnected";

export function useWebSocket() {
  const [status, setStatus] = useState<WSStatus>("disconnected");
  const wsRef = useRef<WebSocket | null>(null);
  const updateSensors = useSensorStore((s) => s.updateSensors);
  const retryRef = useRef(0);

  useEffect(() => {
    function connect() {
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const ws = new WebSocket(`${protocol}//${window.location.host}/ws`);
      wsRef.current = ws;
      setStatus("connecting");

      ws.onopen = () => {
        setStatus("connected");
        retryRef.current = 0;
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === "sensor_update") {
            updateSensors(msg.server_id, msg.sensors);
          }
          // Other message types can be handled here
        } catch {
          // ignore parse errors
        }
      };

      ws.onclose = () => {
        setStatus("disconnected");
        wsRef.current = null;
        // Reconnect with linear backoff: 1s, 3s, 5s, 10s, then every 10s
        const delays = [1000, 3000, 5000, 10000];
        const delay = delays[Math.min(retryRef.current, delays.length - 1)];
        retryRef.current++;
        setTimeout(connect, delay);
      };

      ws.onerror = () => {
        ws.close();
      };
    }

    connect();

    return () => {
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [updateSensors]);

  return { status };
}
