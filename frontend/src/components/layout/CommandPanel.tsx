import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { useCommandStore, type CommandEntry } from "@/stores/command-store";
import { useServerStore } from "@/stores/server-store";
import { get } from "@/api/client";
import { cn } from "@/lib/utils";
import i18n from "@/i18n";
import { intlLocale } from "@/i18n/languages";
import { Terminal, X } from "lucide-react";

function formatTime(ts: string) {
  try {
    const d = new Date(ts);
    // Module-level helper: read the active language from the i18n singleton so log
    // timestamps format in the user's locale (D-16) without threading a prop through EntryRow.
    return d.toLocaleTimeString(intlLocale(i18n.resolvedLanguage), { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return ts;
  }
}

function CommandIcon({ type }: { type: string }) {
  const { t } = useTranslation();
  const colors: Record<string, string> = {
    power: "text-yellow-500",
    fan_mode: "text-blue-500",
    fan_speed: "text-blue-400",
    sensor_poll: "text-emerald-500",
    sel_clear: "text-red-400",
    sel_fetch: "text-muted-foreground",
    fru_fetch: "text-muted-foreground",
  };
  // Known command types map to a translated label; unknown types fall back to the
  // raw code with underscores replaced (defaultValue keeps i18next from echoing the key).
  const label = t(`command.type.${type}`, { defaultValue: type.replace("_", " ") });
  return (
    <div className={cn("font-mono text-[10px] font-bold uppercase", colors[type] || "text-muted-foreground")}>
      {label}
    </div>
  );
}

function EntryRow({ entry }: { entry: CommandEntry }) {
  const isError = !!entry.error_message;
  return (
    <div className={cn(
      "border-b border-border/30 px-3 py-2 text-[11px] hover:bg-muted/50 transition-colors",
      isError && "bg-red-500/5"
    )}>
      <div className="flex items-center justify-between gap-2">
        <CommandIcon type={entry.command_type} />
        <span className="text-[10px] text-muted-foreground tabular-nums">{formatTime(entry.timestamp)}</span>
      </div>
      <div className="mt-0.5 font-mono text-muted-foreground truncate">
        {entry.command_detail}
      </div>
      {entry.result && !isError && (
        <div className="mt-0.5 font-mono text-emerald-500/80 truncate">
          {entry.result}
        </div>
      )}
      {isError && (
        <div className="mt-0.5 font-mono text-red-400 truncate">
          {entry.error_message}
        </div>
      )}
    </div>
  );
}

export function CommandPanel() {
  const { t } = useTranslation();
  const { entries, isOpen, toggle, setEntries } = useCommandStore();
  const contextServerId = useServerStore((s) => s.contextServerId);
  const scrollRef = useRef<HTMLDivElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval>>();

  // Poll command log
  useEffect(() => {
    if (!isOpen) return;

    async function fetchLogs() {
      try {
        const url = contextServerId
          ? `/api/logs?limit=100&server_id=${contextServerId}`
          : "/api/logs?limit=100";
        const data = await get<{ logs: CommandEntry[] }>(url);
        setEntries(data.logs);
      } catch {
        // ignore
      }
    }

    fetchLogs();
    pollRef.current = setInterval(fetchLogs, 3000);
    return () => clearInterval(pollRef.current);
  }, [isOpen, contextServerId, setEntries]);

  return (
    <>
      {/* Toggle button — always visible on the right edge */}
      <button
        onClick={toggle}
        className={cn(
          "fixed right-0 top-1/2 -translate-y-1/2 z-40 flex items-center gap-1 rounded-l-md border border-r-0 border-border bg-card px-1.5 py-3 text-muted-foreground hover:text-foreground hover:bg-muted transition-colors",
          isOpen && "right-[320px]"
        )}
        title={t("command.logTitle")}
      >
        <Terminal className="h-3.5 w-3.5" />
      </button>

      {/* Panel */}
      <div
        className={cn(
          "fixed right-0 top-0 h-screen w-[320px] bg-card border-l border-border z-30 flex flex-col transition-transform duration-200",
          isOpen ? "translate-x-0" : "translate-x-full"
        )}
      >
        {/* Header */}
        <div className="flex h-[52px] items-center justify-between border-b border-border px-3 shrink-0">
          <div className="flex items-center gap-2">
            <Terminal className="h-4 w-4 text-muted-foreground" />
            <span className="text-[13px] font-medium">{t("command.logTitle")}</span>
            <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground tabular-nums">
              {entries.length}
            </span>
          </div>
          <button onClick={toggle} className="rounded p-1 hover:bg-muted">
            <X className="h-3.5 w-3.5 text-muted-foreground" />
          </button>
        </div>

        {/* Entries */}
        <div ref={scrollRef} className="flex-1 overflow-y-auto">
          {entries.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <Terminal className="h-8 w-8 text-muted-foreground/30 mb-2" />
              <p className="text-xs text-muted-foreground">{t("command.empty")}</p>
              <p className="text-[10px] text-muted-foreground/60 mt-1">
                {t("command.emptyHint")}
              </p>
            </div>
          ) : (
            entries.map((entry, i) => <EntryRow key={entry.id ?? i} entry={entry} />)
          )}
        </div>
      </div>
    </>
  );
}
