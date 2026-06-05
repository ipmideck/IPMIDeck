import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { get } from "@/api/client";
import { useBackendOnline } from "@/stores/connection-store";

interface FanPilotStatusWidgetProps {
  serverId: string;
}

export function FanPilotStatusWidget({ serverId }: FanPilotStatusWidgetProps) {
  const { t } = useTranslation();
  const [status, setStatus] = useState<{ enabled: boolean; profile: { name: string } | null } | null>(null);
  const online = useBackendOnline();

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

  if (!serverId) {
    return <div className="flex h-full items-center justify-center text-muted-foreground">—</div>;
  }

  // Without backend connectivity the cached enabled/profile values are stale.
  // Uses the same opacity-50 grayscale transition treatment as every other offline
  // widget on the dashboard so the page reads as uniformly dim when disconnected.
  if (!online) {
    return (
      <div className="flex h-full items-center justify-between opacity-50 grayscale transition-[filter,opacity]">
        <div className="flex flex-col gap-0.5">
          <span className="text-[11px] font-medium text-muted-foreground">{t("widget.disconnected")}</span>
          <span className="text-sm font-semibold text-muted-foreground">—</span>
        </div>
        <div className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
          {t("widget.offline")}
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full items-center justify-between">
      <div className="flex flex-col gap-0.5">
        <span className="text-[11px] font-medium text-muted-foreground">
          {status?.enabled ? t("widget.fanpilotActive") : t("widget.bmcAuto")}
        </span>
        <span className="text-sm font-semibold">
          {status?.profile?.name || t("widget.noProfile")}
        </span>
      </div>
      <div className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${status?.enabled ? "bg-blue-500/10 text-blue-500" : "bg-muted text-muted-foreground"}`}>
        {status?.enabled ? t("widget.active") : t("widget.auto")}
      </div>
    </div>
  );
}
