import { useTranslation } from "react-i18next";
import { ExternalLink, Heart, Code2, Globe } from "lucide-react";
import { useSettings } from "./SettingsContext";
import { SectionPanel, FieldGroup } from "./primitives";

interface AboutSectionProps {
  headingRef: React.Ref<HTMLHeadingElement>;
}

/**
 * About section — live version (/api/health), creator attribution (VERBATIM,
 * preserved from the monolith; no new/duplicated personal data), and sponsor.
 */
export function AboutSection({ headingRef }: AboutSectionProps) {
  const { t } = useTranslation();
  const { appVersion } = useSettings();

  return (
    <SectionPanel
      ref={headingRef}
      headingId="settings-panel-heading"
      title={t("settings.about.title")}
      description={t("settings.sections.aboutDescription")}
    >
      <FieldGroup title={t("settings.about.title")}>
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm text-muted-foreground">{t("settings.version")}</span>
            <span className="font-mono text-sm">{appVersion ?? "—"}</span>
          </div>
          <div className="border-t border-border/60" />
          <div className="flex items-start gap-3 pt-1">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-muted text-sm font-semibold">LT</div>
            <div>
              <p className="text-sm font-medium">Luigi Tanzillo</p>
              <p className="text-xs text-muted-foreground">{t("settings.creatorRole")}</p>
              <div className="mt-1.5 flex flex-wrap items-center gap-2">
                <a href="https://github.com/dev-luigi" target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-0.5 text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground">
                  <Code2 className="h-3 w-3" /> dev-luigi <ExternalLink className="h-2.5 w-2.5" />
                </a>
                <a href="https://luigitanzillo.it/" target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-0.5 text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground">
                  <Globe className="h-3 w-3" /> luigitanzillo.it <ExternalLink className="h-2.5 w-2.5" />
                </a>
                <a href="https://github.com/sponsors/dev-luigi" target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 rounded-md border border-pink-500/30 bg-pink-500/10 px-2 py-0.5 text-[11px] font-medium text-pink-400 transition-colors hover:bg-pink-500/20">
                  <Heart className="h-3 w-3 fill-current" /> {t("settings.sponsor")} <ExternalLink className="h-2.5 w-2.5" />
                </a>
              </div>
            </div>
          </div>
        </div>
      </FieldGroup>
    </SectionPanel>
  );
}
