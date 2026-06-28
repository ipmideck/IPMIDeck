import { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { get, post } from "@/api/client";
import { useAuthStore } from "@/stores/auth-store";
import { bootstrapAppData } from "@/lib/bootstrap";
import { AlertCircle, LogIn, Loader2, ServerCog } from "lucide-react";

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

  // Shared field styling: lift inputs onto the surface, hit --control-min (D-05), and
  // let the repo-wide :focus-visible ring land (no focus:outline-none override).
  const fieldClass =
    "w-full rounded-lg border border-input bg-background px-3 py-2.5 text-sm text-foreground " +
    "placeholder:text-muted-foreground min-h-[var(--control-min)] transition-colors " +
    "hover:border-muted-foreground/40";

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-background px-6 py-12 text-foreground">
      <div className="w-full max-w-sm">
        {/* Brand presence (D-06): navy brand mark + wordmark tie the login to the app
         * shell ("IPMIDeck" in the Sidebar) and the marketing site. No new color. */}
        <div className="flex flex-col items-center text-center">
          <div className="mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-primary text-primary-foreground shadow-sm">
            <ServerCog className="h-7 w-7" aria-hidden="true" />
          </div>
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
            IPMIDeck
          </p>
          <h1 className="mt-1 text-2xl font-bold tracking-tight text-foreground">
            {t("login.title")}
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">{t("login.subtitle")}</p>
        </div>

        {/* The form lives on a lifted card surface so it reads as the focused task
         * (earned hierarchy, D-06) rather than floating on the canvas. */}
        <form
          onSubmit={handleSubmit}
          className="mt-7 w-full space-y-4 rounded-xl border border-border bg-card p-6 shadow-sm"
        >
          <div className="space-y-1.5">
            <label htmlFor="login-username" className="text-xs font-medium text-foreground">
              {t("login.usernamePlaceholder")}
            </label>
            <input
              id="login-username"
              type="text"
              placeholder={t("login.usernamePlaceholder")}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              autoFocus
              className={fieldClass}
            />
          </div>

          <div className="space-y-1.5">
            <label htmlFor="login-password" className="text-xs font-medium text-foreground">
              {t("login.passwordPlaceholder")}
            </label>
            <input
              id="login-password"
              type="password"
              placeholder={t("login.passwordPlaceholder")}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              className={fieldClass}
            />
          </div>

          {/* Error: triple-encoded (D-04) — semantic --color-danger token + AlertCircle
           * icon companion + text, announced via role="alert" for screen readers.
           * Message text is the backend-supplied generic copy (no enumeration). */}
          {error && (
            <p
              role="alert"
              className="flex items-start gap-2 rounded-lg border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger"
            >
              <AlertCircle className="mt-px h-4 w-4 shrink-0" aria-hidden="true" />
              <span>{error}</span>
            </p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground min-h-[var(--control-min)] hover:bg-primary/90 transition-colors disabled:opacity-50"
          >
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <LogIn className="h-4 w-4" aria-hidden="true" />
            )}
            {t("login.signIn")}
          </button>
        </form>
      </div>
    </div>
  );
}
