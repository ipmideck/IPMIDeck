import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Moon, Sun, Monitor } from "lucide-react";
import { toast } from "sonner";
import { useThemeStore } from "@/stores/theme-store";
import { useTourStore } from "@/stores/tour-store";
import { useDateTimeFormat, useDisplayPrefsStore } from "@/stores/display-prefs-store";
import { cn } from "@/lib/utils";
import { intlLocale } from "@/i18n/languages";
import {
  DEFAULT_DISPLAY_PREFS,
  activeTimeZone,
  formatDate,
  formatTime,
  listTimeZones,
  type DisplayPrefs,
} from "@/lib/datetime";
import { LanguageSelect } from "@/components/LanguageSelect";
import { SectionPanel, FieldGroup, inputClass, secondaryBtnClass } from "./primitives";

interface AppearanceSectionProps {
  headingRef: React.Ref<HTMLHeadingElement>;
}

/**
 * Appearance section — theme, language, and date and time display (currency MOVED to Energy per brief §5).
 * The `data-tour="language-select"` anchor is preserved byte-identical here; the
 * OnboardingTour repoints its language step to /settings/appearance in 06-09.
 */
export function AppearanceSection({ headingRef }: AppearanceSectionProps) {
  const { t } = useTranslation();
  const { theme, setTheme } = useThemeStore();
  const startTour = useTourStore((s) => s.start);

  const themeOptions = [
    { value: "dark" as const, label: t("settings.themeDark"), icon: Moon },
    { value: "light" as const, label: t("settings.themeLight"), icon: Sun },
    { value: "system" as const, label: t("settings.themeSystem"), icon: Monitor },
  ];

  return (
    <SectionPanel
      ref={headingRef}
      headingId="settings-panel-heading"
      title={t("settings.appearance")}
      description={t("settings.sections.appearanceDescription")}
    >
      <FieldGroup title={t("settings.appearance")} description={t("settings.sections.appearanceThemeHint")}>
        <div role="radiogroup" aria-label={t("settings.appearance")} className="flex flex-wrap gap-2">
          {themeOptions.map((opt) => (
            <button
              key={opt.value}
              type="button"
              role="radio"
              aria-checked={theme === opt.value}
              onClick={() => setTheme(opt.value)}
              className={cn(
                "inline-flex items-center gap-2 rounded-md border px-3 py-2 text-sm font-medium transition-colors min-h-[--control-min] md:min-h-9",
                theme === opt.value ? "border-primary bg-primary/10 text-foreground" : "border-border hover:bg-muted",
              )}
            >
              <opt.icon className="h-4 w-4" aria-hidden="true" />
              {opt.label}
            </button>
          ))}
        </div>
      </FieldGroup>

      <FieldGroup title={t("settings.language")} description={t("settings.sections.appearanceLanguageHint")}>
        {/* Language switcher — data-tour anchor preserved byte-identical. */}
        <div className="flex items-center justify-between gap-3" data-tour="language-select">
          <span className="text-sm font-medium text-foreground">{t("settings.language")}</span>
          <LanguageSelect className={cn(inputClass, "max-w-[14rem]")} />
        </div>
      </FieldGroup>

      <DateTimeGroup />

      <FieldGroup title={t("tour.replay")} description={t("settings.sections.appearanceTourHint")}>
        <div className="flex items-center justify-between gap-3">
          <span className="text-sm font-medium text-foreground">{t("tour.replay")}</span>
          <button type="button" onClick={startTour} className={secondaryBtnClass}>
            {t("tour.replay")}
          </button>
        </div>
      </FieldGroup>
    </SectionPanel>
  );
}

/**
 * How every timestamp in the interface is written. Each option label shows the current time in
 * that form, so the choice can be made by looking. Saved on the server for every browser.
 */
function DateTimeGroup() {
  const { t, i18n } = useTranslation();
  const prefs = useDisplayPrefsStore((s) => s.prefs);
  const setPrefs = useDisplayPrefsStore((s) => s.setPrefs);
  const { formatDateTime, timeZone } = useDateTimeFormat();

  useEffect(() => {
    void useDisplayPrefsStore.getState().hydrate();
  }, []);

  // The preview and the option examples show the real current time.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const locale = intlLocale(i18n.resolvedLanguage);
  const browserZone = activeTimeZone(DEFAULT_DISPLAY_PREFS);
  const zones = useMemo(() => listTimeZones(prefs.timeZone), [prefs.timeZone]);

  const example = (change: Partial<DisplayPrefs>) => ({ locale, prefs: { ...prefs, ...change } });
  const minuteOnly = { seconds: false };

  function update(change: Partial<DisplayPrefs>) {
    setPrefs({ ...prefs, ...change }).catch(() => {
      toast.error(t("settings.datetime.saveFailed"));
    });
  }

  const rowClass = "flex items-center justify-between gap-3";
  const labelClass = "text-sm font-medium text-foreground";
  const selectClass = cn(inputClass, "max-w-[14rem]");

  return (
    <FieldGroup title={t("settings.datetime.title")} description={t("settings.datetime.hint")}>
      <div className="space-y-3">
        <div className={rowClass}>
          <label htmlFor="datetime-zone" className={labelClass}>{t("settings.datetime.timeZone")}</label>
          <select
            id="datetime-zone"
            value={prefs.timeZone}
            onChange={(e) => update({ timeZone: e.target.value })}
            className={selectClass}
          >
            <option value="browser">{t("settings.datetime.timeZoneBrowser", { zone: browserZone })}</option>
            {zones.map((z) => (
              <option key={z} value={z}>{z}</option>
            ))}
          </select>
        </div>

        <div className={rowClass}>
          <label htmlFor="datetime-clock" className={labelClass}>{t("settings.datetime.clock")}</label>
          <select
            id="datetime-clock"
            value={prefs.timeFormat}
            onChange={(e) => update({ timeFormat: e.target.value as DisplayPrefs["timeFormat"] })}
            className={selectClass}
          >
            <option value="auto">{t("settings.datetime.clockAuto")}</option>
            <option value="24h">
              {t("settings.datetime.clock24", { example: formatTime(now, example({ timeFormat: "24h" }), minuteOnly) })}
            </option>
            <option value="12h">
              {t("settings.datetime.clock12", { example: formatTime(now, example({ timeFormat: "12h" }), minuteOnly) })}
            </option>
          </select>
        </div>

        <div className={rowClass}>
          <label htmlFor="datetime-seconds" className={labelClass}>{t("settings.datetime.seconds")}</label>
          <select
            id="datetime-seconds"
            value={prefs.seconds}
            onChange={(e) => update({ seconds: e.target.value as DisplayPrefs["seconds"] })}
            className={selectClass}
          >
            <option value="auto">{t("settings.datetime.secondsAuto")}</option>
            <option value="show">{t("settings.datetime.secondsShow")}</option>
            <option value="hide">{t("settings.datetime.secondsHide")}</option>
          </select>
        </div>

        <div className={rowClass}>
          <label htmlFor="datetime-date" className={labelClass}>{t("settings.datetime.dateFormat")}</label>
          <select
            id="datetime-date"
            value={prefs.dateFormat}
            onChange={(e) => update({ dateFormat: e.target.value as DisplayPrefs["dateFormat"] })}
            className={selectClass}
          >
            <option value="language">
              {t("settings.datetime.dateLanguage", { example: formatDate(now, example({ dateFormat: "language" })) })}
            </option>
            <option value="iso">
              {t("settings.datetime.dateIso", { example: formatDate(now, example({ dateFormat: "iso" })) })}
            </option>
          </select>
        </div>
      </div>

      <p className="mt-4 text-xs text-muted-foreground tabular-nums">
        {t("settings.datetime.preview", { value: `${formatDateTime(now, { seconds: true })} (${timeZone})` })}
      </p>
    </FieldGroup>
  );
}
