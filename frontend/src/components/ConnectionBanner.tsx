import { useConnectionStore } from "@/stores/connection-store";
import { useTranslation } from "react-i18next";
import { WifiOff, RotateCw } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Page-level banner shown above main content whenever the WebSocket is not
 * fully connected. Two flavours:
 *   - "connecting" → yellow, animated, "Reconnecting…"
 *   - "disconnected" → red, "Backend disconnected"
 * When connected the component renders nothing so the layout collapses back.
 *
 * The banner exists so users can immediately tell that any sensor / fan / power
 * reading still on screen is the LAST known value, not a fresh one — the widgets
 * also dim their content when offline, but the banner is the explicit message.
 */
export function ConnectionBanner() {
  const { t } = useTranslation();
  const wsStatus = useConnectionStore((s) => s.wsStatus);
  if (wsStatus === "connected") return null;

  const reconnecting = wsStatus === "connecting";

  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        "flex flex-wrap items-center gap-2 border-b px-4 py-2 text-xs",
        reconnecting
          ? "border-yellow-500/30 bg-yellow-500/10"
          : "border-red-500/40 bg-red-500/10"
      )}
    >
      {reconnecting ? (
        <RotateCw className="h-3.5 w-3.5 shrink-0 animate-spin text-yellow-500" />
      ) : (
        <WifiOff className="h-3.5 w-3.5 shrink-0 text-red-500" />
      )}
      <span
        className={cn(
          "font-semibold",
          reconnecting ? "text-yellow-500" : "text-red-500"
        )}
      >
        {reconnecting ? t("banner.reconnecting") : t("banner.disconnected")}
      </span>
      <span className="text-muted-foreground">
        {reconnecting
          ? t("banner.reconnectingDetail")
          : t("banner.disconnectedDetail")}
      </span>
    </div>
  );
}
