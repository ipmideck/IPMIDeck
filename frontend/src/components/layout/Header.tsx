import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { LogOut } from "lucide-react";
import { useServerStore } from "@/stores/server-store";
import { useAuthStore } from "@/stores/auth-store";
import { useConnectionStore, type WSStatus } from "@/stores/connection-store";
import { post } from "@/api/client";
import { cn } from "@/lib/utils";

interface HeaderProps {
  title: string;
  children?: React.ReactNode;
}

function ConnectionBadge({ status }: { status: WSStatus }) {
  const { t } = useTranslation();
  return (
    <div
      className={cn(
        "flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium",
        status === "connected" && "bg-emerald-500/10 text-emerald-500",
        status === "connecting" && "bg-yellow-500/10 text-yellow-500",
        status === "disconnected" && "bg-red-500/10 text-red-500"
      )}
    >
      <div
        className={cn(
          "h-1.5 w-1.5 rounded-full",
          status === "connected" && "bg-emerald-500",
          status === "connecting" && "bg-yellow-500",
          status === "disconnected" && "bg-red-500"
        )}
      />
      {status === "connected" ? t("header.live") : status === "connecting" ? t("header.connecting") : t("header.offline")}
    </div>
  );
}

export function Header({ title, children }: HeaderProps) {
  const { t } = useTranslation();
  // Read from the global connection store. The WebSocket itself is hoisted to
  // PageLayout so we don't open a new socket every time the user navigates.
  const status = useConnectionStore((s) => s.wsStatus);
  const contextServer = useServerStore((s) =>
    s.servers.find((srv) => srv.id === s.contextServerId)
  );

  // Logout (D-11): rendered inside Header so it appears on EVERY page. Gated on
  // authEnabled && authenticated — hidden in open-access mode (nothing to log out of).
  const navigate = useNavigate();
  const authEnabled = useAuthStore((s) => s.authEnabled);
  const authenticated = useAuthStore((s) => s.authenticated);

  async function handleLogout() {
    // Best-effort: clearing client state + redirecting is correct even if the POST fails
    // (cookie expires server-side regardless; a 401 here is handled by the interceptor, REVIEWS #6).
    try { await post("/api/auth/logout"); } catch { /* best-effort */ }
    useAuthStore.setState({ authenticated: false });
    navigate("/login", { replace: true });
  }

  return (
    <header className="flex h-[52px] items-center justify-between border-b border-border bg-card px-6 shrink-0">
      <div className="flex items-center gap-2 text-[13px]">
        {contextServer && (
          <>
            <span className="text-muted-foreground">{contextServer.name}</span>
            <span className="text-muted-foreground">/</span>
          </>
        )}
        <span className="font-medium">{title}</span>
        <ConnectionBadge status={status} />
      </div>
      <div className="flex items-center gap-2">
        {children}
        {authEnabled && authenticated && (
          <button
            onClick={handleLogout}
            aria-label={t("header.logoutAria")}
            className="inline-flex items-center gap-1 rounded-md border border-border px-2.5 py-1 text-xs font-medium hover:bg-muted"
          >
            <LogOut className="h-3.5 w-3.5" />
            {t("header.logout")}
          </button>
        )}
      </div>
    </header>
  );
}
