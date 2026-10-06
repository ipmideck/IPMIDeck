import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";

/**
 * The guide link follows the language picked in IPMIDeck, not English: the docs keep a page
 * per UI language under the same codes. Separate file, because it pins the i18n instance.
 */

const language = vi.hoisted(() => ({ current: "it" }));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { resolvedLanguage: language.current },
  }),
}));

vi.mock("@/api/client", () => ({
  get: vi.fn(() => Promise.resolve({ success: true, phase: "idle" })),
  post: vi.fn(),
  put: vi.fn(),
  del: vi.fn(),
  api: vi.fn(),
  setUnauthorizedHandler: vi.fn(),
}));

import { UpdateDialog } from "@/components/UpdateDialog";
import { useUIOverlayStore } from "@/stores/ui-overlay-store";
import { useUpdateInstallStore } from "@/stores/update-install-store";
import { useUpdateStore } from "@/stores/update-store";

afterEach(() => {
  cleanup();
  useUIOverlayStore.setState({ updateOpen: false });
  useUpdateInstallStore.getState().reset();
});

describe("the update guide link", () => {
  it.each(["it", "de", "ja", "zh-Hans"])("opens the %s page when IPMIDeck is in that language", async (code) => {
    language.current = code;
    useUpdateStore.setState({
      state: {
        enabled: true,
        consent: true,
        current_version: "2.0.1",
        latest_version: "2.1.0",
        update_available: true,
        is_security: false,
        release_url: "https://example.invalid/releases/v2.1.0",
        install_method: "docker",
        checked_at: "2026-10-06T10:00:00Z",
        error: null,
        notes: null,
        upgrade: {
          automatic: false,
          mechanism: null,
          command: "docker compose pull && docker compose up -d",
          reason: "docker",
          restart: null,
        },
      },
    });
    render(<UpdateDialog />);
    act(() => useUIOverlayStore.getState().setUpdateOpen(true));
    const guide = await waitFor(() => screen.getByRole("link", { name: /updateDialog\.guide/ }));
    expect(guide.getAttribute("href")).toBe(`https://docs.ipmideck.com/${code}/update-from-web-ui`);
  });
});
