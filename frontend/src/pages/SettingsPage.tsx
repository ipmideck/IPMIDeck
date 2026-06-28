import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { Header } from "@/components/layout/Header";
import { get } from "@/api/client";
import { useBackendOnline } from "@/stores/connection-store";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { cn } from "@/lib/utils";
import { ChevronLeft } from "lucide-react";

import { SettingsContext, type SettingsCtx } from "@/pages/settings/SettingsContext";
import { SectionRail, SECTIONS } from "@/pages/settings/SectionRail";
import { SECTION_IDS, type SettingsSectionId } from "@/pages/settings/types";
import { ServersSection } from "@/pages/settings/ServersSection";
import { SecuritySection } from "@/pages/settings/SecuritySection";
import { NotificationsSection } from "@/pages/settings/NotificationsSection";
import { EnergySection } from "@/pages/settings/EnergySection";
import { AppearanceSection } from "@/pages/settings/AppearanceSection";
import { SystemSection } from "@/pages/settings/SystemSection";
import { AboutSection } from "@/pages/settings/AboutSection";

const DEFAULT_SECTION: SettingsSectionId = "servers";

/** Parse the active section id from the pathname; null when bare /settings. */
function parseSection(pathname: string): SettingsSectionId | null {
  const m = pathname.match(/^\/settings\/([^/]+)\/?$/);
  if (!m) return null;
  const id = m[1] as SettingsSectionId;
  return SECTION_IDS.includes(id) ? id : null;
}

/**
 * Two-pane Settings shell (D-13 / brief verbatim). Left section rail + right
 * URL-routed panel, 7 sections, default landing Servers. On mobile (<768px) it
 * is a URL-driven master-detail: bare /settings is the section list; tapping a
 * row navigates to /settings/<section>; in-panel back returns to the list via
 * history. The shell owns the cross-section state (Context) so panels stay
 * navigation-safe (certPath/keyPath survive leaving System and coming back).
 *
 * Blocker #1 deep-link: the shell matches `^#server-(.+)-cost$` ABOVE the
 * section switch and navigates to /settings/servers preserving the hash, so the
 * Servers panel is guaranteed mounted; ServersSection then opens the edit form
 * and focuses the cost input. Regex + input id + undefined/new guards preserved.
 */
export default function SettingsPage() {
  const { t } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const isMobile = useMediaQuery("(max-width: 767px)");

  const online = useBackendOnline();
  const offlineTip = online ? undefined : t("header.backendDisconnected");

  // --- Lifted cross-section state (medium caveat) ---
  // certPath/keyPath are populated only by the in-session gen-cert action; held
  // here so they survive navigating away from System and back.
  const [certPath, setCertPath] = useState("");
  const [keyPath, setKeyPath] = useState("");

  // Live backend version for the About section (zero-drift, /api/health).
  const [appVersion, setAppVersion] = useState<string | null>(null);
  useEffect(() => {
    get<{ version: string }>("/api/health")
      .then((h) => setAppVersion(h.version))
      .catch(() => { /* leave null -> render the — placeholder */ });
  }, []);

  const ctx: SettingsCtx = {
    online,
    offlineTip,
    certPath,
    setCertPath,
    keyPath,
    setKeyPath,
    appVersion,
  };

  // --- Blocker #1: shell-level deep-link hash router ---
  // On a `^#server-(.+)-cost$` match, route to the Servers panel (preserving the
  // hash) so the panel is mounted before ServersSection consumes the hash. The
  // regex + guards are preserved verbatim; ServersSection performs the actual
  // startEdit + waitForEl + focus + hash-clear.
  useEffect(() => {
    const match = location.hash.match(/^#server-(.+)-cost$/);
    if (!match) return;
    const targetId = match[1];
    if (!targetId || targetId === "undefined" || targetId === "new") return;
    if (parseSection(location.pathname) !== "servers") {
      navigate(`/settings/servers${location.search}${location.hash}`, { replace: true });
    }
  }, [location.hash, location.pathname, location.search, navigate]);

  // --- Focus-move to the panel heading on section switch (D-13 §8) ---
  const headingRef = useRef<HTMLHeadingElement>(null);
  const activeSection = parseSection(location.pathname);
  // Track the previous section so we only move focus on an actual section change
  // (not on every keystroke / re-render within a panel).
  const prevSectionRef = useRef<SettingsSectionId | null>(null);
  useLayoutEffect(() => {
    if (activeSection && activeSection !== prevSectionRef.current) {
      // Don't steal focus on the very first mount (avoids hijacking the page on
      // a fresh load / deep-link, where ServersSection wants the cost input).
      if (prevSectionRef.current !== null) {
        headingRef.current?.focus();
      }
      prevSectionRef.current = activeSection;
    }
  }, [activeSection]);

  // --- Routing decisions ---
  const bareSettings = location.pathname === "/settings" || location.pathname === "/settings/";

  // Desktop: bare /settings redirects to the default section (so the four
  // bare-`/settings` call-sites land populated). Mobile: bare /settings is the
  // master list — do NOT redirect.
  if (bareSettings && !isMobile) {
    return <Navigate replace to={`/settings/${DEFAULT_SECTION}`} />;
  }

  // An unknown /settings/<x> path -> redirect to the default section.
  if (!bareSettings && activeSection === null) {
    return <Navigate replace to={`/settings/${DEFAULT_SECTION}`} />;
  }

  const renderPanel = (section: SettingsSectionId) => {
    switch (section) {
      case "servers": return <ServersSection headingRef={headingRef} />;
      case "security": return <SecuritySection headingRef={headingRef} />;
      case "notifications": return <NotificationsSection headingRef={headingRef} />;
      case "energy": return <EnergySection headingRef={headingRef} />;
      case "appearance": return <AppearanceSection headingRef={headingRef} />;
      case "system": return <SystemSection headingRef={headingRef} />;
      case "about": return <AboutSection headingRef={headingRef} />;
    }
  };

  const goToSection = (id: SettingsSectionId) => navigate(`/settings/${id}`);

  // --- Mobile master-detail (URL-driven) ---
  if (isMobile) {
    // Master: the section list.
    if (bareSettings) {
      return (
        <SettingsContext.Provider value={ctx}>
          <Header title={t("nav.settings")} />
          <div className="flex-1 overflow-auto p-4">
            <div className="mx-auto max-w-xl">
              <SectionRail active={null} onSelect={goToSection} variant="mobile" />
            </div>
          </div>
        </SettingsContext.Provider>
      );
    }
    // Detail: the panel + an in-panel back to the list (history-driven).
    const activeLabel = SECTIONS.find((s) => s.id === activeSection)?.labelKey;
    return (
      <SettingsContext.Provider value={ctx}>
        <Header title={activeLabel ? t(activeLabel) : t("nav.settings")} />
        <div className="flex-1 overflow-auto p-4">
          <div className="mx-auto max-w-xl">
            <button
              type="button"
              onClick={() => navigate("/settings")}
              className="mb-4 inline-flex items-center gap-1 rounded-md px-2 py-2 text-sm font-medium text-muted-foreground hover:bg-muted min-h-[--control-min]"
            >
              <ChevronLeft className="h-4 w-4" aria-hidden="true" />
              {t("settings.sections.backToList")}
            </button>
            {activeSection && renderPanel(activeSection)}
          </div>
        </div>
      </SettingsContext.Provider>
    );
  }

  // --- Desktop two-pane (rail + panel) ---
  return (
    <SettingsContext.Provider value={ctx}>
      <Header title={t("nav.settings")} />
      <div className="flex-1 overflow-auto">
        <div className="mx-auto flex w-full max-w-5xl gap-8 px-6 py-8">
          {/* Subordinate section rail (~220px) — sticky, no card/border box. */}
          <aside className="sticky top-8 hidden w-[200px] shrink-0 self-start md:block lg:w-[220px]">
            <SectionRail active={activeSection} onSelect={goToSection} variant="desktop" />
          </aside>
          {/* Content panel. */}
          <div className="min-w-0 flex-1">
            {activeSection && renderPanel(activeSection)}
          </div>
        </div>
      </div>
    </SettingsContext.Provider>
  );
}
