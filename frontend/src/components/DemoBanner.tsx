import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { get } from "@/api/client";
import { X } from "lucide-react";

export function DemoBanner() {
  const { t } = useTranslation();
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
    <div className="flex items-center justify-center gap-2 bg-warning px-4 py-1.5 text-xs font-medium text-background">
      <span>{t("banner.demoText")}</span>
      <button
        onClick={() => setVisible(false)}
        className="ml-1 rounded p-0.5 hover:bg-background/20 transition-colors"
        aria-label={t("banner.dismiss")}
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
