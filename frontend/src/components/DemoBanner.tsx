import { useState, useEffect } from "react";
import { get } from "@/api/client";
import { X } from "lucide-react";

export function DemoBanner() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    async function checkDemo() {
      try {
        const data = await get<{ demo?: boolean }>("/api/health");
        if (data.demo) {
          setVisible(true);
        }
      } catch {
        // ignore — backend not reachable
      }
    }
    checkDemo();
  }, []);

  if (!visible) return null;

  return (
    <div className="flex items-center justify-center gap-2 bg-amber-500/90 px-4 py-1.5 text-xs font-medium text-amber-950">
      <span>Running in demo mode — no real hardware connected</span>
      <button
        onClick={() => setVisible(false)}
        className="ml-1 rounded p-0.5 hover:bg-amber-600/30 transition-colors"
        aria-label="Dismiss"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
