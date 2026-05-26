import { useMemo } from "react";
import { useSensorStore } from "@/stores/sensor-store";
import { cn } from "@/lib/utils";
import { sensorNamesForType } from "@/modules/sensors/sensorUtils";

interface VoltagesWidgetProps {
  serverId: string;
}

export function VoltagesWidget({ serverId }: VoltagesWidgetProps) {
  // Subscribe to the readings map for this server (stable ref per server — no React #185).
  const readings = useSensorStore((s) => s.readings[serverId]);

  // Type-driven: every voltage and current sensor by its REAL name. No hardcoded rails.
  const voltageNames = useMemo(() => sensorNamesForType(readings, "voltage"), [readings]);
  const currentNames = useMemo(() => sensorNamesForType(readings, "current"), [readings]);

  if (!serverId) {
    return <div className="flex h-full items-center justify-center text-muted-foreground">—</div>;
  }

  const hasAny = voltageNames.length > 0 || currentNames.length > 0;
  if (!hasAny) {
    return (
      <div className="flex h-full flex-col items-center justify-center text-center text-sm text-muted-foreground">
        <p>No voltage/current sensors</p>
        <p className="mt-1 text-xs">Waiting for readings or this server reports none.</p>
      </div>
    );
  }

  const statusColor = (status?: string) =>
    status === "ok"
      ? "text-emerald-500"
      : status === "warning"
        ? "text-yellow-500"
        : status === "critical"
          ? "text-red-500"
          : "text-muted-foreground";

  return (
    <div className="flex h-full flex-col gap-2 overflow-y-auto">
      {voltageNames.length > 0 && (
        <div className="space-y-1.5">
          {voltageNames.map((name) => {
            const r = readings?.[name];
            return (
              <div key={name} className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground">{name}</span>
                <span className={cn("font-mono text-xs font-medium", statusColor(r?.status))}>
                  {r?.value != null ? `${r.value}V` : "—"}
                </span>
              </div>
            );
          })}
        </div>
      )}

      {currentNames.length > 0 && (
        <div className="mt-auto border-t border-border pt-2">
          <div className="space-y-1.5">
            {currentNames.map((name) => {
              const r = readings?.[name];
              return (
                <div key={name} className="flex items-center justify-between">
                  <span className="text-xs text-muted-foreground">{name}</span>
                  <span className={cn("font-mono text-xs font-medium", statusColor(r?.status))}>
                    {r?.value != null ? `${r.value}A` : "—"}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
