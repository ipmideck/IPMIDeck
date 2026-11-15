import { describe, expect, it, vi } from "vitest";
import { installStaleBundleReload, reloadForStaleBundle } from "./staleBundle";

/** A tab opened before an upgrade reloads once to pick up the new bundles, and never loops. */

function memoryStorage() {
  const data = new Map<string, string>();
  return {
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
  };
}

describe("reloadForStaleBundle", () => {
  it("reloads the first time", () => {
    const reload = vi.fn();
    expect(reloadForStaleBundle({ storage: memoryStorage(), reload, now: () => 1_000_000 })).toBe(
      true,
    );
    expect(reload).toHaveBeenCalledOnce();
  });

  it("does not reload again within a minute", () => {
    const storage = memoryStorage();
    const reload = vi.fn();
    reloadForStaleBundle({ storage, reload, now: () => 1_000_000 });
    expect(reloadForStaleBundle({ storage, reload, now: () => 1_030_000 })).toBe(false);
    expect(reload).toHaveBeenCalledOnce();
  });

  it("reloads again after a minute, for the next upgrade", () => {
    const storage = memoryStorage();
    const reload = vi.fn();
    reloadForStaleBundle({ storage, reload, now: () => 1_000_000 });
    expect(reloadForStaleBundle({ storage, reload, now: () => 1_061_000 })).toBe(true);
  });

  it("does not reload when it cannot remember having done so", () => {
    const reload = vi.fn();
    const storage = {
      getItem: () => null,
      setItem: () => {
        throw new Error("blocked");
      },
    };
    expect(reloadForStaleBundle({ storage, reload, now: () => 1 })).toBe(false);
    expect(reload).not.toHaveBeenCalled();
  });
});

describe("installStaleBundleReload", () => {
  it("swallows the error only when it reloads", () => {
    window.sessionStorage.clear();
    const reload = vi.fn();
    const win = {
      addEventListener: window.addEventListener.bind(window),
      sessionStorage: window.sessionStorage,
      location: { reload },
    } as unknown as Window;
    installStaleBundleReload(win);

    const first = new Event("vite:preloadError", { cancelable: true });
    window.dispatchEvent(first);
    expect(first.defaultPrevented).toBe(true);
    expect(reload).toHaveBeenCalledOnce();

    const second = new Event("vite:preloadError", { cancelable: true });
    window.dispatchEvent(second);
    expect(second.defaultPrevented).toBe(false);
  });
});
