import { lazy, Suspense, useEffect } from "react";
import {
  BrowserRouter,
  Route,
  Routes,
  Navigate,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { Toaster } from "sonner";
import { PageLayout } from "@/components/layout/PageLayout";
import { CommandPalette } from "@/components/CommandPalette";
import { ShortcutsHelp } from "@/components/ShortcutsHelp";
import { OnboardingTour } from "@/components/OnboardingTour";
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";
import { applyTheme, useThemeStore } from "@/stores/theme-store";
import { useServerStore } from "@/stores/server-store";
import { useAuthStore } from "@/stores/auth-store";
import { useCurrencyStore } from "@/stores/currency-store";
import { useEnergyResetStore } from "@/stores/energy-reset-store";
import { useAlertingStore } from "@/stores/alerting-store";
import { bootstrapAppData } from "@/lib/bootstrap";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { get, setUnauthorizedHandler } from "@/api/client";

const Dashboard = lazy(() => import("@/pages/Dashboard"));
const FanPilotPage = lazy(() => import("@/pages/FanPilotPage"));
const SELPage = lazy(() => import("@/pages/SELPage"));
const FRUPage = lazy(() => import("@/pages/FRUPage"));
const ModulesPage = lazy(() => import("@/pages/ModulesPage"));
const SettingsPage = lazy(() => import("@/pages/SettingsPage"));
const SetupPage = lazy(() => import("@/pages/SetupPage"));
const LoginPage = lazy(() => import("@/pages/LoginPage"));

function Loading() {
  return (
    <div className="flex flex-1 items-center justify-center">
      <div className="h-6 w-6 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent" />
    </div>
  );
}

/**
 * D-07 routing precedence for the APP routes (everything except /setup and /login,
 * which have their own guards below). Replaces the buggy servers-only SetupRedirect.
 */
function AuthGate({ children }: { children: React.ReactNode }) {
  const authLoaded = useAuthStore((s) => s.loaded);
  const serversLoaded = useServerStore((s) => s.loaded);
  const authEnabled = useAuthStore((s) => s.authEnabled);
  const authenticated = useAuthStore((s) => s.authenticated);
  const hasUser = useAuthStore((s) => s.hasUser);
  const servers = useServerStore((s) => s.servers);
  const location = useLocation();

  // GAP-03: in the login-required state the server fetch is skipped (REVIEWS #4),
  // so serversLoaded stays false there — resolve to /login on authLoaded alone for
  // that case; otherwise wait for BOTH flags.
  if (!authLoaded) return <Loading />;
  // D-07 case 1: "no user -> setup" applies ONLY when auth is enabled. When auth is
  // DISABLED (skipped/open access, D-02), no-user is a VALID configured state — fall
  // through to the servers check and render the app. Guarding on authEnabled here is
  // what breaks the AuthGate(/->/setup) <-> SetupGuard(/setup->/) infinite loop (GAP-AUTH-01).
  if (!hasUser && authEnabled) return <Navigate to="/setup" replace />;
  if (hasUser && authEnabled && !authenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }
  // From here we are authenticated or auth is off -> the server fetch ran; wait for it.
  if (!serversLoaded) return <Loading />;
  if ((authenticated || !authEnabled) && servers.length === 0) {
    return <Navigate to="/setup" replace />;
  }
  return <>{children}</>;
}

/** D-07 precedence guard for the top-level /setup route (REVIEWS #3). */
function SetupGuard() {
  const authLoaded = useAuthStore((s) => s.loaded);
  const authEnabled = useAuthStore((s) => s.authEnabled);
  const authenticated = useAuthStore((s) => s.authenticated);
  const hasUser = useAuthStore((s) => s.hasUser);
  const serversLoaded = useServerStore((s) => s.loaded);
  const servers = useServerStore((s) => s.servers);
  if (!authLoaded) return <Loading />;
  // Logged-out user WITH an account must not see setup -> /login (REVIEWS #3).
  if (hasUser && authEnabled && !authenticated) return <Navigate to="/login" replace />;
  // Already usable (authenticated or open) AND servers exist -> app (REVIEWS #3).
  if ((authenticated || !authEnabled) && serversLoaded && servers.length > 0) {
    return <Navigate to="/" replace />;
  }
  return <SetupPage />;
}

/** D-07 precedence guard for the top-level /login route (REVIEWS #3). */
function LoginGuard() {
  const authLoaded = useAuthStore((s) => s.loaded);
  const authEnabled = useAuthStore((s) => s.authEnabled);
  const authenticated = useAuthStore((s) => s.authenticated);
  const hasUser = useAuthStore((s) => s.hasUser);
  const location = useLocation();
  if (!authLoaded) return <Loading />;
  // No account yet -> there is nothing to log into -> setup (REVIEWS #3).
  if (!hasUser) return <Navigate to="/setup" replace />;
  // Auth off or already authenticated -> go to intended path / home (REVIEWS #3, D-05).
  if (!authEnabled || authenticated) {
    const from = (
      location.state as { from?: { pathname?: string; search?: string; hash?: string } } | null
    )?.from;
    const target = from
      ? `${from.pathname ?? "/"}${from.search ?? ""}${from.hash ?? ""}`
      : "/";
    return <Navigate to={target} replace />;
  }
  return <LoginPage />;
}

/** Inner shell that lives inside BrowserRouter so hooks like useNavigate work. */
function AppShell() {
  useKeyboardShortcuts();

  const navigate = useNavigate();
  const location = useLocation();
  // Wave 7: Sonner toasts move to bottom-center on mobile for thumb reach,
  // bottom-right on desktop (Decision M — Toaster is mounted HERE, not PageLayout).
  const isMobile = useMediaQuery("(max-width: 767px)");
  useEffect(() => {
    setUnauthorizedHandler(() => {
      // Mark unauthenticated so AuthGate routes correctly; preserve intended path (D-05, LOW).
      useAuthStore.setState({ authenticated: false });
      if (location.pathname !== "/login") {
        navigate("/login", {
          replace: true,
          state: {
            from: {
              pathname: location.pathname,
              search: location.search,
              hash: location.hash,
            },
          },
        });
      }
    });
  }, [navigate, location]);

  return (
    <>
      <Suspense fallback={<Loading />}>
        <Routes>
          <Route path="/setup" element={<SetupGuard />} />
          <Route path="/login" element={<LoginGuard />} />
          <Route
            path="*"
            element={
              <AuthGate>
                <PageLayout>
                  <OnboardingTour />
                  <Suspense fallback={<Loading />}>
                    <Routes>
                      <Route path="/" element={<Dashboard />} />
                      <Route path="/fanpilot" element={<FanPilotPage />} />
                      <Route path="/sel" element={<SELPage />} />
                      <Route path="/fru" element={<FRUPage />} />
                      <Route path="/modules" element={<ModulesPage />} />
                      {/* Wildcard so SettingsPage owns the section sub-routing
                          (06-08 builds the two-pane + nested section routes; the
                          index redirect to /settings/servers already lives inside
                          SettingsPage so bare /settings call-sites land populated). */}
                      <Route path="/settings/*" element={<SettingsPage />} />
                    </Routes>
                  </Suspense>
                </PageLayout>
              </AuthGate>
            }
          />
        </Routes>
      </Suspense>
      <CommandPalette />
      <ShortcutsHelp />
      <Toaster
        theme="dark"
        position={isMobile ? "bottom-center" : "bottom-right"}
        mobileOffset={{ bottom: "16px" }}
        toastOptions={{
          className: "!bg-card !border-border !text-foreground",
        }}
      />
    </>
  );
}

export default function App() {
  const theme = useThemeStore((s) => s.theme);
  const setAuth = useAuthStore((s) => s.setAuth);

  // Apply theme on mount
  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  // GAP-2 (04-12): hydrate the global currency ONCE at the app shell so cost widgets
  // (Power Control, Energy Cost, Power Stats) show the configured currency on the very
  // first dashboard paint — regardless of whether the user lands on `/` or /settings.
  // Idempotent with SettingsPage:73 via the store's `hydrated` guard. getState() (not the
  // hook) keeps this effect dependency-free and avoids a re-render subscription.
  useEffect(() => {
    useCurrencyStore.getState().hydrate();
  }, []);

  // Pitfall 4 / D-13 high caveat: energy-reset (feeds powerShared.tsx) and alerting
  // (feeds useWebSocket.ts) hydrate ONLY inside the monolithic SettingsPage today. When
  // 06-08 splits Settings into URL-routed sections, a user landing on `/` would never
  // mount SettingsPage and these would silently never fire. Lift both to the App shell
  // NOW, mirroring the idempotent currency hydrate above. getState() (not the hook) keeps
  // these effects dependency-free; each store's `hydrated` guard makes a second call from
  // SettingsPage a no-op (06-08 cleans up the duplicate calls).
  useEffect(() => {
    useEnergyResetStore.getState().hydrate();
  }, []);
  useEffect(() => {
    useAlertingStore.getState().hydrate();
  }, []);

  // Boot: fetch /api/auth/me FIRST, then load protected data only when usable.
  useEffect(() => {
    async function load() {
      let authEnabled = true;
      let authenticated = false;
      try {
        const me = await get<{
          authenticated: boolean;
          username?: string;
          auth_enabled: boolean;
          has_user: boolean;
        }>("/api/auth/me");
        authEnabled = me.auth_enabled;
        authenticated = me.authenticated;
        setAuth({
          authEnabled,
          authenticated,
          hasUser: me.has_user,
          username: me.username ?? null,
        });
      } catch {
        // Fail closed: assume auth required + not authenticated -> user sees /login.
        authEnabled = true;
        authenticated = false;
        setAuth({ authEnabled: true, authenticated: false, hasUser: true, username: null });
      }
      // REVIEWS #4: only load protected resources when the app is actually usable.
      // In the login-required state (authEnabled && !authenticated) SKIP the server fetch
      // entirely — do NOT mark the server store loaded:[] (that would later imply
      // "no servers -> setup" after login). AuthGate resolves the login-required state
      // on authLoaded alone (see AuthGate above), so leaving serversLoaded:false is correct.
      if (!authEnabled || authenticated) {
        await bootstrapAppData();
      }
    }
    load();
  }, [setAuth]);

  return (
    <BrowserRouter>
      <AppShell />
    </BrowserRouter>
  );
}
