const BASE = "";

let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}
// REVIEWS #6: exempt ONLY the boot/login auth calls. A 401 on /api/auth/toggle,
// /api/auth/configure, or /api/auth/logout (session expiry mid-Settings) MUST still
// redirect to /login per D-12 — so do NOT exempt all of /api/auth/*.
const NO_REDIRECT_PATHS = ["/api/auth/me", "/api/auth/login"];

export async function api<T = unknown>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
    ...options,
  });
  if (res.status === 401) {
    const exempt = NO_REDIRECT_PATHS.includes(path);
    if (!exempt && onUnauthorized) onUnauthorized();
    throw new Error("API error: 401 Unauthorized");
  }
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export const get = <T = unknown>(path: string) => api<T>(path);

export const post = <T = unknown>(path: string, body?: unknown) =>
  api<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined });

export const put = <T = unknown>(path: string, body?: unknown) =>
  api<T>(path, { method: "PUT", body: body ? JSON.stringify(body) : undefined });

export const del = <T = unknown>(path: string) =>
  api<T>(path, { method: "DELETE" });
