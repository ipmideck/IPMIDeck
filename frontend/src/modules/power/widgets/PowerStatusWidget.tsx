import { useTranslation } from "react-i18next";
import { useBackendOnline } from "@/stores/connection-store";
import { usePowerStore } from "@/stores/power-store";

interface PowerStatusWidgetProps {
  serverId: string;
}

export function PowerStatusWidget({ serverId }: PowerStatusWidgetProps) {
  const { t } = useTranslation();
  const online = useBackendOnline();
  // 04-W4-01 (debug: power-controls-widget-unknown-status): power state now comes from the
  // backend `power_status` WS broadcast (+ snapshot replay on connect) via usePowerStore —
  // the same single source of truth PowerControlsWidget reads (see PowerControlsWidget.tsx:42).
  // This drops the old redundant 10s REST poll of GET /api/modules/power/{id}/status. Default
  // to "unknown" until the snapshot/broadcast populates the store.
  const status = usePowerStore((s) => s.statusByServer[serverId]?.status) ?? "unknown";

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
