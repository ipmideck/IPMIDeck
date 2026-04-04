import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useServerStore } from "@/stores/server-store";
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
      // Skip when an input, textarea, or contenteditable is focused
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      if ((e.target as HTMLElement)?.isContentEditable) return;

      // Skip if any modifier key is held (except shift for letters)
      if (e.ctrlKey || e.metaKey || e.altKey) return;

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
