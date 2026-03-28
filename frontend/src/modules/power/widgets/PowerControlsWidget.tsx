import { useEffect, useState } from "react";
import { get, post } from "@/api/client";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

interface PowerControlsWidgetProps {
  serverId: string;
}

const ACTIONS = [
  { id: "on", label: "Power On", danger: false },
  { id: "soft", label: "Soft Off", danger: true },
  { id: "off", label: "Hard Off", danger: true },
  { id: "reset", label: "Reset", danger: true },
  { id: "cycle", label: "Cycle", danger: true },
] as const;

export function PowerControlsWidget({ serverId }: PowerControlsWidgetProps) {
  const [status, setStatus] = useState("unknown");
  const [loading, setLoading] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null);

  useEffect(() => {
    if (!serverId) return;
    const poll = async () => {
      try {
        const data = await get<{ status: string }>(`/api/modules/power/${serverId}/status`);
        setStatus(data.status);
      } catch { /* ignore */ }
    };
    poll();
    const interval = setInterval(poll, 10000);
    return () => clearInterval(interval);
  }, [serverId]);

  const handleAction = async (action: string) => {
    // Dangerous actions need confirmation
    if (action !== "on" && confirm !== action) {
      setConfirm(action);
      setTimeout(() => setConfirm(null), 3000); // auto-dismiss after 3s
      return;
    }
    setConfirm(null);
    setLoading(action);
    try {
      const res = await post<{ success: boolean; error?: string }>(`/api/modules/power/${serverId}/command`, { action });
      if (res.success) {
        toast.success(`Power ${action} executed`);
        // Update status
        setStatus(action === "on" || action === "reset" || action === "cycle" ? "on" : "off");
      } else {
        toast.error(res.error || "Command failed");
      }
    } catch (e: any) {
      toast.error(e.message || "Connection error");
    } finally {
      setLoading(null);
    }
  };

  const isOn = status === "on";

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2.5 mb-3">
        <div className={`h-2.5 w-2.5 rounded-full ${isOn ? "bg-emerald-500" : "bg-red-500"}`} />
        <span className={cn("font-mono text-sm font-semibold", isOn ? "text-emerald-500" : "text-red-500")}>
          {isOn ? "Online" : "Offline"}
        </span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {ACTIONS.map((a) => (
          <button
            key={a.id}
            onClick={() => handleAction(a.id)}
            disabled={loading !== null}
            className={cn(
              "rounded-md border px-2.5 py-1.5 text-[11px] font-medium transition-colors",
              confirm === a.id
                ? "border-red-500 bg-red-500/20 text-red-400"
                : a.danger
                  ? "border-border text-muted-foreground hover:border-red-500/50 hover:text-red-400"
                  : "border-emerald-500/30 bg-emerald-500/10 text-emerald-500 hover:bg-emerald-500/20",
              loading === a.id && "opacity-50"
            )}
          >
            {confirm === a.id ? `Confirm ${a.label}?` : a.label}
          </button>
        ))}
      </div>
    </div>
  );
}
