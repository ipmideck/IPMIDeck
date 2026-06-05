import { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { get, post } from "@/api/client";
import { useAuthStore } from "@/stores/auth-store";
import { bootstrapAppData } from "@/lib/bootstrap";
import { Lock, LogIn, Loader2 } from "lucide-react";

export default function LoginPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();

  // LOW: preserve the originally-intended URL (pathname + search + hash), default "/".
  const from = (
    location.state as { from?: { pathname?: string; search?: string; hash?: string } } | null
  )?.from;
  const target = from
    ? `${from.pathname ?? "/"}${from.search ?? ""}${from.hash ?? ""}`
    : "/";

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const res = await post<{ success: boolean; username?: string; error?: string }>(
        "/api/auth/login",
        { username, password }
      );
      if (res.success) {
        // REVIEWS #5: re-run the SAME post-auth bootstrap the app boot runs, so the
        // user is never mis-routed to /setup because servers were never loaded while
        // unauthenticated (Plan 02 REVIEWS #4 deliberately skipped that fetch).
        try {
          const me = await get<{
            authenticated: boolean;
            username?: string;
            auth_enabled: boolean;
            has_user: boolean;
          }>("/api/auth/me");
          useAuthStore.getState().setAuth({
            authEnabled: me.auth_enabled,
            authenticated: me.authenticated,
            hasUser: me.has_user,
            username: me.username ?? null,
          });
        } catch {
          useAuthStore.setState({ authenticated: true, username: res.username ?? username });
        }
        // REQUIRED order: /me refresh -> bootstrapAppData (servers + dashboard context)
        // -> navigate. The server store MUST be loaded before AuthGate evaluates routing
        // so the user lands on their intended page (or Dashboard), never the setup wizard.
        await bootstrapAppData();
        // Do NOT clear `loading` here — navigation unmounts this page.
        navigate(target, { replace: true });
      } else {
        // Backend already returns generic invalid/lockout text (Phase 1 D-04) — use verbatim,
        // never rephrase or special-case so username existence is not leaked.
        setError(res.error || t("login.failed"));
        setLoading(false);
      }
    } catch {
      setError(t("login.failedRetry"));
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-background text-foreground">
      <div className="w-full max-w-sm px-6">
        <div className="flex flex-col items-center text-center">
          <div className="mb-6 flex h-16 w-16 items-center justify-center rounded-2xl bg-primary/10">
            <Lock className="h-8 w-8 text-primary" />
          </div>
          <h1 className="text-xl font-bold">{t("login.title")}</h1>
          <p className="mt-2 max-w-sm text-sm text-muted-foreground">
            {t("login.subtitle")}
          </p>
        </div>

        <form onSubmit={handleSubmit} className="mt-6 w-full space-y-3">
          <input
            type="text"
            placeholder={t("login.usernamePlaceholder")}
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            autoFocus
            className="w-full rounded-lg border border-border bg-card px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
          />
          <input
            type="password"
            placeholder={t("login.passwordPlaceholder")}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            className="w-full rounded-lg border border-border bg-card px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
          />
          {error && <p className="text-xs text-red-500">{error}</p>}
          <button
            type="submit"
            disabled={loading}
            className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-primary px-5 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50"
          >
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <LogIn className="h-4 w-4" />
            )}
            {t("login.signIn")}
          </button>
        </form>
      </div>
    </div>
  );
}
