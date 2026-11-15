import { create } from "zustand";
import { get as apiGet, post } from "@/api/client";

/**
 * Where an update started from the web UI has got to.
 *
 * The server does the work; this only starts it and follows it. `starting` covers the request
 * itself, `back` the moment the new version has answered and the page is about to reload.
 */
export type InstallPhase =
  | "idle"
  | "starting"
  | "backing_up"
  | "installing"
  | "restarting"
  | "restart_required"
  | "failed"
  | "back";

export interface InstallSnapshot {
  phase: InstallPhase;
  target?: string;
  from?: string;
  /** How the new version comes up: by itself, by the operator, or as a new container. */
  restart?: "automatic" | "manual" | "container";
  error_code?: string;
  output?: string;
  /** The folder on the server the pre-update copies were written to, set once the backup is done. */
  backup?: string;
}

interface UpdateInstallStore {
  snapshot: InstallSnapshot;
  /** The new version has been awaited for longer than it should take. */
  slow: boolean;
  /** Ask the server to install the version it found. */
  start: () => Promise<void>;
  /** Follow an update already running on the server (started from another tab, say). */
  resume: () => Promise<void>;
  /** Forget a finished or failed attempt, so the dialog shows the plan again. */
  reset: () => void;
}

export const INSTALL_POLL_MS = 1500;
export const RESTART_POLL_MS = 3000;
export const RESTART_SLOW_MS = 3 * 60 * 1000;

/** Replaced in tests: jsdom cannot reload. */
export const installDeps = {
  reload: () => window.location.reload(),
};

const ACTIVE: InstallPhase[] = ["starting", "backing_up", "installing", "restarting"];

export const isActive = (phase: InstallPhase) => ACTIVE.includes(phase);

// One follow-up at a time. The run number lets a request already on its way see that the
// attempt it belonged to has been replaced or forgotten.
let timer: ReturnType<typeof setTimeout> | null = null;
let run = 0;

function stop() {
  run += 1;
  if (timer !== null) clearTimeout(timer);
  timer = null;
}

const bare = (v: string) => v.replace(/^v/, "");

/**
 * The version answering on this address. Read outside the API client on purpose: while the
 * server restarts, a refused connection is expected and must not count as an error, and an
 * answer of 401 must not send the page to the login screen before it has reloaded.
 */
async function answering(): Promise<{ version: string | null; unauthorized: boolean }> {
  try {
    const res = await fetch("/api/updates/state", { cache: "no-store" });
    if (res.status === 401) return { version: null, unauthorized: true };
    if (!res.ok) return { version: null, unauthorized: false };
    const body = await res.json();
    const version = typeof body?.current_version === "string" ? body.current_version : null;
    return { version, unauthorized: false };
  } catch {
    return { version: null, unauthorized: false };
  }
}

export const useUpdateInstallStore = create<UpdateInstallStore>((set, get) => {
  const waitForVersion = (target: string, mine: number) => {
    const startedAt = Date.now();
    const tick = async () => {
      timer = null;
      if (mine !== run) return;
      const { version, unauthorized } = await answering();
      if (mine !== run) return;
      // A 401 means a server is answering and wants a login: the page reloads into it either way.
      if (unauthorized || (version !== null && bare(version) === bare(target))) {
        set({ snapshot: { ...get().snapshot, phase: "back" } });
        installDeps.reload();
        return;
      }
      if (!get().slow && Date.now() - startedAt > RESTART_SLOW_MS) set({ slow: true });
      timer = setTimeout(tick, RESTART_POLL_MS);
    };
    timer = setTimeout(tick, RESTART_POLL_MS);
  };

  const follow = (snapshot: InstallSnapshot, mine: number) => {
    if (mine !== run) return;
    const target = snapshot.target ?? get().snapshot.target;
    // A server that answers "idle" mid-install is a new process: the old one has restarted.
    if (snapshot.phase === "idle" && isActive(get().snapshot.phase) && target) {
      set({ snapshot: { ...get().snapshot, phase: "restarting" } });
      waitForVersion(target, mine);
      return;
    }
    set({ snapshot: { ...snapshot, target } });
    if (snapshot.phase === "restarting" && target) {
      waitForVersion(target, mine);
    } else if (snapshot.phase === "backing_up" || snapshot.phase === "installing") {
      timer = setTimeout(() => void poll(mine), INSTALL_POLL_MS);
    }
  };

  const poll = async (mine: number) => {
    timer = null;
    if (mine !== run) return;
    let snapshot: InstallSnapshot | null = null;
    try {
      snapshot = await apiGet<InstallSnapshot>("/api/updates/install");
    } catch {
      // Not answering: it may be on its way down already. Ask again.
    }
    if (mine !== run) return;
    if (snapshot === null) {
      timer = setTimeout(() => void poll(mine), INSTALL_POLL_MS);
      return;
    }
    follow(snapshot, mine);
  };

  return {
    snapshot: { phase: "idle" },
    slow: false,

    start: async () => {
      stop();
      const mine = run;
      set({ snapshot: { phase: "starting" }, slow: false });
      let answer: InstallSnapshot & { success: boolean };
      try {
        answer = await post<InstallSnapshot & { success: boolean }>("/api/updates/install");
      } catch {
        answer = { success: false, phase: "failed", error_code: "update_failed" };
      }
      if (mine !== run) return;
      if (!answer.success) {
        set({ snapshot: { phase: "failed", error_code: answer.error_code ?? "update_failed" } });
        return;
      }
      follow(answer, mine);
    },

    resume: async () => {
      if (get().snapshot.phase !== "idle") return;
      let snapshot: InstallSnapshot | null = null;
      try {
        snapshot = await apiGet<InstallSnapshot>("/api/updates/install");
      } catch {
        return;
      }
      if (!snapshot || !isActive(snapshot.phase) || get().snapshot.phase !== "idle") return;
      stop();
      follow(snapshot, run);
    },

    reset: () => {
      stop();
      set({ snapshot: { phase: "idle" }, slow: false });
    },
  };
});
