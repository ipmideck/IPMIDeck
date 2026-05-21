import { lazy, Suspense, useEffect } from "react";
import { BrowserRouter, Route, Routes, Navigate, useLocation } from "react-router-dom";
import { Toaster } from "sonner";
import { PageLayout } from "@/components/layout/PageLayout";
import { CommandPalette } from "@/components/CommandPalette";
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";
import { applyTheme, useThemeStore } from "@/stores/theme-store";
import { useServerStore } from "@/stores/server-store";
import { get } from "@/api/client";

const Dashboard = lazy(() => import("@/pages/Dashboard"));
const FanPilotPage = lazy(() => import("@/pages/FanPilotPage"));
const SELPage = lazy(() => import("@/pages/SELPage"));
const FRUPage = lazy(() => import("@/pages/FRUPage"));
const ModulesPage = lazy(() => import("@/pages/ModulesPage"));
const SettingsPage = lazy(() => import("@/pages/SettingsPage"));
const SetupPage = lazy(() => import("@/pages/SetupPage"));

function Loading() {
  return (
    <div className="flex flex-1 items-center justify-center">
      <div className="h-6 w-6 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent" />
    </div>
  );
}

/** Redirects to /setup when no servers exist (first-run experience). */
function SetupRedirect({ children }: { children: React.ReactNode }) {
  const servers = useServerStore((s) => s.servers);
  const loaded = useServerStore((s) => s.loaded);
  const location = useLocation();

  // Until the initial /api/servers fetch resolves, `servers` is [] regardless of
  // whether servers actually exist. Show the spinner instead of deciding the
  // redirect — otherwise a hard reload bounces an authenticated user to /setup.
  if (!loaded) return <Loading />;

  if (loaded && servers.length === 0 && location.pathname !== "/setup") {
    return <Navigate to="/setup" replace />;
  }
  return <>{children}</>;
}

/** Inner shell that lives inside BrowserRouter so hooks like useNavigate work. */
function AppShell() {
  useKeyboardShortcuts();

  return (
    <>
      <Suspense fallback={<Loading />}>
        <Routes>
          <Route
            path="/setup"
            element={<SetupPage />}
          />
          <Route
            path="*"
            element={
              <SetupRedirect>
                <PageLayout>
                  <Suspense fallback={<Loading />}>
                    <Routes>
                      <Route path="/" element={<Dashboard />} />
                      <Route path="/fanpilot" element={<FanPilotPage />} />
                      <Route path="/sel" element={<SELPage />} />
                      <Route path="/fru" element={<FRUPage />} />
                      <Route path="/modules" element={<ModulesPage />} />
                      <Route path="/settings" element={<SettingsPage />} />
                    </Routes>
                  </Suspense>
                </PageLayout>
              </SetupRedirect>
            }
          />
        </Routes>
      </Suspense>
      <CommandPalette />
      <Toaster
        theme="dark"
        position="bottom-right"
        toastOptions={{
          className: "!bg-card !border-border !text-foreground",
        }}
      />
    </>
  );
}

export default function App() {
  const theme = useThemeStore((s) => s.theme);
  const setServers = useServerStore((s) => s.setServers);
  const setLoaded = useServerStore((s) => s.setLoaded);
  const setContextServer = useServerStore((s) => s.setContextServer);

  // Apply theme on mount
  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  // Load servers on mount
  useEffect(() => {
    async function load() {
      try {
        const data = await get<{ servers: any[] }>("/api/servers");
        setServers(data.servers);

        // Load context server
        const ctx = await get<{ server_id: string | null }>("/api/dashboard/context");
        if (ctx.server_id) {
          setContextServer(ctx.server_id);
        }
      } catch {
        // API not available yet (first run or backend not started), or a
        // benign pre-auth 401. Flip loaded so the app doesn't hang on the
        // spinner; SetupRedirect then evaluates (first run with no servers
        // legitimately routes to /setup — the regression was the RACE).
        setLoaded(true);
      }
    }
    load();
  }, [setServers, setLoaded, setContextServer]);

  return (
    <BrowserRouter>
      <AppShell />
    </BrowserRouter>
  );
}
