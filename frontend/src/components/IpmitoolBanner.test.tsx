import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

/**
 * The notice shown while the backend cannot find ipmitool, and the dialog behind its Install
 * button: what each host is offered, the install itself, and "Check again".
 */

let ipmitool: Record<string, unknown> = {};
let installAnswer: Record<string, unknown> = { success: true };

vi.mock("@/api/client", () => ({
  get: vi.fn((path: string) =>
    path === "/api/config" ? Promise.resolve({ demo: false, ipmitool }) : Promise.resolve({}),
  ),
  post: vi.fn((path: string) =>
    path === "/api/system/ipmitool/install"
      ? Promise.resolve(installAnswer)
      : Promise.resolve({}),
  ),
}));

// Real i18n singleton, so the assertions read the English catalog rather than raw keys.
import i18n from "@/i18n";
import { post } from "@/api/client";
import { IpmitoolBanner } from "./IpmitoolBanner";

const linux = {
  available: false,
  install_command: "sudo apt install ipmitool",
  platform: "linux",
  os_label: "Ubuntu 24.04 LTS",
};

beforeEach(async () => {
  vi.clearAllMocks();
  ipmitool = {};
  installAnswer = { success: true };
  await i18n.changeLanguage("en");
});

afterEach(() => {
  cleanup();
});

async function openDialog() {
  render(<IpmitoolBanner />);
  await screen.findByRole("alert");
  await userEvent.click(screen.getByRole("button", { name: "Install" }));
  return screen.findByRole("dialog");
}

describe("IpmitoolBanner", () => {
  it("renders nothing while ipmitool is available", async () => {
    ipmitool = { available: true, install_command: null, platform: "linux" };
    const { container } = render(<IpmitoolBanner />);
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("names the problem and offers Install and Check again", async () => {
    ipmitool = { ...linux, install: { automatic: false, reason: "disabled" } };
    render(<IpmitoolBanner />);
    expect(await screen.findByRole("alert")).toHaveTextContent("ipmitool is not installed");
    expect(screen.getByRole("button", { name: "Install" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check again" })).toBeInTheDocument();
  });

  it("disappears when Check again finds the program", async () => {
    ipmitool = { ...linux, install: { automatic: false, reason: "disabled" } };
    render(<IpmitoolBanner />);
    await screen.findByRole("alert");
    ipmitool = { available: true, install_command: null, platform: "linux" };
    await userEvent.click(screen.getByRole("button", { name: "Check again" }));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });

  it("says so when Check again still cannot find it", async () => {
    ipmitool = { ...linux, install: { automatic: false, reason: "disabled" } };
    render(<IpmitoolBanner />);
    await screen.findByRole("alert");
    await userEvent.click(screen.getByRole("button", { name: "Check again" }));
    expect(await screen.findByText(/Still not found/)).toBeInTheDocument();
  });
});

describe("the install dialog", () => {
  it("explains why it cannot install, and gives the command to run", async () => {
    ipmitool = { ...linux, install: { automatic: false, reason: "no_privileges" } };
    const dialog = await openDialog();
    expect(dialog).toHaveTextContent("Detected system: Ubuntu 24.04 LTS");
    expect(dialog).toHaveTextContent("not running with administrator rights");
    expect(within(dialog).getByText("sudo apt install ipmitool")).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Install now" })).toBeNull();
  });

  it("installs when the backend can, and reports success", async () => {
    ipmitool = { ...linux, install: { automatic: true, reason: null } };
    const dialog = await openDialog();
    await userEvent.click(within(dialog).getByRole("button", { name: "Install now" }));
    expect(post).toHaveBeenCalledWith("/api/system/ipmitool/install");
    expect(await within(dialog).findByText(/ipmitool is installed/)).toBeInTheDocument();
  });

  it("shows the failure, the output and the command when the install fails", async () => {
    ipmitool = { ...linux, install: { automatic: true, reason: null } };
    installAnswer = {
      success: false,
      error_code: "ipmitool_install_failed",
      output: "E: Unable to locate package ipmitool",
    };
    const dialog = await openDialog();
    await userEvent.click(within(dialog).getByRole("button", { name: "Install now" }));
    expect(
      await within(dialog).findByText("The installation did not complete."),
    ).toBeInTheDocument();
    expect(dialog).toHaveTextContent("Unable to locate package ipmitool");
    expect(within(dialog).getByText("sudo apt install ipmitool")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("guides Windows through a vendor tool instead of inventing a command", async () => {
    ipmitool = {
      available: false,
      install_command: null,
      platform: "windows",
      os_label: "Windows",
      install: { automatic: false, reason: "windows" },
      search_dirs: ["C:\\Program Files\\Dell\\SysMgt\\bmc"],
    };
    const dialog = await openDialog();
    expect(dialog).toHaveTextContent("iDRAC Tools");
    expect(dialog).toHaveTextContent("C:\\Program Files\\Dell\\SysMgt\\bmc");
    expect(dialog).not.toHaveTextContent("WSL");
    expect(within(dialog).queryByRole("button", { name: "Install now" })).toBeNull();
  });
});
