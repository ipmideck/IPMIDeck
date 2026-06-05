/** Shared native-name language dropdown with local SVG flags, reused by Setup + Settings. */

import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown } from "lucide-react";
import {
  GB, DE, FR, ES, IT, PT, NL, RU, PL, CN, JP, KR,
} from "country-flag-icons/react/3x2";
import { LANGUAGES } from "@/i18n/languages";
import { useLanguageStore } from "@/stores/language-store";
import { cn } from "@/lib/utils";

// Static map: 2-letter ISO country code -> local SVG flag component (bundled, no CDN).
const FLAG_BY_COUNTRY: Record<string, React.ComponentType<{ className?: string; title?: string }>> = {
  GB, DE, FR, ES, IT, PT, NL, RU, PL, CN, JP, KR,
};

interface LanguageSelectProps {
  className?: string;
}

export function LanguageSelect({ className }: LanguageSelectProps) {
  const { t, i18n } = useTranslation();
  const setLanguage = useLanguageStore((s) => s.setLanguage);
  const active = i18n.resolvedLanguage;

  const [open, setOpen] = useState(false);
  // activeIndex tracks keyboard focus within the listbox while open.
  const [activeIndex, setActiveIndex] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const listId = useId();

  const activeEntry = LANGUAGES.find((l) => l.code === active) ?? LANGUAGES[0];
  const ActiveFlag = FLAG_BY_COUNTRY[activeEntry.country];

  // Close on outside-click.
  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: PointerEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  function openList() {
    const idx = LANGUAGES.findIndex((l) => l.code === active);
    setActiveIndex(idx >= 0 ? idx : 0);
    setOpen(true);
  }

  function choose(code: string) {
    setLanguage(code);
    setOpen(false);
  }

  function onButtonKeyDown(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown" || e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      openList();
    }
  }

  function onListKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") {
      e.preventDefault();
      setOpen(false);
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => (i + 1) % LANGUAGES.length);
      return;
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => (i - 1 + LANGUAGES.length) % LANGUAGES.length);
      return;
    }
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      choose(LANGUAGES[activeIndex].code);
      return;
    }
  }

  return (
    <div ref={rootRef} className="relative inline-block">
      <button
        type="button"
        aria-label={t("language.label")}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => (open ? setOpen(false) : openList())}
        onKeyDown={onButtonKeyDown}
        className={cn("inline-flex items-center gap-2", className)}
      >
        {ActiveFlag && <ActiveFlag className="h-3.5 w-5 shrink-0 rounded-[2px]" />}
        <span className="truncate">{activeEntry.native}</span>
        <ChevronDown className="h-3.5 w-3.5 shrink-0 opacity-60" aria-hidden="true" />
      </button>

      {open && (
        <ul
          role="listbox"
          id={listId}
          aria-label={t("language.label")}
          aria-activedescendant={`${listId}-${LANGUAGES[activeIndex].code}`}
          tabIndex={-1}
          onKeyDown={onListKeyDown}
          ref={(el) => el?.focus()}
          className="absolute right-0 z-50 mt-1 max-h-72 w-44 overflow-auto rounded-md border border-border bg-card py-1 text-sm shadow-lg focus:outline-none"
        >
          {LANGUAGES.map((l, i) => {
            const Flag = FLAG_BY_COUNTRY[l.country];
            const selected = l.code === active;
            return (
              <li
                key={l.code}
                id={`${listId}-${l.code}`}
                role="option"
                aria-selected={selected}
                onClick={() => choose(l.code)}
                onMouseEnter={() => setActiveIndex(i)}
                className={cn(
                  "flex cursor-pointer items-center gap-2 px-3 py-1.5",
                  i === activeIndex ? "bg-muted" : "hover:bg-muted/60",
                  selected && "font-medium"
                )}
              >
                {Flag && <Flag className="h-3.5 w-5 shrink-0 rounded-[2px]" />}
                <span className="truncate">{l.native}</span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
