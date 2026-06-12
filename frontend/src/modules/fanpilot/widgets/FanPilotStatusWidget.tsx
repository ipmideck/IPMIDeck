import { useTranslation } from "react-i18next";
import { useBackendOnline } from "@/stores/connection-store";
import { useFanpilotStore } from "@/stores/fanpilot-store";

interface FanPilotStatusWidgetProps {
  serverId: string;
}

export function FanPilotStatusWidget({ serverId }: FanPilotStatusWidgetProps) {
  const { t } = useTranslation();
  // 04-W4-01: FanPilot status now comes from the `fanpilot_status` WS broadcast
  // (+ snapshot replay on connect) via useFanpilotStore — no more per-widget REST
  // polling. The widget reads `enabled` + `profile.name` (Decision Q — real keys);
  // status is null until the snapshot/broadcast arrives (within ~500ms of mount).
  const status = useFanpilotStore((s) => s.statusByServer[serverId]);
  const online = useBackendOnline();

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
