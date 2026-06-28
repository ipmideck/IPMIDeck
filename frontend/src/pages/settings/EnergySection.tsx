import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Zap } from "lucide-react";
import { toast } from "sonner";
import { useServerStore } from "@/stores/server-store";
import { useCurrencyStore } from "@/stores/currency-store";
import { useEnergyResetStore } from "@/stores/energy-reset-store";
import { SUPPORTED_CURRENCIES, currencyOptionLabel, type CurrencyCode } from "@/lib/currency";
import { cn } from "@/lib/utils";
import { useSettings } from "./SettingsContext";
import { SectionPanel, FieldGroup, inputClass, secondaryBtnClass } from "./primitives";

interface EnergySectionProps {
  headingRef: React.Ref<HTMLHeadingElement>;
}

/**
 * Energy section — currency (MOVED from Appearance per brief §5) + per-server
 * energy-counter reset / reset-all. Both resets use the destructive inline
 * 2-step confirm pattern (preserved verbatim). Server IDs are STRINGS.
 *
 * The energy-reset store is hydrated at the App shell (App.tsx) so it stays fed
 * even when the user never lands on this section.
 */
export function EnergySection({ headingRef }: EnergySectionProps) {
  const { t, i18n } = useTranslation();
  const { online, offlineTip } = useSettings();
  const { servers } = useServerStore();
  const currency = useCurrencyStore((s) => s.currency);
  const setCurrency = useCurrencyStore((s) => s.setCurrency);

  const [resetConfirmId, setResetConfirmId] = useState<string | null>(null);
  const [resetAllConfirm, setResetAllConfirm] = useState(false);
  const resets = useEnergyResetStore((s) => s.resets);
  const resetServer = useEnergyResetStore((s) => s.resetServer);
  const resetAll = useEnergyResetStore((s) => s.resetAll);
  const energyLocale = i18n.resolvedLanguage || "en";

  return (
    <SectionPanel
      ref={headingRef}
      headingId="settings-panel-heading"
      title={t("settings.energy.title")}
      description={t("settings.sections.energyDescription")}
    >
      {/* Currency — moved from Appearance. */}
      <FieldGroup title={t("settings.currency.label")} description={t("settings.sections.energyCurrencyHint")}>
        <div className="flex items-center justify-between gap-3">
          <label htmlFor="currency-select" className="text-sm font-medium text-foreground">{t("settings.currency.label")}</label>
          <select
            id="currency-select"
            value={currency}
            onChange={(e) => setCurrency(e.target.value as CurrencyCode)}
            className={cn(inputClass, "max-w-[12rem]")}
          >
            {SUPPORTED_CURRENCIES.map((c) => (
              <option key={c} value={c}>{currencyOptionLabel(c)}</option>
            ))}
          </select>
        </div>
      </FieldGroup>

      {/* Energy counters — per-server + reset-all (destructive confirms). */}
      <FieldGroup
        title={t("settings.energy.title")}
        action={
          <div className="flex items-center gap-2">
            <Zap className="h-4 w-4 text-cyan" aria-hidden="true" />
            <button
              type="button"
              onClick={() => setResetAllConfirm(true)}
              disabled={servers.length === 0 || !online}
              title={offlineTip}
              className="rounded-md border border-border px-2.5 py-2 text-xs font-medium text-danger hover:bg-danger/10 min-h-[--control-min] md:min-h-9 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {t("settings.energy.resetAll")}
            </button>
          </div>
        }
      >
        {resetAllConfirm && (
          <div className="mb-4 space-y-3 rounded-md border border-danger/30 bg-danger/5 p-3">
            <p className="text-xs text-muted-foreground">{t("settings.energy.confirmResetAllBody", { count: servers.length })}</p>
            <div className="flex gap-2">
              <button type="button" onClick={() => setResetAllConfirm(false)} className={cn(secondaryBtnClass, "flex-1")}>{t("settings.cancel")}</button>
              <button
                type="button"
                onClick={async () => {
                  try { await resetAll(); setResetAllConfirm(false); toast.success(t("settings.energy.resetSuccess")); }
                  catch { toast.error(t("settings.energy.resetFailed")); }
                }}
                className="flex-1 rounded-md bg-danger px-3 py-2 text-sm font-semibold text-white hover:bg-danger/90 min-h-[--control-min] md:min-h-9"
              >
                {t("settings.energy.confirmResetAll")}
              </button>
            </div>
          </div>
        )}

        {servers.length === 0 ? (
          <p className="text-xs text-muted-foreground">{t("settings.noServersDescription")}</p>
        ) : (
          <div className="space-y-2">
            {servers.map((server) => (
              <div key={server.id} className="flex flex-col items-stretch justify-between gap-3 rounded-md border border-border p-3 md:flex-row md:items-center">
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium text-foreground">{server.name}</div>
                  <div className="text-xs text-muted-foreground">
                    {resets[server.id]
                      ? t("settings.energy.lastReset", { value: new Date(resets[server.id]!).toLocaleString(energyLocale) })
                      : t("settings.energy.neverReset")}
                  </div>
                </div>
                {resetConfirmId === server.id ? (
                  <div className="w-full space-y-3 rounded-md border border-danger/30 bg-danger/5 p-3 md:w-auto">
                    <p className="text-xs text-muted-foreground">{t("settings.energy.confirmResetBody", { name: server.name })}</p>
                    <div className="flex gap-2">
                      <button type="button" onClick={() => setResetConfirmId(null)} className={cn(secondaryBtnClass, "flex-1")}>{t("settings.cancel")}</button>
                      <button
                        type="button"
                        onClick={async () => {
                          try { await resetServer(server.id); setResetConfirmId(null); toast.success(t("settings.energy.resetSuccess")); }
                          catch { toast.error(t("settings.energy.resetFailed")); }
                        }}
                        className="flex-1 rounded-md bg-danger px-3 py-2 text-sm font-semibold text-white hover:bg-danger/90 min-h-[--control-min] md:min-h-9"
                      >
                        {t("settings.energy.confirmReset")}
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => setResetConfirmId(server.id)}
                    disabled={!online}
                    title={offlineTip}
                    className="w-full rounded-md border border-border px-2.5 py-2 text-xs font-medium text-danger hover:bg-danger/10 min-h-[--control-min] md:min-h-9 md:w-auto disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {t("settings.energy.resetServer", { name: server.name })}
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </FieldGroup>
    </SectionPanel>
  );
}
