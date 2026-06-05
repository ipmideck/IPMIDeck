import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { get } from "@/api/client";
import { useBackendOnline } from "@/stores/connection-store";

interface PowerStatusWidgetProps {
  serverId: string;
}

export function PowerStatusWidget({ serverId }: PowerStatusWidgetProps) {
  const { t } = useTranslation();
  const [status, setStatus] = useState<string>("unknown");
  const online = useBackendOnline();

  useEffect(() => {
    if (!serverId) return;
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  if (!serverId) {
    return <div className="flex h-full items-center justify-center text-muted-foreground">—</div>;
  }

  // Without backend connectivity we can't trust the cached status — render it as Unknown
  // with a muted dot rather than the last-known Online/Offline value. Same opacity-50
  // grayscale treatment as the rest of the offline-aware widgets for visual parity.
  if (!online) {
    return (
      <div className="flex h-full flex-col justify-center opacity-50 grayscale transition-[filter,opacity]">
        <div className="flex items-center gap-2.5">
          <div className="h-2.5 w-2.5 rounded-full bg-muted-foreground/40" />
          <span className="font-mono text-sm font-semibold text-muted-foreground">{t("power.unknown")}</span>
        </div>
      </div>
    );
  }

  const isOn = status === "on";
  return (
    <div className="flex h-full flex-col justify-center">
      <div className="flex items-center gap-2.5">
        <div className={`h-2.5 w-2.5 rounded-full ${isOn ? "bg-emerald-500" : "bg-red-500"}`} />
        <span className={`font-mono text-sm font-semibold ${isOn ? "text-emerald-500" : "text-red-500"}`}>
          {isOn ? t("power.online") : status === "off" ? t("power.offline") : t("power.unknown")}
        </span>
      </div>
    </div>
  );
}
