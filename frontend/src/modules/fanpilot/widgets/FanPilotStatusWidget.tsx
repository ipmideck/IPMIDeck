import { useEffect, useState } from "react";
import { get } from "@/api/client";

interface FanPilotStatusWidgetProps {
  serverId: string;
}

export function FanPilotStatusWidget({ serverId }: FanPilotStatusWidgetProps) {
  const [status, setStatus] = useState<{ enabled: boolean; profile: { name: string } | null } | null>(null);

  useEffect(() => {
    if (!serverId) return;
    const poll = async () => {
      try {
        const data = await get<any>(`/api/modules/fanpilot/${serverId}/status`);
        setStatus(data);
      } catch { /* ignore */ }
    };
    poll();
    const interval = setInterval(poll, 5000);
    return () => clearInterval(interval);
  }, [serverId]);

  return (
    <div className="flex h-full items-center justify-between">
      <div className="flex flex-col gap-0.5">
        <span className="text-[11px] font-medium text-muted-foreground">
          {status?.enabled ? "FanPilot Active" : "BMC Auto"}
        </span>
        <span className="text-sm font-semibold">
          {status?.profile?.name || "No profile"}
        </span>
      </div>
      <div className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${status?.enabled ? "bg-blue-500/10 text-blue-500" : "bg-muted text-muted-foreground"}`}>
        {status?.enabled ? "Active" : "Auto"}
      </div>
    </div>
  );
}
