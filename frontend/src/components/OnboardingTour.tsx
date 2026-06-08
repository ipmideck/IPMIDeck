import { useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  Joyride,
  STATUS,
  type EventData,
  type Step,
  type TooltipRenderProps,
} from "react-joyride";
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
 * `options.zIndex`. The tooltip is fully custom via `tooltipComponent` and the
 * spotlight ring/glow is styled via `styles.spotlight` (an SVG <path>, NOT CSS).
 */

/**
 * Poll the DOM until `selector` exists (or `timeout` elapses), then resolve.
 * Used by the Language step's `before` hook: after navigating to /settings the
 * SettingsPage is lazy-loaded, so `[data-tour="language-select"]` is NOT in the
 * DOM yet. Awaiting this before the step presents guarantees react-joyride finds
 * the real anchor and does not skip the step (BUG 1). Resolves (never rejects)
 * so the tour always continues even if the anchor never appears.
 */
function waitForEl(selector: string, timeout = 5000): Promise<void> {
  return new Promise((resolve) => {
    if (document.querySelector(selector)) {
      resolve();
      return;
    }
    const start = Date.now();
    const id = setInterval(() => {
      if (document.querySelector(selector) || Date.now() - start > timeout) {
        clearInterval(id);
        resolve();
      }
    }, 50);
  });
}

/**
 * Custom themed tooltip (v2 redesign). Uses the app's Tailwind tokens so it
 * inherits light/dark for free (same tokens as CommandPalette / Sidebar). Adds a
 * step counter + dot indicators and an accent primary button. Mirrors
 * DefaultTooltip's button gating: skip only when !isLastStep, back only when
 * index > 0. All button props (onClick + a11y + label `title`) come from
 * react-joyride; labels resolve from the <Joyride locale={...}> prop.
 */
function TourTooltip({
  index,
  size,
  isLastStep,
  step,
  backProps,
  skipProps,
  primaryProps,
  tooltipProps,
}: TooltipRenderProps) {
  return (
    <div
      {...tooltipProps}
      className="w-[340px] max-w-[calc(100vw-2rem)] rounded-lg border border-border bg-popover text-popover-foreground shadow-lg"
    >
      <div className="p-4">
        {step.title && <h4 className="mb-1.5 text-sm font-semibold">{step.title}</h4>}
        <div className="text-sm text-muted-foreground">{step.content}</div>
      </div>
      <div className="flex items-center justify-between gap-2 border-t border-border px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="text-xs tabular-nums text-muted-foreground">
            {index + 1} / {size}
          </span>
          <div className="flex gap-1">
            {Array.from({ length: size }).map((_, i) => (
              <span
                key={i}
                className={
                  "h-1.5 w-1.5 rounded-full " +
                  (i === index ? "bg-primary" : "bg-muted-foreground/30")
                }
              />
            ))}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {!isLastStep && (
            <button
              {...skipProps}
              className="rounded-md px-2.5 py-1.5 text-xs font-medium text-muted-foreground hover:bg-muted"
            >
              {skipProps.title}
            </button>
          )}
          {index > 0 && (
            <button
              {...backProps}
              className="rounded-md px-2.5 py-1.5 text-xs font-medium text-muted-foreground hover:bg-muted"
            >
              {backProps.title}
            </button>
          )}
          <button
            {...primaryProps}
            className="rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground hover:bg-primary/90"
          >
            {primaryProps.title}
          </button>
        </div>
      </div>
    </div>
  );
}

export function OnboardingTour() {
  const { t } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const run = useTourStore((s) => s.run);
  const seen = useTourStore((s) => s.seen);
  const markSeen = useTourStore((s) => s.markSeen);
  const start = useTourStore((s) => s.start);
  const setTourOpen = useUIOverlayStore((s) => s.setTourOpen);
  const requestCommandOpen = useUIOverlayStore((s) => s.requestCommandOpen);

  // Steps 1-4 anchor to data-tour attributes that ALL live on the Dashboard
  // route (Sidebar + Dashboard header). Step 5 (language) navigates to /settings
  // and spotlights the REAL lazy language selector (awaited via targetWaitTimeout);
  // step 6 (Cmd+K) opens the REAL cmdk palette live (centered, since the palette
  // is itself a centered modal). Both stay uncontrolled + continuous and drive
  // their work via per-step before/after hooks (RESEARCH §3/§4).
  const steps: Step[] = [
    {
      target: '[data-tour="sidebar-nav"]',
      title: t("tour.navTitle"),
      content: t("tour.navBody"),
      // Land the box at the lower-right of the nav column (not floating
      // mid-menu). Orchestrator verifies this live and may adjust the value.
      placement: "right-end",
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
      // Real language selector lives in the lazy /settings route. Navigate there
      // in `before`, then let targetWaitTimeout poll (every 100ms) for the anchor
      // to mount before the step presents (RESEARCH §3).
      target: '[data-tour="language-select"]',
      title: t("tour.languageTitle"),
      content: t("tour.languageBody"),
      placement: "left", // selector sits at the right edge of the Appearance card
      // Backstop: even if the before-hook somehow resolves early, the engine still
      // polls for the lazy target up to 5s before giving up (BUG 1 belt-and-braces).
      targetWaitTimeout: 5000,
      before: async () => {
        if (location.pathname !== "/settings") navigate("/settings");
        // The SettingsPage is lazy-loaded — block the step until the real anchor
        // actually mounts so react-joyride attaches/spotlights it instead of
        // skipping the step (BUG 1). The 100ms targetWaitTimeout default was too
        // short for the lazy chunk to load + render; awaiting the element here
        // makes the step reliable. Cap at 4500ms — just under the engine's
        // beforeTimeout (5000ms) so this hook always resolves before the engine
        // force-times-out the before phase; the targetWaitTimeout backstop (5000ms)
        // then covers an anchor that mounts a hair later.
        await waitForEl('[data-tour="language-select"]', 4500);
      },
    },
    {
      // Open the REAL cmdk palette live. The tour-driven open is NON-MODAL and
      // z-raised (CommandPalette branches on commandOpenRequest): the palette
      // content sits at z 10001 — ABOVE the joyride dim (overlay z 10000) so it's
      // visible over the backdrop — while this centered tooltip's floater (also
      // 10001, mounted AFTER the palette via this before-hook) renders on top and
      // its Next/Done/Back/Skip buttons stay clickable. Non-modal removes the
      // palette's focus trap + outside-inert that previously trapped the tour
      // (BUG 2). Keep the tooltip centered (target: body) — the palette is the
      // visual focus above the dim; do NOT spotlight it.
      target: "body",
      placement: "center",
      title: t("tour.commandTitle"),
      content: t("tour.commandBody"),
      before: async () => {
        requestCommandOpen(true);
      },
      after: () => {
        requestCommandOpen(false);
      },
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

  // Robustness (F3): clear the overlay flag whenever the tour is not running for
  // any reason (e.g. a stop path that never emits FINISHED/SKIPPED). The RUNNING
  // branch in handleEvent keeps it true while the tour is on screen.
  useEffect(() => {
    if (!run) setTourOpen(false);
  }, [run, setTourOpen]);

  function handleEvent(data: EventData) {
    const { status } = data;
    if (status === STATUS.RUNNING) {
      // Suppress nav/server keyboard shortcuts for the WHOLE running tour (F3),
      // so pressing "?" never opens the help modal on top of the tour.
      setTourOpen(true);
    } else if (status === STATUS.FINISHED || status === STATUS.SKIPPED) {
      // Real end: force-close the palette (covers a mid-command-step skip), return
      // the user to the dashboard in a clean state, then remember it and lift the
      // overlay suppression. markSeen stays gated on this terminal branch only.
      requestCommandOpen(false);
      if (location.pathname !== "/") navigate("/");
      markSeen();
      setTourOpen(false);
    } else if (status === STATUS.IDLE) {
      // Tour not running (idle/reset): clear the flag but do NOT mark seen.
      setTourOpen(false);
    }
  }

  // Theme-aware backdrop dim: a single overlayColor reads too dark in light mode
  // / too light in dark mode. The app toggles theme via the `dark` class on
  // documentElement (theme-store), so read it at render and pick a tuned alpha.
  // The accent ring/glow use var(--primary), which is theme-correct in both.
  const isDark = document.documentElement.classList.contains("dark");

  return (
    <Joyride
      steps={steps}
      run={run}
      continuous
      onEvent={handleEvent}
      tooltipComponent={TourTooltip}
      locale={{
        skip: t("tour.skip"),
        next: t("tour.next"),
        back: t("tour.back"),
        last: t("tour.last"),
        close: t("tour.close"),
      }}
      styles={{
        // The spotlight is an SVG <path>, so these are SVG attributes (stroke for
        // the ring, filter for the glow) — NOT CSS box-shadow. If var(--primary)
        // does not resolve inside the SVG paint context during live UAT, the
        // orchestrator may swap to the computed token value.
        spotlight: {
          stroke: "var(--primary)",
          strokeWidth: 2,
          rx: 8,
          ry: 8,
          filter: "drop-shadow(0 0 6px var(--primary)) drop-shadow(0 0 14px var(--primary))",
        },
      }}
      options={{
        zIndex: 10000,
        buttons: ["back", "skip", "primary"],
        skipBeacon: true,
        spotlightPadding: 6,
        spotlightRadius: 8,
        // Theme-aware backdrop dim (overlayColor lives on `options` in v3.1.0,
        // not on `styles.options`): lighter for light theme, heavier for dark.
        overlayColor: isDark ? "rgba(0,0,0,0.55)" : "rgba(0,0,0,0.35)",
      }}
    />
  );
}
