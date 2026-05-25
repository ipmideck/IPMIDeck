import { create } from "zustand";

interface AuthState {
  loaded: boolean; // false until GET /api/auth/me resolves (GAP-03 guard)
  authEnabled: boolean; // from /me auth_enabled; default true = fail closed
  authenticated: boolean; // from /me authenticated
  hasUser: boolean; // from /me has_user (D-14)
  username: string | null;
  setAuth: (s: {
    authEnabled: boolean;
    authenticated: boolean;
    hasUser: boolean;
    username: string | null;
  }) => void;
  setLoaded: (loaded: boolean) => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  loaded: false,
  authEnabled: true,
  authenticated: false,
  hasUser: false,
  username: null,
  setAuth: (s) => set({ ...s, loaded: true }),
  setLoaded: (loaded) => set({ loaded }),
}));
