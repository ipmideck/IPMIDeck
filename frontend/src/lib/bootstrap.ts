import { get } from "@/api/client";
import { useServerStore, type Server } from "@/stores/server-store";

/**
 * Post-auth data load (servers + dashboard context). Factored out (REVIEWS #5)
 * so App boot and LoginPage success run the IDENTICAL bootstrap and cannot drift.
 * Call ONLY when (!authEnabled || authenticated) — never while login is required,
 * so the protected /api/servers fetch never 401s into a loaded:[] state (REVIEWS #4).
 * On failure it still marks the server store loaded so routing can resolve.
 */
export async function bootstrapAppData(): Promise<void> {
  const { setServers, setLoaded } = useServerStore.getState();
  try {
    const data = await get<{ servers: Server[] }>("/api/servers");
    setServers(data.servers);
    const ctx = await get<{ server_id: string | null }>("/api/dashboard/context");
    if (ctx.server_id) {
      useServerStore.getState().setContextServer(ctx.server_id);
    }
  } catch {
    setLoaded(true);
  }
}
