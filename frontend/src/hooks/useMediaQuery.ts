import { useEffect, useState } from "react";

/**
 * Reactive CSS media-query hook (Wave 7 mobile redesign).
 *
 * Used by the Toaster position swap (App.tsx), the WidgetCatalog mobile-vs-desktop
 * sheet, the widget grid resize/long-press gates, and the chart tap-tooltip swap.
 * Reads the initial value synchronously so the first render already matches the
 * viewport (no flash), then subscribes to MediaQueryList change events.
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() =>
    typeof window !== "undefined" ? window.matchMedia(query).matches : false,
  );
  useEffect(() => {
    const m = window.matchMedia(query);
    const handler = (e: MediaQueryListEvent) => setMatches(e.matches);
    m.addEventListener("change", handler);
    // Re-sync in case the query/viewport changed between the initial render and effect.
    setMatches(m.matches);
    return () => m.removeEventListener("change", handler);
  }, [query]);
  return matches;
}
