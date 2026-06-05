import { useCallback, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { SlidersHorizontal } from "lucide-react";
import { useSensorStore } from "@/stores/sensor-store";
import { useBackendOnline } from "@/stores/connection-store";
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
  const { t } = useTranslation();
  // Subscribe to the readings map for this server (stable ref per server — no React #185).
  const readings = useSensorStore((s) => s.readings[serverId]);
  const online = useBackendOnline();
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

  const dotColor = (status?: string) =>
    status === "ok"
      ? "bg-emerald-500"
      : status === "warning"
        ? "bg-yellow-500"
        : status === "critical"
          ? "bg-red-500"
          : "bg-muted-foreground/40";

  // Pair each voltage with the current sharing its trailing index → one card per PSU/rail.
  // Currents without a matching voltage get their own card (and vice-versa).
  const trailingNum = (s: string) => s.match(/(\d+)\s*$/)?.[1] ?? null;
  type PsuCard = { key: string; label: string; voltage: number | null; current: number | null; status?: string };
  const cards: PsuCard[] = (() => {
    const out: PsuCard[] = [];
    const usedCurrents = new Set<string>();
    for (const vName of visibleVoltages) {
      const num = trailingNum(vName);
      const cName =
        num != null
          ? visibleCurrents.find((c) => trailingNum(c) === num && !usedCurrents.has(c))
          : undefined;
      if (cName) usedCurrents.add(cName);
      const vr = readings?.[vName];
      const cr = cName ? readings?.[cName] : undefined;
      out.push({
        key: vName,
        label: vName,
        voltage: vr?.value ?? null,
        current: cr?.value ?? null,
        status: vr?.status ?? cr?.status,
      });
    }
    for (const cName of visibleCurrents) {
      if (usedCurrents.has(cName)) continue;
      const cr = readings?.[cName];
      out.push({ key: cName, label: cName, voltage: null, current: cr?.value ?? null, status: cr?.status });
    }
    return out;
  })();

  // Filter affordance (top-right) — only when there's something to filter + persistence is wired.
  const filterControl =
    onHiddenChange && allSensors.length > 0 ? (
      <div className="absolute right-0 top-0 z-20">
        <button
          ref={filterRef}
          type="button"
          aria-label={t("widget.chooseSensors")}
          aria-haspopup="true"
          aria-expanded={filterOpen}
          onMouseDown={(e) => e.stopPropagation()}
          onClick={() => setFilterOpen((o) => !o)}
          className={cn(
            "flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] hover:bg-muted",
            hiddenSet.size > 0 ? "text-primary" : "text-muted-foreground"
          )}
          title={t("widget.chooseSensorsTitle")}
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
        <p>{t("widget.voltagesNoSensorsTitle")}</p>
        <p className="mt-1 text-xs">{t("widget.voltagesNoSensorsHint")}</p>
      </div>
    );
  } else if (!hasVisible) {
    body = (
      <div className="flex h-full flex-col items-center justify-center text-center text-sm text-muted-foreground">
        <p>{t("widget.voltagesNoneSelectedTitle")}</p>
        <p className="mt-1 text-xs">{t("widget.voltagesNoneSelectedHint")}</p>
      </div>
    );
  } else {
    body = (
      <div
        className={cn(
          "grid content-start gap-2 overflow-y-auto [grid-template-columns:repeat(auto-fill,minmax(120px,1fr))]",
          filterControl ? "pt-6" : ""
        )}
      >
        {cards.map((c) => (
          <div key={c.key} className="rounded-lg border border-border bg-background/40 p-2.5">
            <div className="flex items-center gap-1.5">
              <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", dotColor(c.status))} />
              <span className="truncate text-[11px] text-muted-foreground">{c.label}</span>
            </div>
            {c.voltage != null ? (
              <div className="mt-1 flex items-baseline gap-1">
                <span className="font-mono text-2xl font-bold leading-none tabular-nums">{c.voltage}</span>
                <span className="text-xs text-muted-foreground">V</span>
              </div>
            ) : c.current != null ? (
              <div className="mt-1 flex items-baseline gap-1">
                <span className="font-mono text-2xl font-bold leading-none tabular-nums">{c.current}</span>
                <span className="text-xs text-muted-foreground">A</span>
              </div>
            ) : (
              <div className="mt-1 font-mono text-2xl font-bold leading-none text-muted-foreground">—</div>
            )}
            {c.voltage != null && c.current != null && (
              <div className="mt-1.5 flex items-center gap-1.5 font-mono text-[11px] text-muted-foreground">
                <span>{c.current} A</span>
                <span>·</span>
                <span>≈{Math.round(c.voltage * c.current)} W</span>
              </div>
            )}
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="relative h-full">
      {filterControl}
      <div className={cn("h-full", !online && "opacity-50 grayscale transition-[filter,opacity]")}>
        {body}
      </div>
    </div>
  );
}
