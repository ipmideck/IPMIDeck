import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { post, get } from "@/api/client";
import { useServerStore } from "@/stores/server-store";
import { useAuthStore } from "@/stores/auth-store";
import { cn } from "@/lib/utils";
import {
  MonitorCog,
  User,
  Server,
  CheckCircle2,
  ChevronRight,
  ChevronLeft,
  Loader2,
  ShieldCheck,
  Globe,
  Lock,
} from "lucide-react";

const STEPS = ["Welcome", "Auth Setup", "Add Server", "Done"];

const VENDORS = [
  { value: "supermicro", label: "Supermicro" },
  { value: "dell", label: "Dell iDRAC" },
  { value: "hp", label: "HP iLO" },
  { value: "generic", label: "Generic IPMI" },
];

export default function SetupPage() {
  const navigate = useNavigate();
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
          setAuthError("Username and password are required.");
          setAuthLoading(false);
          return;
        }
        if (password !== passwordConfirm) {
          setAuthError("Passwords do not match.");
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
      setAuthError(e.message || "Failed to apply authentication setting.");
    } finally {
      setAuthLoading(false);
    }
  }

  async function handleAddServer() {
    if (!serverName.trim() || !serverHost.trim()) {
      setServerError("Name and host are required.");
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
      setServerError(e.message || "Failed to add server.");
    } finally {
      setServerLoading(false);
    }
  }

  async function handleTestConnection() {
    if (!serverHost.trim()) {
      setServerError("Enter a host first.");
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
      {/* Stepper */}
      <div className="mx-auto flex w-full max-w-2xl items-center justify-center gap-2 px-6 pt-10 pb-6">
        {STEPS.map((label, i) => (
          <div key={label} className="flex items-center gap-2">
            <div
              className={cn(
                "flex h-8 w-8 items-center justify-center rounded-full text-xs font-semibold transition-colors",
                i < step && "bg-emerald-500 text-white",
                i === step && "bg-primary text-primary-foreground",
                i > step && "bg-muted text-muted-foreground"
              )}
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

      {/* Content */}
      <div className="mx-auto flex w-full max-w-lg flex-1 flex-col items-center justify-center px-6 pb-20">
        {/* Step 0: Welcome */}
        {step === 0 && (
          <div className="flex flex-col items-center text-center">
            <div className="mb-6 flex h-20 w-20 items-center justify-center rounded-2xl bg-primary/10">
              <MonitorCog className="h-10 w-10 text-primary" />
            </div>
            <h1 className="text-2xl font-bold">Welcome to IPMILink</h1>
            <p className="mt-3 max-w-sm text-sm leading-relaxed text-muted-foreground">
              IPMILink lets you monitor and manage your servers via IPMI from a
              single, beautiful dashboard. Let's get you set up in a few quick
              steps.
            </p>
            <button
              onClick={() => setStep(1)}
              className="mt-8 inline-flex items-center gap-2 rounded-lg bg-primary px-6 py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
            >
              Get Started
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        )}

        {/* Step 1: Auth Setup */}
        {step === 1 && (
          <div className="flex w-full flex-col items-center text-center">
            <div className="mb-6 flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-primary/20 to-primary/5 ring-1 ring-primary/20">
              <ShieldCheck className="h-8 w-8 text-primary" />
            </div>
            <h1 className="text-2xl font-bold tracking-tight">Require login?</h1>
            <p className="mt-2 max-w-sm text-sm leading-relaxed text-muted-foreground">
              Choose whether IPMILink is protected by a username and password, or
              left open to anyone on your network. You can change this later in
              Settings.
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
                    Yes — require login
                  </span>
                  <span className="mt-0.5 block text-xs leading-relaxed text-muted-foreground">
                    Protect the dashboard with a username and password.
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
                    No — open access
                  </span>
                  <span className="mt-0.5 block text-xs leading-relaxed text-muted-foreground">
                    Anyone on your LAN can use IPMILink without logging in.
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
                    Your credentials
                  </p>
                  <div className="relative">
                    <User className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                    <input
                      type="text"
                      placeholder="Username"
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      className="w-full rounded-lg border border-border bg-card py-2 pl-9 pr-3 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
                    />
                  </div>
                  <div className="relative">
                    <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                    <input
                      type="password"
                      placeholder="Password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      className="w-full rounded-lg border border-border bg-card py-2 pl-9 pr-3 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
                    />
                  </div>
                  <div className="relative">
                    <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                    <input
                      type="password"
                      placeholder="Confirm password"
                      value={passwordConfirm}
                      onChange={(e) => setPasswordConfirm(e.target.value)}
                      className={cn(
                        "w-full rounded-lg border bg-card py-2 pl-9 pr-3 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50",
                        password && passwordConfirm && password !== passwordConfirm
                          ? "border-red-500/60"
                          : "border-border"
                      )}
                    />
                  </div>
                  {password && passwordConfirm && password !== passwordConfirm && (
                    <p className="text-xs text-red-500">Passwords do not match.</p>
                  )}
                </div>
              )}

              {authError && (
                <p className="flex items-center gap-1.5 text-xs text-red-500">
                  {authError}
                </p>
              )}
            </div>

            <div className="mt-7 flex w-full max-w-md items-center gap-3">
              <button
                onClick={() => setStep(0)}
                className="inline-flex items-center gap-1 rounded-lg border border-border px-4 py-2.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted/50 hover:text-foreground"
              >
                <ChevronLeft className="h-4 w-4" />
                Back
              </button>
              <button
                onClick={handleAuthStep}
                disabled={authLoading}
                className="inline-flex flex-1 items-center justify-center gap-2 rounded-lg bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground shadow-sm transition-colors hover:bg-primary/90 disabled:opacity-50"
              >
                {authLoading && <Loader2 className="h-4 w-4 animate-spin" />}
                Continue
                <ChevronRight className="h-4 w-4" />
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
            <h1 className="text-xl font-bold">Add Your First Server</h1>
            <p className="mt-2 max-w-sm text-sm text-muted-foreground">
              Enter the IPMI/BMC connection details for your server.
            </p>

            <div className="mt-6 w-full max-w-xs space-y-3 text-left">
              <div>
                <label className="mb-1 block text-xs font-medium text-muted-foreground">
                  Server Name
                </label>
                <input
                  type="text"
                  placeholder="e.g. TrueNAS"
                  value={serverName}
                  onChange={(e) => setServerName(e.target.value)}
                  className="w-full rounded-lg border border-border bg-card px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
                />
              </div>
              <div className="flex gap-2">
                <div className="flex-1">
                  <label className="mb-1 block text-xs font-medium text-muted-foreground">
                    Host / IP
                  </label>
                  <input
                    type="text"
                    placeholder="192.0.2.20"
                    value={serverHost}
                    onChange={(e) => setServerHost(e.target.value)}
                    className="w-full rounded-lg border border-border bg-card px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
                  />
                </div>
                <div className="w-20">
                  <label className="mb-1 block text-xs font-medium text-muted-foreground">
                    Port
                  </label>
                  <input
                    type="number"
                    value={serverPort}
                    onChange={(e) => setServerPort(e.target.value)}
                    className="w-full rounded-lg border border-border bg-card px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
                  />
                </div>
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-muted-foreground">
                  IPMI Username
                </label>
                <input
                  type="text"
                  value={serverUser}
                  onChange={(e) => setServerUser(e.target.value)}
                  className="w-full rounded-lg border border-border bg-card px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-muted-foreground">
                  IPMI Password
                </label>
                <input
                  type="password"
                  value={serverPass}
                  onChange={(e) => setServerPass(e.target.value)}
                  className="w-full rounded-lg border border-border bg-card px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-muted-foreground">
                  Vendor
                </label>
                <select
                  value={serverVendor}
                  onChange={(e) => setServerVendor(e.target.value)}
                  className="w-full rounded-lg border border-border bg-card px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
                >
                  {VENDORS.map((v) => (
                    <option key={v.value} value={v.value}>
                      {v.label}
                    </option>
                  ))}
                </select>
              </div>

              {serverError && (
                <p className="text-xs text-red-500">{serverError}</p>
              )}

              {testResult === "success" && (
                <p className="text-xs text-emerald-500">
                  Connection successful!
                </p>
              )}
              {testResult === "fail" && (
                <p className="text-xs text-red-500">
                  Connection failed. Check your details and try again.
                </p>
              )}
            </div>

            <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
              <button
                onClick={() => setStep(1)}
                className="inline-flex items-center gap-1 rounded-lg border border-border px-4 py-2 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
              >
                <ChevronLeft className="h-4 w-4" />
                Back
              </button>
              <button
                onClick={handleTestConnection}
                disabled={testLoading}
                className="inline-flex items-center gap-2 rounded-lg border border-border px-4 py-2 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors disabled:opacity-50"
              >
                {testLoading && <Loader2 className="h-4 w-4 animate-spin" />}
                Test Connection
              </button>
              <button
                onClick={handleAddServer}
                disabled={serverLoading}
                className="inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50"
              >
                {serverLoading && <Loader2 className="h-4 w-4 animate-spin" />}
                Add Server
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        )}

        {/* Step 3: Done */}
        {step === 3 && (
          <div className="flex flex-col items-center text-center">
            <div className="mb-6 flex h-20 w-20 items-center justify-center rounded-2xl bg-emerald-500/10">
              <CheckCircle2 className="h-10 w-10 text-emerald-500" />
            </div>
            <h1 className="text-2xl font-bold">You're all set!</h1>
            <p className="mt-3 max-w-sm text-sm leading-relaxed text-muted-foreground">
              IPMILink is ready. Your server has been added and will start
              polling for sensor data shortly.
            </p>
            <button
              onClick={() => navigate("/")}
              className="mt-8 inline-flex items-center gap-2 rounded-lg bg-primary px-6 py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
            >
              Go to Dashboard
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
