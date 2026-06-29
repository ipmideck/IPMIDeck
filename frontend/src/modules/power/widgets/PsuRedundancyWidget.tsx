import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { CheckCircle2, AlertTriangle, XCircle } from "lucide-react";
import { useSensorStore, type SensorReading } from "@/stores/sensor-store";
import { useBackendOnline } from "@/stores/connection-store";
import { naturalCompare } from "@/modules/sensors/sensorUtils";
import { cn } from "@/lib/utils";

interface Props {
  /** Server IDs are STRINGS end-to-end (Decision C). */
  serverId: string;
  w: number;
  h: number;
}

/** A sensor reading carried alongside its (real, vendor-specific) name. */
interface NamedReading extends SensorReading {
  name: string;
}

type PSUStatus = "ok" | "predictive" | "failed" | "missing";

interface DetectedPSU {
  index: number;
  voltage: number | null;
  current: number | null;
  status: PSUStatus;
}

/**
 * PSU detection — Decision S (Codex MEDIUM fix).
 *
 * PSUs are detected via the backend sensor `type` field (`"voltage"` / `"current"`),
 * NOT a name-based regex on "Voltage 1" / "Current 1" (fragile — the SDR parser emits
 * names like "Voltage", "Voltage (2)", "12V", "Vcore"). The voltage and current sensor
 * names are taken in natural order (sensorNamesForType sorts them), and the i-th voltage
 * is paired with the i-th current — the BMC presents PSU1's V+A before PSU2's V+A in the
 * SDR ordering, so positional pairing recovers the per-PSU pairs vendor-agnostically.
 *
 * Status maps from the reading `status` field (ok/warning/critical — the only states the
 * sensor store carries): critical → failed, warning → predictive, ok → ok. A voltage with
 * no paired current (or a reading whose value is null) is treated as "missing".
 *
 * NOTE: the demo dataset reports generic voltage rails (12V/5V/3.3V/Vcore) with NO matching
 * current sensors → detectPSUs returns [] → the widget shows its "No PSU sensors" empty
 * state. That is correct, documented behavior (Decision S — demo UAT shows empty state).
 */
function statusFromReading(status: string | undefined): PSUStatus {
  if (status === "critical") return "failed";
  if (status === "warning") return "predictive";
  return "ok";
}

function detectPSUs(readings: Record<string, SensorReading> | undefined): DetectedPSU[] {
  if (!readings) return [];
  // Decision S: detect by sensor TYPE, never by name. Carry the name only for stable
  // natural ordering so the i-th voltage pairs with the i-th current (PSU1 V+A before
  // PSU2 V+A in SDR order).
  const named: NamedReading[] = Object.entries(readings).map(([name, r]) => ({ ...r, name }));
  const voltages = named
    .filter((s) => s.type === "voltage")
    .sort((a, b) => naturalCompare(a.name, b.name));
  const currents = named
    .filter((s) => s.type === "current")
    .sort((a, b) => naturalCompare(a.name, b.name));
  const count = Math.min(voltages.length, currents.length);
  const psus: DetectedPSU[] = [];
  for (let i = 0; i < count; i++) {
    const v = voltages[i];
    const c = currents[i];
    const voltage = v?.value ?? null;
    const current = c?.value ?? null;
    let status: PSUStatus;
    if (voltage == null || current == null) {
      status = "missing";
    } else {
      // Worst-of-the-pair: a critical on either rail fails the PSU.
      const vSt = statusFromReading(v?.status);
      const cSt = statusFromReading(c?.status);
      status = vSt === "failed" || cSt === "failed"
        ? "failed"
        : vSt === "predictive" || cSt === "predictive"
          ? "predictive"
          : "ok";
    }
    psus.push({ index: i + 1, voltage, current, status });
  }
  return psus;
}

function aggregateTone(psus: DetectedPSU[]): "ok" | "warn" | "fail" {
  const statuses = new Set(psus.map((p) => p.status));
  if (statuses.has("failed") || statuses.has("missing")) return "fail";
  if (statuses.has("predictive")) return "warn";
  return "ok";
}

export function PsuRedundancyWidget({ serverId, w, h }: Props) {
  const { t } = useTranslation();
  // Subscribe to the readings map for this server (stable ref per server).
  const readings = useSensorStore((s) => s.readings[serverId]);
  const online = useBackendOnline();
  const psus = useMemo(() => detectPSUs(readings), [readings]);

  // Empty state — Decision S: acceptable on the demo dataset (no PSU current sensors).
  if (psus.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-1 p-3 text-center">
        <h3 className="text-sm font-semibold text-foreground">{t("widget.psuNoSensorsTitle")}</h3>
        <p className="text-xs text-muted-foreground">{t("widget.psuNoSensorsBody")}</p>
      </div>
    );
  }

  const tone = aggregateTone(psus);
  const okCount = psus.filter((p) => p.status === "ok").length;
  const Icon = tone === "ok" ? CheckCircle2 : tone === "warn" ? AlertTriangle : XCircle;
  // D-04: pill pairs the semantic token color with a distinct icon (CheckCircle2 /
  // AlertTriangle / XCircle) + a translated label. Routed through the foundation
  // --color-success/warning/danger tokens, not raw emerald/yellow/red-500.
  const pillClass = cn(
    "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-semibold",
    tone === "ok" && "bg-success/10 text-success",
    tone === "warn" && "bg-warning/10 text-warning",
    tone === "fail" && "bg-danger/10 text-danger",
  );
  // Aggregate label: when fully redundant use the "Redundant" key (Decision S /
  // hygiene #4 — widget.psuRedundant, NOT psuStatusRedundant); otherwise reuse the
  // worst per-PSU status string for the degraded/failed case.
  const aggLabel =
    tone === "ok"
      ? t("widget.psuRedundant")
      : psus.some((p) => p.status === "failed" || p.status === "missing")
        ? t("widget.psuStatusFailed")
        : t("widget.psuStatusPredictiveFailure");

  // 2x1 (or any single-row) layout: status pill + "N of M OK", no per-PSU cards.
  const isCompact = w <= 2 && h <= 1;

  if (isCompact) {
    return (
      <div className={cn("flex h-full items-center justify-between gap-2 px-2 py-2", !online && "opacity-50 grayscale transition-[filter,opacity]")}>
        <span className={pillClass} aria-label={`PSU: ${aggLabel}`}>
          <Icon className="h-3 w-3" aria-hidden="true" />
          <span className="truncate max-w-[180px]">{aggLabel}</span>
        </span>
        <span className="text-xs tabular-nums text-muted-foreground">
          {okCount} / {psus.length} OK
        </span>
      </div>
    );
  }

  return (
    <div className={cn("flex h-full flex-col gap-3 p-3", !online && "opacity-50 grayscale transition-[filter,opacity]")}>
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-foreground">{t("widget.titlePsuRedundancy")}</h3>
        <span className={pillClass}>
          <Icon className="h-3 w-3" aria-hidden="true" />
          <span>{aggLabel}</span>
        </span>
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-2 overflow-y-auto md:grid-cols-2">
        {psus.map((psu) => {
          const wattage = psu.voltage != null && psu.current != null ? psu.voltage * psu.current : null;
          const dotColor =
            psu.status === "ok"
              ? "bg-success"
              : psu.status === "predictive"
                ? "bg-warning"
                : "bg-danger";
          const statusLabel =
            psu.status === "ok"
              ? t("widget.psuStatusOk")
              : psu.status === "predictive"
                ? t("widget.psuStatusPredictiveFailure")
                : psu.status === "failed"
                  ? t("widget.psuStatusFailed")
                  : t("widget.psuStatusMissing");
          return (
            <div key={psu.index} className="rounded-lg border border-border bg-background/40 p-2.5">
              <div className="mb-1 flex items-center gap-2">
                <span className={cn("inline-block h-2 w-2 rounded-full", dotColor)} />
                <span className="text-sm font-medium">PSU {psu.index}</span>
                <span className="ml-auto truncate text-xs text-muted-foreground">{statusLabel}</span>
              </div>
              <div className="font-mono text-xs text-muted-foreground">
                {psu.voltage != null ? `${psu.voltage.toFixed(0)} V` : "—"} ·{" "}
                {psu.current != null ? `${psu.current.toFixed(2)} A` : "—"}
              </div>
              <div className="mt-0.5 font-mono text-xs text-muted-foreground">
                {wattage != null ? `≈ ${wattage.toFixed(0)} W` : ""}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
