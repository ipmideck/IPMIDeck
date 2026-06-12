import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { LogOut, Menu, MoreVertical } from "lucide-react";
import { useServerStore } from "@/stores/server-store";
import { useAuthStore } from "@/stores/auth-store";
import { useConnectionStore, type WSStatus } from "@/stores/connection-store";
import { post } from "@/api/client";
import { cn } from "@/lib/utils";
import { MobileNavDrawer } from "./MobileNavDrawer";

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
      {/* Text label drops below sm: — the colored dot stays as the at-a-glance indicator. */}
      <span className="hidden sm:inline">
        {status === "connected" ? t("header.live") : status === "connecting" ? t("header.connecting") : t("header.offline")}
      </span>
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

  // Wave 7 mobile chrome: hamburger opens the MobileNavDrawer below md:; the page
  // action buttons (passed via children) collapse into a kebab dropdown below sm:.
  const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false);
  const [kebabOpen, setKebabOpen] = useState(false);
  const kebabRef = useRef<HTMLDivElement>(null);

  // Close the kebab dropdown on outside click.
  useEffect(() => {
    if (!kebabOpen) return;
    function handleClick(e: MouseEvent) {
      if (kebabRef.current && !kebabRef.current.contains(e.target as Node)) {
        setKebabOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [kebabOpen]);

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
    <header className="flex h-[52px] items-center justify-between border-b border-border bg-card px-4 sm:px-6 shrink-0">
      <div className="flex min-w-0 items-center gap-2 text-[13px]">
        {/* Hamburger — mobile only (below md:). Opens the MobileNavDrawer. */}
        <button
          onClick={() => setMobileDrawerOpen(true)}
          aria-label={t("nav.openMenu")}
          aria-expanded={mobileDrawerOpen}
          aria-controls="mobile-nav-drawer"
          className="md:hidden -ml-1 inline-flex min-h-11 min-w-11 items-center justify-center rounded-md hover:bg-muted"
        >
          <Menu className="h-5 w-5" aria-hidden="true" />
        </button>
        {contextServer && (
          <>
            <span className="hidden truncate text-muted-foreground sm:inline">{contextServer.name}</span>
            <span className="hidden text-muted-foreground sm:inline">/</span>
          </>
        )}
        <span className="truncate font-medium">{title}</span>
        <ConnectionBadge status={status} />
      </div>

      {/* Mobile drawer mount (rendered once; portal lives outside the header flow). */}
      <MobileNavDrawer open={mobileDrawerOpen} onClose={() => setMobileDrawerOpen(false)} />

      <div className="flex items-center gap-2">
        {/* Page action buttons (children): inline above sm:, collapsed into the kebab below sm:. */}
        {children && <div className="hidden items-center gap-2 sm:flex">{children}</div>}

        {/* Kebab overflow — below sm: only, when there are page actions to show. */}
        {children && (
          <div className="relative sm:hidden" ref={kebabRef}>
            <button
              onClick={() => setKebabOpen((v) => !v)}
              aria-label={t("nav.moreActions")}
              aria-expanded={kebabOpen}
              className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md hover:bg-muted"
            >
              <MoreVertical className="h-5 w-5" aria-hidden="true" />
            </button>
            {kebabOpen && (
              <div
                onClick={() => setKebabOpen(false)}
                className="absolute right-0 z-50 mt-1 flex w-56 flex-col gap-2 rounded-md border border-border bg-popover p-3 text-popover-foreground shadow-lg"
              >
                {children}
              </div>
            )}
          </div>
        )}

        {authEnabled && authenticated && (
          <button
            onClick={handleLogout}
            aria-label={t("header.logoutAria")}
            className="inline-flex min-h-11 min-w-11 items-center justify-center gap-1 rounded-md border border-border px-2.5 text-xs font-medium hover:bg-muted sm:min-h-9 sm:min-w-0 sm:py-1"
          >
            <LogOut className="h-3.5 w-3.5" />
            {/* Label drops below sm: — icon-only logout stays one tap away (CONTEXT priority). */}
            <span className="hidden sm:inline">{t("header.logout")}</span>
          </button>
        )}
      </div>
    </header>
  );
}
