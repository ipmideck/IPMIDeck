import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { post, get } from "@/api/client";
import { useServerStore } from "@/stores/server-store";
import { useAuthStore } from "@/stores/auth-store";
import { LanguageSelect } from "@/components/LanguageSelect";
import { cn } from "@/lib/utils";
import {
  ServerCog,
  User,
  Server,
  CheckCircle2,
  ChevronRight,
  ChevronLeft,
  Loader2,
  ShieldCheck,
  Globe,
  Lock,
  AlertCircle,
} from "lucide-react";

// Shared field styling: lift inputs onto the card surface, hit --control-min
// (D-05), and let the repo-wide :focus-visible ring land (no focus:outline-none
// override — that suppresses the global ring the rest of the re-skinned app uses).
const fieldClass =
  "w-full rounded-lg border border-border bg-card text-sm text-foreground " +
  "placeholder:text-muted-foreground min-h-[var(--control-min)] transition-colors " +
  "hover:border-muted-foreground/40";

// Step + vendor metadata: only stable keys/codes live at module load. The displayed
// labels are resolved via t() INSIDE the component so they re-render on language change.
const STEP_KEYS = ["welcome", "authSetup", "addServer", "done"] as const;

const VENDORS = [
  { value: "supermicro", labelKey: "setup.vendors.supermicro" },
  { value: "dell", labelKey: "setup.vendors.dell" },
  { value: "hp", labelKey: "setup.vendors.hp" },
  { value: "generic", labelKey: "setup.vendors.generic" },
];

export default function SetupPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  // STEPS resolved in render so step labels update on language change.
  const STEPS = STEP_KEYS.map((k) => t(`setup.steps.${k}`));
  const setServers = useServerStore((s) => s.setServers);
  const setContextServer = useServerStore((s) => s.setContextServer);
  const [step, setStep] = useState(0);

  // Auth state
  const [requireLogin, setRequireLogin] = useState(true); // default "Yes" (require login) — secure-by-default per REVIEWS LOW; operator may switch to "No" (open access)
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  // Confirm-password protects against typos — without it the operator could lock
  // themselves out of a fresh install with a misspelled password they don't know.
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [authError, setAuthError] = useState("");
  const [authLoading, setAuthLoading] = useState(false);

  // Server state
  const [serverName, setServerName] = useState("");
  const [serverHost, setServerHost] = useState("");
  const [serverPort, setServerPort] = useState("623");
  const [serverUser, setServerUser] = useState("ADMIN");
  const [serverPass, setServerPass] = useState("");
  const [serverVendor, setServerVendor] = useState("supermicro");
  const [serverError, setServerError] = useState("");
  const [serverLoading, setServerLoading] = useState(false);
  const [testResult, setTestResult] = useState<"success" | "fail" | null>(null);
  const [testLoading, setTestLoading] = useState(false);

  // SAFETY-CRITICAL: the "No" branch MUST call POST /api/auth/toggle {enabled:false},
  // otherwise the app locks out — auth_enabled defaults to "true", so a frontend-only
  // skip would leave auth on with no user = permanent lockout. Do NOT reintroduce a
  // frontend-only skip. The radio defaults to "Yes" for secure-by-default (REVIEWS LOW).
  async function handleAuthStep() {
    setAuthLoading(true);
    setAuthError("");
    try {
      if (requireLogin) {
        // D-03: create user (issues a session cookie) -> continue authenticated.
        if (!username.trim() || !password.trim()) {
          setAuthError(t("setup.auth.credentialsRequired"));
          setAuthLoading(false);
          return;
        }
        if (password !== passwordConfirm) {
          setAuthError(t("setup.auth.passwordsDoNotMatch"));
          setAuthLoading(false);
          return;
        }
        await post("/api/auth/setup", { username, password });
        useAuthStore.setState({
          authEnabled: true,
          authenticated: true,
          hasUser: true,
          username,
        });
      } else {
        // D-02: actually DISABLE auth on the backend (default is "true" -> skipping
        // without this = permanent lockout). At first-run this no-session toggle-OFF
        // succeeds ONLY because Plan 02.1-01 patched the backend /toggle handler to use
        // the shared _require_session_if_active helper (no session required when no user
        // exists / auth off).
        await post("/api/auth/toggle", { enabled: false });
        useAuthStore.setState({
          authEnabled: false,
          authenticated: true, // open access: treat as authenticated for routing
          hasUser: false,
          username: null,
        });
      }
      setStep(2);
    } catch (e: any) {
      setAuthError(e.message || t("setup.auth.applyFailed"));
    } finally {
      setAuthLoading(false);
    }
  }

  async function handleAddServer() {
    if (!serverName.trim() || !serverHost.trim()) {
      setServerError(t("setup.server.nameHostRequired"));
      return;
    }
    setServerLoading(true);
    setServerError("");
    try {
      await post("/api/servers", {
        name: serverName,
        host: serverHost,
        port: parseInt(serverPort, 10),
        username: serverUser,
        password: serverPass,
        vendor: serverVendor,
      });
      // Reload servers
      const data = await get<{ servers: any[] }>("/api/servers");
      setServers(data.servers);
      if (data.servers[0]?.id) {
        setContextServer(data.servers[0].id);
      }
      setStep(3);
    } catch (e: any) {
      setServerError(e.message || t("setup.server.addFailed"));
    } finally {
      setServerLoading(false);
    }
  }

  async function handleTestConnection() {
    if (!serverHost.trim()) {
      setServerError(t("setup.server.hostFirst"));
      return;
    }
    setTestLoading(true);
    setTestResult(null);
    setServerError("");
    try {
      // Create a temporary test by posting to test endpoint
      const result = await post<{ success: boolean }>("/api/servers/test", {
        host: serverHost,
        port: parseInt(serverPort, 10),
        username: serverUser,
        password: serverPass,
      });
      setTestResult(result.success ? "success" : "fail");
    } catch {
      setTestResult("fail");
    } finally {
      setTestLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      {/* Stepper — relative wrapper so the language box can sit top-right on every step (D-09/D-10) */}
      <div className="relative">
        {/* Onboarding language box: detected default (i18next), correctable, switches the wizard immediately (D-09/D-10/D-12) */}
        <div className="absolute right-6 top-10 z-10">
          <LanguageSelect className="rounded-md border border-border bg-card px-2 py-1 text-xs text-foreground" />
        </div>
        <div className="mx-auto flex w-full max-w-2xl items-center justify-center gap-2 px-6 pt-10 pb-6">
          {STEPS.map((label, i) => (
          <div key={i} className="flex items-center gap-2">
            <div
              className={cn(
                "flex h-8 w-8 items-center justify-center rounded-full text-xs font-semibold transition-colors",
                // Completed steps use the blueprint success token (not raw emerald)
                // and carry a check GLYPH as the non-color companion (D-04): a
                // colorblind operator reads "done" from the \u2713, not the fill alone.
                i < step && "bg-success text-white",
                i === step && "bg-primary text-primary-foreground",
                i > step && "bg-muted text-muted-foreground"
              )}
              aria-current={i === step ? "step" : undefined}
            >
              {i < step ? "\u2713" : i + 1}
            </div>
            <span
              className={cn(
                "hidden text-xs font-medium sm:inline",
                i === step ? "text-foreground" : "text-muted-foreground"
              )}
            >
              {label}
            </span>
            {i < STEPS.length - 1 && (
              <div className="mx-1 h-px w-8 bg-border sm:w-12" />
            )}
          </div>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="mx-auto flex w-full max-w-lg flex-1 flex-col items-center justify-center px-6 pb-20">
        {/* Step 0: Welcome */}
        {step === 0 && (
          <div className="flex flex-col items-center text-center">
            {/* Brand presence (D-06): the same navy mark + IPMIDeck wordmark the
             * Login screen uses, so the first-run wizard reads as the same product
             * (and the marketing site) on sight. No new color — navy --primary. */}
            <div className="mb-5 flex h-16 w-16 items-center justify-center rounded-2xl bg-primary text-primary-foreground shadow-sm">
              <ServerCog className="h-8 w-8" aria-hidden="true" />
            </div>
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
              IPMIDeck
            </p>
            <h1 className="mt-1 text-2xl font-bold tracking-tight">{t("setup.welcomeTitle")}</h1>
            <p className="mt-3 max-w-sm text-sm leading-relaxed text-muted-foreground">
              {t("setup.welcomeBody")}
            </p>
            <button
              onClick={() => setStep(1)}
              className="mt-8 inline-flex items-center justify-center gap-2 rounded-lg bg-primary px-6 py-2.5 text-sm font-medium text-primary-foreground min-h-[var(--control-min)] hover:bg-primary/90 transition-colors"
            >
              {t("setup.getStarted")}
              <ChevronRight className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>
        )}

        {/* Step 1: Auth Setup */}
        {step === 1 && (
          <div className="flex w-full flex-col items-center text-center">
            <div className="mb-6 flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-primary/20 to-primary/5 ring-1 ring-primary/20">
              <ShieldCheck className="h-8 w-8 text-primary" />
            </div>
            <h1 className="text-2xl font-bold tracking-tight">{t("setup.auth.title")}</h1>
            <p className="mt-2 max-w-sm text-sm leading-relaxed text-muted-foreground">
              {t("setup.auth.subtitle")}
            </p>

            <div className="mt-7 w-full max-w-md space-y-3 text-left">
              {/* Option: require login */}
              <button
                type="button"
                onClick={() => setRequireLogin(true)}
                aria-pressed={requireLogin}
                className={cn(
                  "group flex w-full items-center gap-4 rounded-xl border p-4 text-left transition-all duration-150",
                  requireLogin
                    ? "border-primary bg-primary/5 shadow-sm ring-2 ring-primary/35"
                    : "border-border hover:border-primary/40 hover:bg-muted/40"
                )}
              >
                <span
                  className={cn(
                    "flex h-10 w-10 shrink-0 items-center justify-center rounded-lg transition-colors",
                    requireLogin
                      ? "bg-primary/15 text-primary"
                      : "bg-muted text-muted-foreground group-hover:text-foreground"
                  )}
                >
                  <ShieldCheck className="h-5 w-5" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-semibold text-foreground">
                    {t("setup.auth.yesTitle")}
                  </span>
                  <span className="mt-0.5 block text-xs leading-relaxed text-muted-foreground">
                    {t("setup.auth.yesDescription")}
                  </span>
                </span>
                <span
                  className={cn(
                    "flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2 transition-colors",
                    requireLogin ? "border-primary" : "border-muted-foreground/40"
                  )}
                >
                  {requireLogin && (
                    <span className="h-2.5 w-2.5 rounded-full bg-primary" />
                  )}
                </span>
              </button>

              {/* Option: open access */}
              <button
                type="button"
                onClick={() => setRequireLogin(false)}
                aria-pressed={!requireLogin}
                className={cn(
                  "group flex w-full items-center gap-4 rounded-xl border p-4 text-left transition-all duration-150",
                  !requireLogin
                    ? "border-primary bg-primary/5 shadow-sm ring-2 ring-primary/35"
                    : "border-border hover:border-primary/40 hover:bg-muted/40"
                )}
              >
                <span
                  className={cn(
                    "flex h-10 w-10 shrink-0 items-center justify-center rounded-lg transition-colors",
                    !requireLogin
                      ? "bg-primary/15 text-primary"
                      : "bg-muted text-muted-foreground group-hover:text-foreground"
                  )}
                >
                  <Globe className="h-5 w-5" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-semibold text-foreground">
                    {t("setup.auth.noTitle")}
                  </span>
                  <span className="mt-0.5 block text-xs leading-relaxed text-muted-foreground">
                    {t("setup.auth.noDescription")}
                  </span>
                </span>
                <span
                  className={cn(
                    "flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2 transition-colors",
                    !requireLogin ? "border-primary" : "border-muted-foreground/40"
                  )}
                >
                  {!requireLogin && (
                    <span className="h-2.5 w-2.5 rounded-full bg-primary" />
                  )}
                </span>
              </button>

              {/* Credentials — revealed only when "Yes" is selected */}
              {requireLogin && (
                <div className="space-y-3 rounded-xl border border-border/60 bg-muted/30 p-4">
                  <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    {t("setup.auth.yourCredentials")}
                  </p>
                  <div className="relative">
                    <User className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                    <input
                      type="text"
                      placeholder={t("setup.auth.usernamePlaceholder")}
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      autoComplete="username"
                      className={cn(fieldClass, "py-2 pl-9 pr-3")}
                    />
                  </div>
                  <div className="relative">
                    <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                    <input
                      type="password"
                      placeholder={t("setup.auth.passwordPlaceholder")}
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      autoComplete="new-password"
                      className={cn(fieldClass, "py-2 pl-9 pr-3")}
                    />
                  </div>
                  <div className="relative">
                    <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                    <input
                      type="password"
                      placeholder={t("setup.auth.confirmPasswordPlaceholder")}
                      value={passwordConfirm}
                      onChange={(e) => setPasswordConfirm(e.target.value)}
                      autoComplete="new-password"
                      aria-invalid={
                        !!(password && passwordConfirm && password !== passwordConfirm)
                      }
                      className={cn(
                        fieldClass,
                        "py-2 pl-9 pr-3",
                        // Mismatch uses the blueprint danger token (not raw red).
                        password && passwordConfirm && password !== passwordConfirm &&
                          "border-danger/60"
                      )}
                    />
                  </div>
                  {/* Inline mismatch hint — triple-encoded (D-04): danger token +
                   * AlertCircle companion + text, announced via role="alert". */}
                  {password && passwordConfirm && password !== passwordConfirm && (
                    <p role="alert" className="flex items-center gap-1.5 text-xs text-danger">
                      <AlertCircle className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                      {t("setup.auth.passwordsDoNotMatch")}
                    </p>
                  )}
                </div>
              )}

              {/* Error: triple-encoded (D-04) — danger token + AlertCircle companion
               * + text, on a tinted callout, announced via role="alert". */}
              {authError && (
                <p
                  role="alert"
                  className="flex items-start gap-2 rounded-lg border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger"
                >
                  <AlertCircle className="mt-px h-4 w-4 shrink-0" aria-hidden="true" />
                  <span>{authError}</span>
                </p>
              )}
            </div>

            <div className="mt-7 flex w-full max-w-md items-center gap-3">
              <button
                onClick={() => setStep(0)}
                className="inline-flex items-center gap-1 rounded-lg border border-border px-4 py-2.5 text-sm font-medium text-muted-foreground min-h-[var(--control-min)] transition-colors hover:bg-muted/50 hover:text-foreground"
              >
                <ChevronLeft className="h-4 w-4" aria-hidden="true" />
                {t("common.back")}
              </button>
              <button
                onClick={handleAuthStep}
                disabled={authLoading}
                className="inline-flex flex-1 items-center justify-center gap-2 rounded-lg bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground min-h-[var(--control-min)] shadow-sm transition-colors hover:bg-primary/90 disabled:opacity-50"
              >
                {authLoading && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
                {t("common.continue")}
                <ChevronRight className="h-4 w-4" aria-hidden="true" />
              </button>
            </div>
          </div>
        )}

        {/* Step 2: Add Server */}
        {step === 2 && (
          <div className="flex w-full flex-col items-center text-center">
            <div className="mb-6 flex h-16 w-16 items-center justify-center rounded-2xl bg-primary/10">
              <Server className="h-8 w-8 text-primary" />
            </div>
            <h1 className="text-xl font-bold">{t("setup.server.title")}</h1>
            <p className="mt-2 max-w-sm text-sm text-muted-foreground">
              {t("setup.server.subtitle")}
            </p>

            <div className="mt-6 w-full max-w-xs space-y-3 text-left">
              <div>
                <label className="mb-1 block text-xs font-medium text-muted-foreground">
                  {t("setup.server.name")}
                </label>
                <input
                  type="text"
                  placeholder={t("setup.server.namePlaceholder")}
                  value={serverName}
                  onChange={(e) => setServerName(e.target.value)}
                  className={cn(fieldClass, "px-3 py-2")}
                />
              </div>
              <div className="flex gap-2">
                <div className="flex-1">
                  <label className="mb-1 block text-xs font-medium text-muted-foreground">
                    {t("setup.server.host")}
                  </label>
                  <input
                    type="text"
                    placeholder={t("setup.server.hostPlaceholder")}
                    value={serverHost}
                    onChange={(e) => setServerHost(e.target.value)}
                    className={cn(fieldClass, "px-3 py-2")}
                  />
                </div>
                <div className="w-20">
                  <label className="mb-1 block text-xs font-medium text-muted-foreground">
                    {t("setup.server.port")}
                  </label>
                  <input
                    type="number"
                    value={serverPort}
                    onChange={(e) => setServerPort(e.target.value)}
                    className={cn(fieldClass, "px-3 py-2")}
                  />
                </div>
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-muted-foreground">
                  {t("setup.server.username")}
                </label>
                <input
                  type="text"
                  value={serverUser}
                  onChange={(e) => setServerUser(e.target.value)}
                  className={cn(fieldClass, "px-3 py-2")}
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-muted-foreground">
                  {t("setup.server.password")}
                </label>
                <input
                  type="password"
                  value={serverPass}
                  onChange={(e) => setServerPass(e.target.value)}
                  autoComplete="off"
                  className={cn(fieldClass, "px-3 py-2")}
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-muted-foreground">
                  {t("setup.server.vendor")}
                </label>
                <select
                  value={serverVendor}
                  onChange={(e) => setServerVendor(e.target.value)}
                  className={cn(fieldClass, "px-3 py-2")}
                >
                  {VENDORS.map((v) => (
                    <option key={v.value} value={v.value}>
                      {t(v.labelKey)}
                    </option>
                  ))}
                </select>
              </div>

              {/* All three states triple-encoded (D-04): semantic token + lucide
               * icon companion + text, announced via role="alert"/"status". */}
              {serverError && (
                <p role="alert" className="flex items-start gap-2 text-xs text-danger">
                  <AlertCircle className="mt-px h-4 w-4 shrink-0" aria-hidden="true" />
                  <span>{serverError}</span>
                </p>
              )}

              {testResult === "success" && (
                <p role="status" className="flex items-start gap-2 text-xs text-success">
                  <CheckCircle2 className="mt-px h-4 w-4 shrink-0" aria-hidden="true" />
                  <span>{t("setup.server.testSuccess")}</span>
                </p>
              )}
              {testResult === "fail" && (
                <p role="alert" className="flex items-start gap-2 text-xs text-danger">
                  <AlertCircle className="mt-px h-4 w-4 shrink-0" aria-hidden="true" />
                  <span>{t("setup.server.testFail")}</span>
                </p>
              )}
            </div>

            <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
              <button
                onClick={() => setStep(1)}
                className="inline-flex items-center gap-1 rounded-lg border border-border px-4 py-2 text-sm font-medium text-muted-foreground min-h-[var(--control-min)] hover:text-foreground transition-colors"
              >
                <ChevronLeft className="h-4 w-4" aria-hidden="true" />
                {t("common.back")}
              </button>
              <button
                onClick={handleTestConnection}
                disabled={testLoading}
                className="inline-flex items-center gap-2 rounded-lg border border-border px-4 py-2 text-sm font-medium text-muted-foreground min-h-[var(--control-min)] hover:text-foreground transition-colors disabled:opacity-50"
              >
                {testLoading && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
                {t("common.testConnection")}
              </button>
              <button
                onClick={handleAddServer}
                disabled={serverLoading}
                className="inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-2 text-sm font-medium text-primary-foreground min-h-[var(--control-min)] hover:bg-primary/90 transition-colors disabled:opacity-50"
              >
                {serverLoading && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
                {t("setup.server.addServer")}
                <ChevronRight className="h-4 w-4" aria-hidden="true" />
              </button>
            </div>
          </div>
        )}

        {/* Step 3: Done */}
        {step === 3 && (
          <div className="flex flex-col items-center text-center">
            {/* Success uses the blueprint success token; the CheckCircle2 glyph is
             * the non-color companion (D-04) so "complete" reads without color. */}
            <div className="mb-6 flex h-20 w-20 items-center justify-center rounded-2xl bg-success/10">
              <CheckCircle2 className="h-10 w-10 text-success" aria-hidden="true" />
            </div>
            <h1 className="text-2xl font-bold">{t("setup.done.title")}</h1>
            <p className="mt-3 max-w-sm text-sm leading-relaxed text-muted-foreground">
              {t("setup.done.body")}
            </p>
            <button
              onClick={() => navigate("/")}
              className="mt-8 inline-flex items-center justify-center gap-2 rounded-lg bg-primary px-6 py-2.5 text-sm font-medium text-primary-foreground min-h-[var(--control-min)] hover:bg-primary/90 transition-colors"
            >
              {t("setup.done.goToDashboard")}
              <ChevronRight className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
