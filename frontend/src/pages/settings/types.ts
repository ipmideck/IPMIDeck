import type { LucideIcon } from "lucide-react";

/**
 * The 7 settings sections (D-13 brief §5). Order is the rail order; `servers`
 * is the default landing section (co-locates the tariff deep-link).
 */
export type SettingsSectionId =
  | "servers"
  | "security"
  | "notifications"
  | "energy"
  | "appearance"
  | "system"
  | "about";

export const SECTION_IDS: SettingsSectionId[] = [
  "servers",
  "security",
  "notifications",
  "energy",
  "appearance",
  "system",
  "about",
];

/** Rail entry descriptor — icon + i18n label key (settings.sections.<id>). */
export interface SectionDef {
  id: SettingsSectionId;
  icon: LucideIcon;
  /** i18n key under settings.sections.* */
  labelKey: string;
}
