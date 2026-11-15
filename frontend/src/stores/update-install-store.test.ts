import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Following an update started from the web UI: the progress the server reports, and the wait
 * for the new version that ends in a reload.
 */

vi.mock("@/api/client", () => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  del: vi.fn(),
  api: vi.fn(),
  setUnauthorizedHandler: vi.fn(),
}));

import { get, post } from "@/api/client";
import {
  INSTALL_POLL_MS,
  RESTART_POLL_MS,
  RESTART_SLOW_MS,
  installDeps,
  useUpdateInstallStore,
} from "@/stores/update-install-store";

const mockedGet = get as unknown as ReturnType<typeof vi.fn>;
const mockedPost = post as unknown as ReturnType<typeof vi.fn>;
let fetchMock: ReturnType<typeof vi.fn>;
let reload: ReturnType<typeof vi.fn>;

function answers(...versions: (string | number | Error)[]) {
  for (const v of versions) {
    if (v instanceof Error) fetchMock.mockRejectedValueOnce(v);
    else if (typeof v === "number") fetchMock.mockResolvedValueOnce({ ok: false, status: v });
    else
      fetchMock.mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ current_version: v }),
      });
  }
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  reload = vi.fn();
  installDeps.reload = reload;
  useUpdateInstallStore.getState().reset();
});

afterEach(() => {
  useUpdateInstallStore.getState().reset();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("installing an update from the web UI", () => {
  it("follows the install to the restart and reloads once the new version answers", async () => {
    mockedPost.mockResolvedValueOnce({ success: true, phase: "backing_up", target: "2.1.0" });
    mockedGet
      .mockResolvedValueOnce({ success: true, phase: "installing", target: "2.1.0" })
      .mockResolvedValueOnce({ success: true, phase: "restarting", target: "2.1.0", restart: "automatic" });
    // The old process still answers for a moment, then nothing, then the new one.
    answers("2.0.1", new TypeError("refused"), "2.1.0");

    await useUpdateInstallStore.getState().start();
    expect(mockedPost).toHaveBeenCalledWith("/api/updates/install");
    expect(useUpdateInstallStore.getState().snapshot.phase).toBe("backing_up");

    await vi.advanceTimersByTimeAsync(INSTALL_POLL_MS);
    expect(useUpdateInstallStore.getState().snapshot.phase).toBe("installing");
    await vi.advanceTimersByTimeAsync(INSTALL_POLL_MS);
    expect(useUpdateInstallStore.getState().snapshot.phase).toBe("restarting");

    await vi.advanceTimersByTimeAsync(RESTART_POLL_MS * 2);
    expect(reload).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(RESTART_POLL_MS);
    expect(reload).toHaveBeenCalledTimes(1);
    expect(useUpdateInstallStore.getState().snapshot.phase).toBe("back");
  });

  it("reads the new version outside the API client, so a 401 reloads instead of redirecting", async () => {
    mockedPost.mockResolvedValueOnce({
      success: true,
      phase: "restarting",
      target: "2.1.0",
      restart: "container",
    });
    answers(401);
    await useUpdateInstallStore.getState().start();
    await vi.advanceTimersByTimeAsync(RESTART_POLL_MS);
    expect(fetchMock).toHaveBeenCalledWith("/api/updates/state", { cache: "no-store" });
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("shows the reason the server refused", async () => {
    mockedPost.mockResolvedValueOnce({ success: false, error_code: "update_docker" });
    await useUpdateInstallStore.getState().start();
    expect(useUpdateInstallStore.getState().snapshot).toEqual({
      phase: "failed",
      error_code: "update_docker",
    });
  });

  it("treats a request that never got an answer as a failure", async () => {
    mockedPost.mockRejectedValueOnce(new Error("network"));
    await useUpdateInstallStore.getState().start();
    expect(useUpdateInstallStore.getState().snapshot.error_code).toBe("update_failed");
  });

  it("stops at a failed install and keeps its output", async () => {
    mockedPost.mockResolvedValueOnce({ success: true, phase: "installing", target: "2.1.0" });
    mockedGet.mockResolvedValueOnce({
      success: true,
      phase: "failed",
      error_code: "update_failed",
      output: "pip said no",
    });
    await useUpdateInstallStore.getState().start();
    await vi.advanceTimersByTimeAsync(INSTALL_POLL_MS);
    const { snapshot } = useUpdateInstallStore.getState();
    expect(snapshot.phase).toBe("failed");
    expect(snapshot.output).toBe("pip said no");
    await vi.advanceTimersByTimeAsync(INSTALL_POLL_MS * 5);
    expect(mockedGet).toHaveBeenCalledTimes(1);
  });

  it("takes a server that answers idle mid-install for one that has already restarted", async () => {
    mockedPost.mockResolvedValueOnce({ success: true, phase: "installing", target: "2.1.0" });
    mockedGet.mockResolvedValueOnce({ success: true, phase: "idle" });
    answers("2.1.0");
    await useUpdateInstallStore.getState().start();
    await vi.advanceTimersByTimeAsync(INSTALL_POLL_MS);
    expect(useUpdateInstallStore.getState().snapshot.phase).toBe("restarting");
    await vi.advanceTimersByTimeAsync(RESTART_POLL_MS);
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("says so when the new version is long in coming", async () => {
    mockedPost.mockResolvedValueOnce({
      success: true,
      phase: "restarting",
      target: "2.1.0",
      restart: "automatic",
    });
    fetchMock.mockRejectedValue(new TypeError("refused"));
    await useUpdateInstallStore.getState().start();
    expect(useUpdateInstallStore.getState().slow).toBe(false);
    await vi.advanceTimersByTimeAsync(RESTART_SLOW_MS + RESTART_POLL_MS * 2);
    expect(useUpdateInstallStore.getState().slow).toBe(true);
    expect(reload).not.toHaveBeenCalled();
  });

  it("picks up an install already running on the server", async () => {
    mockedGet.mockResolvedValueOnce({ success: true, phase: "installing", target: "2.1.0" });
    await useUpdateInstallStore.getState().resume();
    expect(useUpdateInstallStore.getState().snapshot.phase).toBe("installing");
  });

  it("leaves an idle server alone", async () => {
    mockedGet.mockResolvedValueOnce({ success: true, phase: "idle" });
    await useUpdateInstallStore.getState().resume();
    expect(useUpdateInstallStore.getState().snapshot.phase).toBe("idle");
    await vi.advanceTimersByTimeAsync(INSTALL_POLL_MS * 3);
    expect(mockedGet).toHaveBeenCalledTimes(1);
  });

  it("stops following once reset", async () => {
    mockedPost.mockResolvedValueOnce({ success: true, phase: "installing", target: "2.1.0" });
    await useUpdateInstallStore.getState().start();
    useUpdateInstallStore.getState().reset();
    await vi.advanceTimersByTimeAsync(INSTALL_POLL_MS * 3);
    expect(mockedGet).not.toHaveBeenCalled();
    expect(useUpdateInstallStore.getState().snapshot.phase).toBe("idle");
  });
});
