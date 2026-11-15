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
  checked_at: null as string | null,
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
  FIRST_CHECK_READS_MS,
  STATE_REFRESH_MS,
  useUpdateStore,
} from "@/stores/update-store";

const [FIRST_READ, SECOND_READ, LAST_READ] = FIRST_CHECK_READS_MS;

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

/** The next state read answers with this. */
function answerReadWith(body: Partial<typeof statePayload>) {
  vi.mocked(get).mockResolvedValueOnce({ ...statePayload, ...body });
}

/** A request whose answer the test hands over when it chooses, to put answers out of order. */
function held() {
  let resolve!: (body: typeof statePayload) => void;
  const promise = new Promise<typeof statePayload>((r) => {
    resolve = r;
  });
  return {
    promise,
    answer: (body: Partial<typeof statePayload>) => resolve({ ...statePayload, ...body }),
  };
}

const EARLIER = "2026-10-01T06:00:00+00:00";
const LATER = "2026-10-01T12:00:00+00:00";

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

  it("reads at 15, 30 and 60 seconds after the unattended check is switched on", async () => {
    expect(FIRST_CHECK_READS_MS).toEqual([15_000, 30_000, 60_000]);
    withConsent(false);
    await useUpdateStore.getState().setConsent(true);
    expect(put).toHaveBeenCalledWith("/api/updates/consent", { enabled: true });
    await vi.advanceTimersByTimeAsync(FIRST_READ - 1);
    expect(stateReads()).toBe(0);
    await vi.advanceTimersByTimeAsync(1);
    expect(stateReads()).toBe(1);
    // A slow first check has not written its result yet, so the page asks again.
    await vi.advanceTimersByTimeAsync(SECOND_READ - FIRST_READ - 1);
    expect(stateReads()).toBe(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(stateReads()).toBe(2);
    await vi.advanceTimersByTimeAsync(LAST_READ - SECOND_READ);
    expect(stateReads()).toBe(3);
    // Three reads, not a new poll of its own.
    await vi.advanceTimersByTimeAsync(10 * LAST_READ);
    expect(stateReads()).toBe(3);
    expect(post).not.toHaveBeenCalled();
  });

  it("stops reading as soon as a read shows the first check has finished", async () => {
    withConsent(false);
    answerReadWith({ checked_at: null });
    answerReadWith({ checked_at: LATER });
    await useUpdateStore.getState().setConsent(true);
    await vi.advanceTimersByTimeAsync(10 * LAST_READ);
    expect(stateReads()).toBe(2);
    expect(useUpdateStore.getState().state?.checked_at).toBe(LATER);
    expect(post).not.toHaveBeenCalled();
  });

  it("does not read after the unattended check is switched off", async () => {
    await useUpdateStore.getState().setConsent(false);
    await vi.advanceTimersByTimeAsync(2 * LAST_READ);
    expect(stateReads()).toBe(0);
  });

  it("drops the pending read when the check is switched off again before it", async () => {
    withConsent(false);
    await useUpdateStore.getState().setConsent(true);
    await useUpdateStore.getState().setConsent(false);
    await vi.advanceTimersByTimeAsync(2 * LAST_READ);
    expect(stateReads()).toBe(0);
  });

  it("drops the remaining reads when the check is switched off between them", async () => {
    withConsent(false);
    await useUpdateStore.getState().setConsent(true);
    await vi.advanceTimersByTimeAsync(FIRST_READ);
    expect(stateReads()).toBe(1);
    await useUpdateStore.getState().setConsent(false);
    await vi.advanceTimersByTimeAsync(10 * LAST_READ);
    expect(stateReads()).toBe(1);
  });

  it("books no further read when the check is switched off while one is on its way", async () => {
    withConsent(false);
    const slow = held();
    vi.mocked(get).mockReturnValueOnce(slow.promise);
    await useUpdateStore.getState().setConsent(true);
    await vi.advanceTimersByTimeAsync(FIRST_READ);
    expect(stateReads()).toBe(1);
    await useUpdateStore.getState().setConsent(false);
    slow.answer({ consent: false });
    await vi.advanceTimersByTimeAsync(10 * LAST_READ);
    expect(stateReads()).toBe(1);
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

describe("answers that come back out of order", () => {
  it("does not let a read that started before Check now finished replace its result", async () => {
    const stale = held();
    vi.mocked(get).mockReturnValueOnce(stale.promise);
    const reading = useUpdateStore.getState().loadState();
    vi.mocked(post).mockResolvedValueOnce({
      ...statePayload,
      latest_version: "2.2.0",
      checked_at: LATER,
    });
    await useUpdateStore.getState().checkNow();

    stale.answer({ latest_version: "2.1.0", checked_at: EARLIER });
    await reading;
    expect(useUpdateStore.getState().state?.latest_version).toBe("2.2.0");
    expect(useUpdateStore.getState().state?.checked_at).toBe(LATER);
    expect(useUpdateStore.getState().stateLoading).toBe(false);
  });

  it("shows a read that started after Check now finished", async () => {
    vi.mocked(post).mockResolvedValueOnce({ ...statePayload, checked_at: EARLIER });
    await useUpdateStore.getState().checkNow();
    answerReadWith({ latest_version: "2.3.0", checked_at: LATER });
    await useUpdateStore.getState().loadState();
    expect(useUpdateStore.getState().state?.latest_version).toBe("2.3.0");
  });

  it("does not let an older read that comes back last replace a newer one", async () => {
    const older = held();
    const newer = held();
    vi.mocked(get).mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise);
    const first = useUpdateStore.getState().loadState();
    const second = useUpdateStore.getState().loadState();

    newer.answer({ latest_version: "2.3.0", checked_at: LATER });
    await second;
    older.answer({ latest_version: "2.1.0", checked_at: EARLIER });
    await first;
    expect(useUpdateStore.getState().state?.checked_at).toBe(LATER);
  });

  it("does not let a read that started before consent was saved undo the switch", async () => {
    withConsent(false);
    const stale = held();
    vi.mocked(get).mockReturnValueOnce(stale.promise);
    const reading = useUpdateStore.getState().loadState();
    await useUpdateStore.getState().setConsent(true);

    stale.answer({ consent: false });
    await reading;
    expect(useUpdateStore.getState().state?.consent).toBe(true);
  });

  it("does not re-read on its own while Check now is running", async () => {
    useUpdateStore.setState({ checking: true });
    watch();
    setVisibility("visible");
    await settle();
    expect(stateReads()).toBe(0);
    await vi.advanceTimersByTimeAsync(STATE_REFRESH_MS);
    expect(stateReads()).toBe(0);

    useUpdateStore.setState({ checking: false });
    setVisibility("visible");
    await settle();
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
