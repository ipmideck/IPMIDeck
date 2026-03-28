import { useEffect, useState } from "react";
import { get } from "@/api/client";

interface PowerStatusWidgetProps {
  serverId: string;
}

export function PowerStatusWidget({ serverId }: PowerStatusWidgetProps) {
  const [status, setStatus] = useState<string>("unknown");

  useEffect(() => {
    if (!serverId) return;
    const poll = async () => {
      try {
        const data = await get<{ status: string }>(`/api/modules/power/${serverId}/status`);
        setStatus(data.status);
      } catch { /* ignore */ }
    };
    poll();
    const interval = setInterval(poll, 10000);
    return () => clearInterval(interval);
  }, [serverId]);

  const isOn = status === "on";
  return (
    <div className="flex h-full flex-col justify-center">
      <div className="flex items-center gap-2.5">
        <div className={`h-2.5 w-2.5 rounded-full ${isOn ? "bg-emerald-500" : "bg-red-500"}`} />
        <span className={`font-mono text-sm font-semibold ${isOn ? "text-emerald-500" : "text-red-500"}`}>
          {isOn ? "Online" : status === "off" ? "Offline" : "Unknown"}
        </span>
      </div>
    </div>
  );
}
