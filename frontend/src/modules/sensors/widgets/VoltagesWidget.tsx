import { useCallback, useMemo, useRef, useState } from "react";
import { SlidersHorizontal } from "lucide-react";
import { useSensorStore } from "@/stores/sensor-store";
import { cn } from "@/lib/utils";
import { sensorNamesForType } from "@/modules/sensors/sensorUtils";
import { SensorFilterMenu } from "@/modules/sensors/SensorFilterMenu";

interface VoltagesWidgetProps {
  serverId: string;
  /** Sensor names hidden from this widget (persisted per widget). Defaults to none (show all). */
  hiddenSensors?: string[];
  /** Persist the new hidden-set into the widget config. Wired by WidgetGrid via onConfigChange. */
  onHiddenChange?: (hidden: string[]) => void;
}

export function VoltagesWidget({ serverId, hiddenSensors, onHiddenChange }: VoltagesWidgetProps) {
  // Subscribe to the readings map for this server (stable ref per server — no React #185).
  const readings = useSensorStore((s) => s.readings[serverId]);
  const [filterOpen, setFilterOpen] = useState(false);
  const filterRef = useRef<HTMLButtonElement>(null);

  // Type-driven: every voltage and current sensor by its REAL name. No hardcoded rails.
  const voltageNames = useMemo(() => sensorNamesForType(readings, "voltage"), [readings]);
  const currentNames = useMemo(() => sensorNamesForType(readings, "current"), [readings]);
  // The full filterable set (voltages then currents), used by the show/hide menu.
  const allSensors = useMemo(() => [...voltageNames, ...currentNames], [voltageNames, currentNames]);

  const hiddenSet = useMemo(() => new Set(hiddenSensors ?? []), [hiddenSensors]);
  const visibleVoltages = voltageNames.filter((n) => !hiddenSet.has(n));
  const visibleCurrents = currentNames.filter((n) => !hiddenSet.has(n));

  const toggle = useCallback(
    (name: string) => {
      if (!onHiddenChange) return;
      const next = new Set(hiddenSensors ?? []);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      onHiddenChange([...next]);
    },
    [hiddenSensors, onHiddenChange]
  );

  const setAll = useCallback(
    (show: boolean) => {
      if (!onHiddenChange) return;
      onHiddenChange(show ? [] : [...allSensors]);
    },
    [allSensors, onHiddenChange]
  );

  if (!serverId) {
    return <div className="flex h-full items-center justify-center text-muted-foreground">—</div>;
  }

  const statusColor = (status?: string) =>
    status === "ok"
      ? "text-emerald-500"
      : status === "warning"
        ? "text-yellow-500"
        : status === "critical"
          ? "text-red-500"
          : "text-muted-foreground";

  // Filter affordance (top-right) — only when there's something to filter + persistence is wired.
  const filterControl =
    onHiddenChange && allSensors.length > 0 ? (
      <div className="absolute right-0 top-0 z-20">
        <button
          ref={filterRef}
          type="button"
          aria-label="Choose sensors"
          aria-haspopup="true"
          aria-expanded={filterOpen}
          onMouseDown={(e) => e.stopPropagation()}
          onClick={() => setFilterOpen((o) => !o)}
          className={cn(
            "flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] hover:bg-muted",
            hiddenSet.size > 0 ? "text-primary" : "text-muted-foreground"
          )}
          title="Choose which sensors to show"
        >
          <SlidersHorizontal className="h-3 w-3" />
          {hiddenSet.size > 0 && (
            <span>
              {allSensors.length - hiddenSet.size}/{allSensors.length}
            </span>
          )}
        </button>
        {filterOpen && (
          <SensorFilterMenu
            anchorRef={filterRef}
            allSensors={allSensors}
            hiddenSet={hiddenSet}
            readings={readings}
            onToggle={toggle}
            onAll={setAll}
            onClose={() => setFilterOpen(false)}
          />
        )}
      </div>
    ) : null;

  const hasAnySensors = allSensors.length > 0;
  const hasVisible = visibleVoltages.length > 0 || visibleCurrents.length > 0;

  let body: React.ReactNode;
  if (!hasAnySensors) {
    body = (
      <div className="flex h-full flex-col items-center justify-center text-center text-sm text-muted-foreground">
        <p>No voltage/current sensors</p>
        <p className="mt-1 text-xs">Waiting for readings or this server reports none.</p>
      </div>
    );
  } else if (!hasVisible) {
    body = (
      <div className="flex h-full flex-col items-center justify-center text-center text-sm text-muted-foreground">
        <p>No sensors selected</p>
        <p className="mt-1 text-xs">Use the filter (top-right) to choose which to show.</p>
      </div>
    );
  } else {
    body = (
      <div className="flex h-full flex-col gap-2 overflow-y-auto">
        {visibleVoltages.length > 0 && (
          <div className="space-y-1.5">
            {visibleVoltages.map((name) => {
              const r = readings?.[name];
              return (
                <div key={name} className="flex items-center justify-between pr-6">
                  <span className="text-xs text-muted-foreground">{name}</span>
                  <span className={cn("font-mono text-xs font-medium", statusColor(r?.status))}>
                    {r?.value != null ? `${r.value}V` : "—"}
                  </span>
                </div>
              );
            })}
          </div>
        )}

        {visibleCurrents.length > 0 && (
          <div className="mt-auto border-t border-border pt-2">
            <div className="space-y-1.5">
              {visibleCurrents.map((name) => {
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

  return (
    <div className="relative h-full">
      {filterControl}
      {body}
    </div>
  );
}
