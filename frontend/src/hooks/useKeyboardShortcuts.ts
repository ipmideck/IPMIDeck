import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useServerStore } from "@/stores/server-store";
import { useUIOverlayStore } from "@/stores/ui-overlay-store";
import { put } from "@/api/client";

const pageShortcuts: Record<string, string> = {
  d: "/",
  f: "/fanpilot",
  e: "/sel",
  h: "/fru",
  m: "/modules",
};

export function useKeyboardShortcuts() {
  const navigate = useNavigate();
  const { servers, setContextServer } = useServerStore();

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      // Skip when an input, textarea, or contenteditable is focused.
      // (This also covers the cmdk command palette's text <input>.)
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      if ((e.target as HTMLElement)?.isContentEditable) return;

      // Skip if any modifier key is held (except shift for letters — "?" = Shift+/ passes).
      if (e.ctrlKey || e.metaKey || e.altKey) return;

      // "?" opens the shortcuts help modal. Always allowed so it stays re-triggerable.
      // Placed AFTER the input guard so typing "?" in a text field does nothing.
      if (e.key === "?") {
        e.preventDefault();
        useUIOverlayStore.getState().setHelpOpen(true);
        return;
      }

      // Overlay guard (D-07 / REVIEWS MED #9): suppress page + server shortcuts while
      // ANY overlay is open — help, tour, OR the Cmd+K command palette. commandOpen is
      // mirrored from CommandPalette into the store (no DOM querying), so the palette's
      // local useState is visible to this listener here.
      if (useUIOverlayStore.getState().anyOverlayOpen()) return;

      const key = e.key.toLowerCase();

      // Page navigation shortcuts
      if (pageShortcuts[key]) {
        e.preventDefault();
        navigate(pageShortcuts[key]);
        return;
      }

      // Number keys 1-9: switch to server by index
      const num = parseInt(e.key, 10);
      if (num >= 1 && num <= 9) {
        const server = servers[num - 1];
        if (server) {
          e.preventDefault();
          setContextServer(server.id);
          put("/api/dashboard/context", { server_id: server.id }).catch(() => {});
        }
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [navigate, servers, setContextServer]);
}
