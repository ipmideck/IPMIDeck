import { lazy, Suspense, useEffect } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Toaster } from "sonner";
import { PageLayout } from "@/components/layout/PageLayout";
import { applyTheme, useThemeStore } from "@/stores/theme-store";
import { useServerStore } from "@/stores/server-store";
import { get } from "@/api/client";

const Dashboard = lazy(() => import("@/pages/Dashboard"));
const FanPilotPage = lazy(() => import("@/pages/FanPilotPage"));
const SELPage = lazy(() => import("@/pages/SELPage"));
const FRUPage = lazy(() => import("@/pages/FRUPage"));
const ModulesPage = lazy(() => import("@/pages/ModulesPage"));
const SettingsPage = lazy(() => import("@/pages/SettingsPage"));

function Loading() {
  return (
    <div className="flex flex-1 items-center justify-center">
      <div className="h-6 w-6 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent" />
    </div>
  );
}

export default function App() {
  const theme = useThemeStore((s) => s.theme);
  const setServers = useServerStore((s) => s.setServers);
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
        // API not available yet (first run or backend not started)
      }
    }
    load();
  }, [setServers, setContextServer]);

  return (
    <BrowserRouter>
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
      <Toaster
        theme="dark"
        position="bottom-right"
        toastOptions={{
          className: "!bg-card !border-border !text-foreground",
        }}
      />
    </BrowserRouter>
  );
}
