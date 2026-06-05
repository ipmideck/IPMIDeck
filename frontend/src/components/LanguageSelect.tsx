/** Shared native-name language dropdown, reused by Setup + Settings. */

import { useTranslation } from "react-i18next";
import { LANGUAGES } from "@/i18n/languages";
import { useLanguageStore } from "@/stores/language-store";

interface LanguageSelectProps {
  className?: string;
}

export function LanguageSelect({ className }: LanguageSelectProps) {
  const { t, i18n } = useTranslation();
  const setLanguage = useLanguageStore((s) => s.setLanguage);
  const active = i18n.resolvedLanguage;

  return (
    <select
      value={active}
      onChange={(e) => setLanguage(e.target.value)}
      aria-label={t("language.label")}
      className={className}
    >
      {LANGUAGES.map((l) => (
        <option key={l.code} value={l.code}>
          {l.native}
        </option>
      ))}
    </select>
  );
}
