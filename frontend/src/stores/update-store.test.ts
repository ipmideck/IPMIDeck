import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { createElement } from "react";
import { cleanup, render } from "@testing-library/react";

/**
 * Keeping the update state current on a page that stays open.
 *
 * The unattended check runs on the server, so a page that read the state once would never show
 * what it found. These tests pin down how the page catches up, and that it only ever re-reads the
 * cached result: asking for a check is a person's action, never a timer's.
 */

const statePayload = {
  success: true,
  enabled: true,
  consent: true,
  current_version: "2.0.1",
  latest_version: "2.1.0",
  update_available: true,
  is_security: false,
  release_url: "https://example.invalid/releases",
  install_method: "pip",
  checked_at: null,
  error: null,
};

vi.mock("@/api/client", () => ({
  get: vi.fn(() => Promise.resolve({ ...statePayload })),
  post: vi.fn(() => Promise.resolve({ success: true })),
  put: vi.fn(() => Promise.resolve({ success: true })),
  del: vi.fn(() => Promise.resolve({ success: true })),
  setUnauthorizedHandler: vi.fn(),
  api: vi.fn(() => Promise.resolve({})),
}));

import { get, post, put } from "@/api/client";
import { VersionButton } from "@/components/layout/VersionButton";
import {
  FIRST_CHECK_SETTLE_MS,
  STATE_REFRESH_MS,
  useUpdateStore,
} from "@/stores/update-store";

let visibility: DocumentVisibilityState = "visible";

beforeAll(() => {
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => visibility,
  });
});

function setVisibility(next: DocumentVisibilityState) {
  visibility = next;
  document.dispatchEvent(new Event("visibilitychange"));
}

// Every watcher a test starts is stopped afterwards, so a failing test cannot leave a listener
// behind that changes the count in the next one.
const stops: Array<() => void> = [];
function watch(): () => void {
  const stop = useUpdateStore.getState().watchState();
  stops.push(stop);
  return stop;
}

function stateReads(): number {
  const calls = (get as unknown as { mock: { calls: string[][] } }).mock.calls;
  return calls.filter((c) => c[0] === "/api/updates/state").length;
}

/** Lets a read that was started resolve, without moving the clock. */
async function settle() {
  await vi.advanceTimersByTimeAsync(0);
}

function withConsent(consent: boolean) {
  useUpdateStore.setState({
    state: { ...statePayload, consent },
    stateLoading: false,
    checking: false,
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
  visibility = "visible";
  withConsent(true);
});

afterEach(() => {
  while (stops.length > 0) stops.pop()?.();
  cleanup();
  vi.clearAllTimers();
  vi.useRealTimers();
});

describe("keeping the update state current on an open page", () => {
  it("re-reads the cached state when the tab is shown again", async () => {
    watch();
    setVisibility("hidden");
    await settle();
    expect(stateReads()).toBe(0);

    setVisibility("visible");
    await settle();
    expect(stateReads()).toBe(1);
    expect(post).not.toHaveBeenCalled();
  });

  it("re-reads once an hour while the unattended check is on", async () => {
    watch();
    await vi.advanceTimersByTimeAsync(STATE_REFRESH_MS - 1);
    expect(stateReads()).toBe(0);
    await vi.advanceTimersByTimeAsync(1);
    expect(stateReads()).toBe(1);
    await vi.advanceTimersByTimeAsync(STATE_REFRESH_MS);
    expect(stateReads()).toBe(2);
    expect(post).not.toHaveBeenCalled();
  });

  it("does not poll while the unattended check is off", async () => {
    withConsent(false);
    watch();
    await vi.advanceTimersByTimeAsync(3 * STATE_REFRESH_MS);
    expect(stateReads()).toBe(0);
  });

  it("reads the result a few seconds after the unattended check is switched on", async () => {
    withConsent(false);
    await useUpdateStore.getState().setConsent(true);
    expect(put).toHaveBeenCalledWith("/api/updates/consent", { enabled: true });
    await vi.advanceTimersByTimeAsync(FIRST_CHECK_SETTLE_MS - 1);
    expect(stateReads()).toBe(0);
    await vi.advanceTimersByTimeAsync(1);
    expect(stateReads()).toBe(1);
    // Once, not a new poll of its own.
    await vi.advanceTimersByTimeAsync(10 * FIRST_CHECK_SETTLE_MS);
    expect(stateReads()).toBe(1);
    expect(post).not.toHaveBeenCalled();
  });

  it("does not read after the unattended check is switched off", async () => {
    await useUpdateStore.getState().setConsent(false);
    await vi.advanceTimersByTimeAsync(2 * FIRST_CHECK_SETTLE_MS);
    expect(stateReads()).toBe(0);
  });

  it("drops the pending read when the check is switched off again before it", async () => {
    withConsent(false);
    await useUpdateStore.getState().setConsent(true);
    await useUpdateStore.getState().setConsent(false);
    await vi.advanceTimersByTimeAsync(2 * FIRST_CHECK_SETTLE_MS);
    expect(stateReads()).toBe(0);
  });

  it("shares one listener and one timer between every caller", async () => {
    watch();
    watch();
    setVisibility("visible");
    await settle();
    expect(stateReads()).toBe(1);
    await vi.advanceTimersByTimeAsync(STATE_REFRESH_MS);
    expect(stateReads()).toBe(2);
  });

  it("stops reading once the last caller has gone", async () => {
    const first = watch();
    const second = watch();
    first();
    // Stopping twice must not take the other caller's share with it.
    first();
    setVisibility("visible");
    await settle();
    expect(stateReads()).toBe(1);

    second();
    setVisibility("visible");
    await vi.advanceTimersByTimeAsync(2 * STATE_REFRESH_MS);
    expect(stateReads()).toBe(1);
  });
});

describe("the version button", () => {
  it("keeps its badge current while mounted, and stops when it is removed", async () => {
    const view = render(createElement(VersionButton));
    setVisibility("visible");
    await settle();
    expect(stateReads()).toBe(1);

    view.unmount();
    setVisibility("visible");
    await vi.advanceTimersByTimeAsync(2 * STATE_REFRESH_MS);
    expect(stateReads()).toBe(1);
    expect(post).not.toHaveBeenCalled();
  });
});
