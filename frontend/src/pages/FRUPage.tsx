import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { Header } from "@/components/layout/Header";
import { useServerStore } from "@/stores/server-store";
import { useSensorStore } from "@/stores/sensor-store";
import { useBackendOnline } from "@/stores/connection-store";
import { get, post } from "@/api/client";
import { toast } from "sonner";
import { EmptyState } from "@/components/common/EmptyState";
import { intlLocale } from "@/i18n/languages";
import { RefreshCw, Copy, ServerOff, CircuitBoard, Server, Cpu, Info } from "lucide-react";

interface FRUData {
  sections: Record<string, { field: string; value: string }[]>;
  fetched_at: string | null;
}

/** Strip ipmitool's "FRU Device Description :" noise and give common devices a friendly label. */
function cleanSection(raw: string, t: TFunction): string {
  const s = raw.replace(/^FRU Device Description\s*:?\s*/i, "").trim();
  if (/builtin fru device/i.test(s)) return t("fru.section.systemBoard");
  const ps = s.match(/^PS(\d+)/i);
  if (ps) return t("fru.section.powerSupply", { n: ps[1] });
  const bp = s.match(/^BP(\d+)/i);
  if (bp) return t("fru.section.backplane", { n: bp[1] });
  if (/^PERC/i.test(s) || /storage cntlr/i.test(s)) return t("fru.section.storageController");
  if (/^NDC/i.test(s)) return t("fru.section.networkDaughterCard");
  return s || raw;
}

/** Pick the first present value among candidate field names within a section. */
function pick(fields: { field: string; value: string }[], names: string[]): string | undefined {
  for (const n of names) {
    const f = fields.find((x) => x.field.toLowerCase() === n.toLowerCase());
    if (f?.value) return f.value;
  }
  return undefined;
}

export default function FRUPage() {
  const { t, i18n } = useTranslation();
  const contextServerId = useServerStore((s) => s.contextServerId);
  const readings = useSensorStore((s) => (contextServerId ? s.readings[contextServerId] : undefined));
  const [data, setData] = useState<FRUData | null>(null);
  const [loading, setLoading] = useState(false);
  const online = useBackendOnline();

  const loadFRU = async () => {
    if (!contextServerId) return;
    try {
      const res = await get<FRUData>(`/api/modules/fru/${contextServerId}`);
      setData(res);
    } catch { /* ignore */ }
  };

  const refresh = async () => {
    if (!contextServerId) return;
    setLoading(true);
    try {
      await post(`/api/modules/fru/${contextServerId}/refresh`);
      await loadFRU();
      toast.success(t("fru.refreshed"));
    } catch {
      toast.error(t("fru.refreshFailed"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadFRU(); }, [contextServerId]);

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    toast.success(t("fru.copied"));
  };

  const sections = data?.sections || {};
  const hasSections = Object.keys(sections).length > 0;

  // CPUs detected — inferred from per-CPU temperature sensors (IPMI FRU has no CPU inventory).
  const cpuCount = useMemo(() => {
    if (!readings) return 0;
    return Object.entries(readings).filter(
      ([name, r]) => r?.type === "temperature" && /^cpu\b/i.test(name)
    ).length;
  }, [readings]);

  // Build a system summary from the system-board / product / chassis FRU devices, EXCLUDING
  // peripheral devices (PSUs, backplanes, storage controllers, NIC) whose own "Board Product"
  // would otherwise be mistaken for the system model. Works for both the real BMC naming
  // ("Builtin FRU Device") and the demo/clean naming ("BOARD"/"PRODUCT"/"CHASSIS").
  const summary = useMemo(() => {
    const sysFields: { field: string; value: string }[] = [];
    for (const [k, f] of Object.entries(sections)) {
      if (/\bPS\d|power\s*sup|^bp\d|backplane|perc|storage cntlr|\bndc\b|\bdrive\b|network/i.test(k)) continue;
      sysFields.push(...f);
    }
    if (sysFields.length === 0) return null;
    const model = pick(sysFields, ["Product Name", "Board Product"]);
    const vendor = pick(sysFields, ["Product Manufacturer", "Board Mfg"]);
    const serviceTag = pick(sysFields, ["Product Serial", "Chassis Serial", "Board Serial"]);
    const assetTag = pick(sysFields, ["Product Asset Tag", "Chassis Asset Tag"]);
    if (!model && !vendor && !serviceTag) return null;
    return { model, vendor, serviceTag, assetTag };
  }, [sections]);

  return (
    <>
      <Header title={t("nav.fru")}>
        <button
          onClick={refresh}
          disabled={loading || !online}
          title={!online ? t("header.backendDisconnected") : undefined}
          className="flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
        >
          <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} /> {t("fru.refresh")}
        </button>
      </Header>
      <div className="flex-1 overflow-auto p-6">
        {!hasSections ? (
          !contextServerId ? (
            <EmptyState
              icon={ServerOff}
              title={t("fru.noServerTitle")}
              description={t("fru.noServerDescription")}
            />
          ) : (
            <EmptyState
              icon={CircuitBoard}
              title={t("fru.noDataTitle")}
              description={t("fru.noDataDescription")}
            />
          )
        ) : (
          // Earned hierarchy (D-06): a max-width frame lets the warm canvas border the
          // lifted surfaces; no new color, only the inherited blueprint layers + weight.
          <div className="mx-auto max-w-6xl space-y-6">
            {/* System overview — the headline specs, pulled from the system-board FRU device.
                The lead card: elevated off the canvas (shadow-sm) so it reads as primary. */}
            {summary && (summary.model || summary.vendor || summary.serviceTag) && (
              <div className="rounded-lg border border-border bg-card p-5 shadow-sm">
                <div className="flex items-start gap-4">
                  <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-primary/10">
                    <Server className="h-6 w-6 text-primary" />
                  </div>
                  <div className="min-w-0 flex-1">
                    {/* Value-first: the system model is the lead element, foreground + bold. */}
                    <h2 className="text-xl font-bold leading-tight text-foreground">{summary.model || t("fru.unknownSystem")}</h2>
                    <p className="text-sm text-muted-foreground">{summary.vendor}</p>
                    <div className="mt-4 flex flex-wrap gap-x-8 gap-y-3 text-xs">
                      {summary.serviceTag && (
                        // Stacked label-over-value: the muted field name is secondary,
                        // the mono value is the foreground lead (value-first, D-06).
                        <div className="flex flex-col gap-0.5">
                          <span className="uppercase tracking-wide text-[10px] font-medium text-muted-foreground">{t("fru.serviceTag")}</span>
                          <div className="flex items-center gap-1.5">
                            <span className="font-mono text-sm font-semibold text-foreground">{summary.serviceTag}</span>
                            <button
                              onClick={() => copyToClipboard(summary.serviceTag!)}
                              aria-label={t("fru.copyField", { field: t("fru.serviceTag") })}
                              title={t("fru.copyField", { field: t("fru.serviceTag") })}
                              className="inline-flex min-h-11 min-w-11 items-center justify-center rounded hover:bg-muted"
                            >
                              <Copy className="h-3 w-3 text-muted-foreground" aria-hidden="true" />
                            </button>
                          </div>
                        </div>
                      )}
                      {summary.assetTag && (
                        <div className="flex flex-col gap-0.5">
                          <span className="uppercase tracking-wide text-[10px] font-medium text-muted-foreground">{t("fru.assetTag")}</span>
                          <span className="font-mono text-sm font-semibold text-foreground">{summary.assetTag}</span>
                        </div>
                      )}
                      <div className="flex flex-col gap-0.5">
                        <span className="flex items-center gap-1 uppercase tracking-wide text-[10px] font-medium text-muted-foreground">
                          <Cpu className="h-3 w-3" />
                          {t("fru.cpusDetected")}
                        </span>
                        {/* Inferred from live sensor readings — when offline that count
                            would be the LAST seen, so we render an em dash instead. */}
                        <span className="text-sm font-semibold text-foreground">{online && cpuCount > 0 ? cpuCount : "—"}</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Honest capability note — IPMI/FRU does not expose CPU model or RAM. */}
            <div className="flex items-start gap-2 rounded-lg border border-border bg-muted/30 p-3 text-xs text-muted-foreground">
              <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <p>
                {t("fru.capabilityNote")}
              </p>
            </div>

            {/* All FRU devices, with cleaned/friendly section names. Each card earns
                hierarchy via the inherited blueprint layers (D-06): the card surface lifts
                off the canvas (shadow-sm + hover), a surface-2 header band carries a LEGIBLE
                (non-muted) device title as the scan anchor, and field VALUES lead each row. */}
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              {Object.entries(sections).map(([section, fields]) => (
                <div key={section} className="overflow-hidden rounded-lg border border-border bg-card shadow-sm transition-shadow hover:shadow-md">
                  <div className="border-b border-border bg-muted px-4 py-2.5">
                    <h3 className="text-xs font-semibold uppercase tracking-wider text-foreground">{cleanSection(section, t)}</h3>
                  </div>
                  <div className="divide-y divide-border">
                    {fields.map((f, i) => (
                      <div key={i} className="flex items-center justify-between gap-4 px-4 py-2">
                        <span className="text-[11px] text-muted-foreground truncate">{f.field}</span>
                        <div className="flex items-center gap-1">
                          <span className="font-mono text-xs font-semibold text-foreground truncate max-w-[180px]">{f.value}</span>
                          {(f.field.toLowerCase().includes("serial") || f.field.toLowerCase().includes("part")) && (
                            <button
                              onClick={() => copyToClipboard(f.value)}
                              aria-label={t("fru.copyField", { field: f.field })}
                              title={t("fru.copyField", { field: f.field })}
                              className="inline-flex min-h-11 min-w-11 items-center justify-center rounded hover:bg-muted"
                            >
                              <Copy className="h-3 w-3 text-muted-foreground" aria-hidden="true" />
                            </button>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>

            {data?.fetched_at && (
              <p className="text-xs text-muted-foreground">
                {/* Label keyed in Plan 02; the date VALUE now formats in the active locale (D-16). */}
                {t("fru.lastUpdated", { value: new Date(data.fetched_at).toLocaleString(intlLocale(i18n.resolvedLanguage)) })}
              </p>
            )}
          </div>
        )}
      </div>
    </>
  );
}
