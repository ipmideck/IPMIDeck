import { useTranslation } from "react-i18next";
import { Server as ServerIcon, Shield, Bell, Zap, Palette, HardDrive, Info } from "lucide-react";
import { cn } from "@/lib/utils";
import type { SectionDef, SettingsSectionId } from "./types";

/** Rail definitions — order is the rail order; servers leads (default landing). */
export const SECTIONS: SectionDef[] = [
  { id: "servers", icon: ServerIcon, labelKey: "settings.sections.servers" },
  { id: "security", icon: Shield, labelKey: "settings.sections.security" },
  { id: "notifications", icon: Bell, labelKey: "settings.sections.notifications" },
  { id: "energy", icon: Zap, labelKey: "settings.sections.energy" },
  { id: "appearance", icon: Palette, labelKey: "settings.sections.appearance" },
  { id: "system", icon: HardDrive, labelKey: "settings.sections.system" },
  { id: "about", icon: Info, labelKey: "settings.sections.about" },
];

interface SectionRailProps {
  active: SettingsSectionId | null;
  onSelect: (id: SettingsSectionId) => void;
  /** Mobile renders the rail as a full-width master list; desktop as a subordinate column. */
  variant: "desktop" | "mobile";
}

/**
 * The section rail. On desktop it is a SUBORDINATE list (no card/border box —
 * the brief's "two rails" risk: the app Sidebar already sits to its left, so
 * this rail must read as a lightweight in-page nav, not a second chrome panel).
 * Active row uses a tinted pill + aria-current; everything else is quiet.
 *
 * On mobile it is the master view of the master-detail (full-width tappable rows,
 * 44px targets, chevron affordance via larger tap rows).
 */
export function SectionRail({ active, onSelect, variant }: SectionRailProps) {
  const { t } = useTranslation();

  if (variant === "mobile") {
    return (
      <nav aria-label={t("nav.settings")} className="flex flex-col">
        {SECTIONS.map(({ id, icon: Icon, labelKey }) => (
          <button
            key={id}
            type="button"
            onClick={() => onSelect(id)}
            className="flex items-center gap-3 border-b border-border/60 px-1 py-3.5 text-left text-sm font-medium text-foreground min-h-[--control-min] hover:bg-muted/50"
          >
            <Icon className="h-5 w-5 shrink-0 text-muted-foreground" aria-hidden="true" />
            <span className="flex-1">{t(labelKey)}</span>
            <span aria-hidden="true" className="text-muted-foreground">›</span>
          </button>
        ))}
      </nav>
    );
  }

  return (
    <nav aria-label={t("nav.settings")} className="flex flex-col gap-0.5">
      {SECTIONS.map(({ id, icon: Icon, labelKey }) => {
        const isActive = active === id;
        return (
          <button
            key={id}
            type="button"
            onClick={() => onSelect(id)}
            aria-current={isActive ? "page" : undefined}
            className={cn(
              "flex items-center gap-2.5 rounded-md px-3 py-2 text-left text-sm transition-colors min-h-9",
              isActive
                ? "bg-primary/10 font-medium text-foreground"
                : "text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            <Icon className={cn("h-4 w-4 shrink-0", isActive ? "text-primary" : "text-muted-foreground")} aria-hidden="true" />
            <span className="truncate">{t(labelKey)}</span>
          </button>
        );
      })}
    </nav>
  );
}
