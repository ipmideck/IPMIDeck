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
  const allVoltageNames = useMemo(() => sensorNamesForType(readings, "voltage"), [readings]);
  const currentNames = useMemo(() => sensorNamesForType(readings, "current"), [readings]);

  // 04-W5-02: PSU voltage/current PAIRINGS moved to the dedicated PSU Redundancy widget
  // (Decision S — detected by sensor TYPE there). VoltagesWidget now shows ONLY non-PSU
  // voltage rails: a voltage whose trailing index has a matching current sensor is a PSU
  // rail and is omitted here. Standalone currents are PSU draw, also omitted. On the R720
  // demo dataset this leaves nothing to show (vendor-portable for BMCs that report rails).
  const trailingNum = (s: string) => s.match(/(\d+)\s*$/)?.[1] ?? null;
  const pairedCurrentIndices = useMemo(
    () => new Set(currentNames.map(trailingNum).filter((n): n is string => n != null)),
    [currentNames]
  );
  const voltageNames = useMemo(
    () => allVoltageNames.filter((v) => {
      const num = trailingNum(v);
      return num == null || !pairedCurrentIndices.has(num);
    }),
    [allVoltageNames, pairedCurrentIndices]
  );
  // The full filterable set (non-PSU voltages only), used by the show/hide menu.
  const allSensors = useMemo(() => [...voltageNames], [voltageNames]);

  const hiddenSet = useMemo(() => new Set(hiddenSensors ?? []), [hiddenSensors]);
  const visibleVoltages = voltageNames.filter((n) => !hiddenSet.has(n));

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

  // 04-W5-02: one card per non-PSU voltage rail. PSU V/A pairs are rendered by the
  // dedicated PSU Redundancy widget now, so no voltage↔current pairing happens here.
  type RailCard = { key: string; label: string; voltage: number | null; status?: string };
  const cards: RailCard[] = visibleVoltages.map((vName) => {
    const vr = readings?.[vName];
    return { key: vName, label: vName, voltage: vr?.value ?? null, status: vr?.status };
  });

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
  const hasVisible = visibleVoltages.length > 0;

  let body: React.ReactNode;
  if (!hasAnySensors) {
    // 04-W5-02: with PSU V/A pairs moved out, a server reporting only PSU rails (e.g. the
    // R720 demo dataset) now has no non-PSU voltage rails to show.
    body = (
      <div className="flex h-full flex-col items-center justify-center text-center text-sm text-muted-foreground">
        <p>{t("widget.voltagesNoRails")}</p>
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
            ) : (
              <div className="mt-1 font-mono text-2xl font-bold leading-none text-muted-foreground">—</div>
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
