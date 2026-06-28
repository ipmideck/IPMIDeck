import { useTranslation } from "react-i18next";
import { Power, PowerOff, HelpCircle } from "lucide-react";
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
          {/* D-04: shape + icon companion so state never rides on color alone. */}
          <HelpCircle className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
          <span className="font-mono text-base font-semibold text-muted-foreground">{t("power.unknown")}</span>
        </div>
      </div>
    );
  }

  // D-04 — every power state pairs the semantic color with a distinct lucide icon
  // (Power / PowerOff / HelpCircle) so red-green colorblind users still read it.
  const isOn = status === "on";
  const isOff = status === "off";
  const StateIcon = isOn ? Power : isOff ? PowerOff : HelpCircle;
  const stateClass = isOn ? "text-success" : isOff ? "text-danger" : "text-muted-foreground";
  const label = isOn ? t("power.online") : isOff ? t("power.offline") : t("power.unknown");
  return (
    <div className="flex h-full flex-col justify-center">
      <div className="flex items-center gap-2.5">
        <StateIcon className={`h-4 w-4 shrink-0 ${stateClass}`} aria-hidden="true" />
        <span className={`font-mono text-base font-semibold ${stateClass}`}>{label}</span>
      </div>
    </div>
  );
}
