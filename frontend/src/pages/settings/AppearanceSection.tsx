import { useTranslation } from "react-i18next";
import { Moon, Sun, Monitor } from "lucide-react";
import { useThemeStore } from "@/stores/theme-store";
import { useTourStore } from "@/stores/tour-store";
import { cn } from "@/lib/utils";
import { LanguageSelect } from "@/components/LanguageSelect";
import { SectionPanel, FieldGroup, inputClass, secondaryBtnClass } from "./primitives";

interface AppearanceSectionProps {
  headingRef: React.Ref<HTMLHeadingElement>;
}

/**
 * Appearance section — theme + language (currency MOVED to Energy per brief §5).
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
