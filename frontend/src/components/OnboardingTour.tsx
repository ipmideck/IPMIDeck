import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Joyride, STATUS, type EventData, type Step } from "react-joyride";
import { useTourStore } from "@/stores/tour-store";
import { useUIOverlayStore } from "@/stores/ui-overlay-store";

/**
 * First-login guided tour (UX-02). Mounted INSIDE the authenticated app shell
 * (AuthGate/PageLayout) so it only ever renders on real app routes — never on
 * /setup or /login. Auto-runs once when the user lands on the Dashboard ("/")
 * and has not seen it, is skippable, marks itself seen on finish/skip, and sets
 * the shared overlay flag (03-04) so keyboard shortcuts are suppressed while it
 * runs.
 *
 * react-joyride 3.1.0 API: `Joyride` is a NAMED export, the callback prop is
 * `onEvent` (payload `EventData` carries `status`), the Skip button is enabled by
 * including "skip" in `options.buttons`, and the overlay z-index lives in
 * `options.zIndex`.
 */
export function OnboardingTour() {
  const { t } = useTranslation();
  const location = useLocation();
  const run = useTourStore((s) => s.run);
  const seen = useTourStore((s) => s.seen);
  const markSeen = useTourStore((s) => s.markSeen);
  const start = useTourStore((s) => s.start);
  const setTourOpen = useUIOverlayStore((s) => s.setTourOpen);

  // Steps 1-4 anchor to data-tour attributes that ALL live on the Dashboard
  // route (Sidebar + Dashboard header). Steps 5 (language) and 6 (Cmd+K) are
  // target-less centered steps: language-select lives only in Settings (lazy,
  // unmounted on first-login Dashboard) and cmdk has no always-visible trigger.
  const steps: Step[] = [
    {
      target: '[data-tour="sidebar-nav"]',
      title: t("tour.navTitle"),
      content: t("tour.navBody"),
    },
    {
      target: '[data-tour="server-switcher"]',
      title: t("tour.serverTitle"),
      content: t("tour.serverBody"),
    },
    {
      target: '[data-tour="add-widget"]',
      title: t("tour.widgetTitle"),
      content: t("tour.widgetBody"),
    },
    {
      target: '[data-tour="nav-fanpilot"]',
      title: t("tour.fanpilotTitle"),
      content: t("tour.fanpilotBody"),
    },
    {
      target: "body",
      placement: "center",
      title: t("tour.languageTitle"),
      content: t("tour.languageBody"),
    },
    {
      target: "body",
      placement: "center",
      title: t("tour.commandTitle"),
      content: t("tour.commandBody"),
    },
  ];

  // Auto-run gate (REVIEWS HIGH #5): only on the Dashboard route AND when unseen.
  // Not on bare mount, and never on non-"/" paths (so the targeted steps always
  // have anchors when the tour fires on first login).
  useEffect(() => {
    if (!seen && location.pathname === "/") {
      start();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seen, location.pathname]);

  function handleEvent(data: EventData) {
    const { status } = data;
    if (status === STATUS.RUNNING) {
      // Suppress nav/server keyboard shortcuts while the tour is on screen.
      setTourOpen(true);
    } else if (status === STATUS.FINISHED || status === STATUS.SKIPPED) {
      markSeen();
      setTourOpen(false);
    }
  }

  return (
    <Joyride
      steps={steps}
      run={run}
      continuous
      onEvent={handleEvent}
      locale={{
        skip: t("tour.skip"),
        next: t("tour.next"),
        back: t("tour.back"),
        last: t("tour.last"),
        close: t("tour.close"),
      }}
      options={{ zIndex: 10000, buttons: ["back", "skip", "primary"] }}
    />
  );
}
