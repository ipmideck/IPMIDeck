import { Command } from "cmdk";
import * as Dialog from "@radix-ui/react-dialog";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useServerStore } from "@/stores/server-store";
import { useUIOverlayStore } from "@/stores/ui-overlay-store";
import { put } from "@/api/client";
import {
  LayoutDashboard,
  Fan,
  List,
  Cpu,
  Package,
  Settings,
  Server,
  Power,
  PowerOff,
  Volume2,
} from "lucide-react";

// Only stable paths/keys + icons at module load; labels resolved via t() in render.
const pages = [
  { labelKey: "nav.dashboard", path: "/", icon: LayoutDashboard },
  { labelKey: "nav.fanpilot", path: "/fanpilot", icon: Fan },
  { labelKey: "nav.sel", path: "/sel", icon: List },
  { labelKey: "nav.fru", path: "/fru", icon: Cpu },
  { labelKey: "nav.modules", path: "/modules", icon: Package },
  { labelKey: "nav.settings", path: "/settings", icon: Settings },
];

const actions = [
  { id: "powerOn", labelKey: "palette.powerOn", keywords: ["power", "start", "boot"], icon: Power },
  { id: "powerOff", labelKey: "palette.powerOff", keywords: ["power", "shutdown", "stop"], icon: PowerOff },
  { id: "powerCycle", labelKey: "palette.powerCycle", keywords: ["restart", "reboot", "cycle"], icon: Power },
  { id: "switchSilent", labelKey: "palette.switchSilent", keywords: ["fan", "quiet", "silent", "profile"], icon: Volume2 },
  { id: "switchBalanced", labelKey: "palette.switchBalanced", keywords: ["fan", "balanced", "profile"], icon: Volume2 },
  { id: "switchPerformance", labelKey: "palette.switchPerformance", keywords: ["fan", "performance", "loud", "profile"], icon: Volume2 },
];

export function CommandPalette() {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const { servers, setContextServer } = useServerStore();
  const setCommandOpen = useUIOverlayStore((s) => s.setCommandOpen);
  const commandOpenRequest = useUIOverlayStore((s) => s.commandOpenRequest);

  // Mirror the palette's local open state into ui-overlay-store.commandOpen so the
  // keyboard-shortcuts guard suppresses nav/server shortcuts while the palette is open
  // (D-07 / REVIEWS MED #9). The palette still owns its own open state — this only syncs.
  useEffect(() => {
    setCommandOpen(open);
  }, [open, setCommandOpen]);

  // React to the onboarding tour's inward "request open" flag (260608-7kj): the
  // tour sets requestCommandOpen(true/false) during its command-palette step to
  // open/close the REAL palette live. This drives local `open`, so the outward
  // mirror above still fires (keeping the keyboard ?-guard intact). Cmd+K and the
  // local open state remain the source of truth for normal use.
  useEffect(() => {
    setOpen(commandOpenRequest);
  }, [commandOpenRequest]);

  // Listen for Cmd+K / Ctrl+K
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((prev) => !prev);
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, []);

  async function handleSelectServer(id: string) {
    setContextServer(id);
    setOpen(false);
    try {
      await put("/api/dashboard/context", { server_id: id });
    } catch {
      // silently fail
    }
  }

  function handleSelectPage(path: string) {
    navigate(path);
    setOpen(false);
  }

  function handleSelectAction(_id: string) {
    // Actions are placeholders for now — close palette
    setOpen(false);
  }

  // When the onboarding tour drives the palette open (260608-7kj), it must coexist
  // with the react-joyride overlay/tooltip instead of trapping focus underneath it.
  // The default cmdk Command.Dialog renders a MODAL Radix dialog (focus trap +
  // outside-inert/pointer-events:none + its own z-50 overlay) — that makes the
  // joyride tooltip's buttons unclickable. For the tour-driven open we instead
  // render a NON-MODAL Radix dialog (no focus trap, no inert, no Radix overlay)
  // and raise the content ABOVE the joyride overlay (zIndex 10000) so the palette
  // is visible over the dim while the joyride tooltip (floater = overlay+1 = 10001)
  // still floats on top and stays interactive.
  const tourDriven = commandOpenRequest;

  // Shared inner content (input + grouped list). Identical for both modes — only
  // the surrounding dialog (modal vs non-modal) and z-index differ.
  const paletteInner = (
    <div className="rounded-xl border border-border bg-popover text-popover-foreground shadow-2xl overflow-hidden">
        <Command.Input
          placeholder={t("palette.placeholder")}
          className="w-full border-b border-border bg-transparent px-4 py-3 text-sm outline-none placeholder:text-muted-foreground"
        />
        <Command.List className="max-h-80 overflow-y-auto p-2">
          <Command.Empty className="px-4 py-6 text-center text-sm text-muted-foreground">
            {t("palette.empty")}
          </Command.Empty>

          {/* Servers */}
          {servers.length > 0 && (
            <Command.Group
              heading={t("palette.groupServers")}
              className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-muted-foreground"
            >
              {servers.map((server) => (
                <Command.Item
                  key={server.id}
                  value={`server ${server.name} ${server.host}`}
                  onSelect={() => handleSelectServer(server.id)}
                  className="flex items-center gap-3 rounded-md px-2 py-2 text-sm cursor-pointer aria-selected:bg-accent aria-selected:text-accent-foreground"
                >
                  <Server className="h-4 w-4 shrink-0 text-muted-foreground" />
                  <div className="flex items-center gap-2 min-w-0 flex-1">
                    <div
                      className="h-2 w-2 shrink-0 rounded-full"
                      style={{
                        backgroundColor: server.is_online
                          ? "var(--color-success)"
                          : "var(--color-danger)",
                      }}
                    />
                    <span className="truncate">{server.name}</span>
                    <span className="font-mono text-xs text-muted-foreground">{server.host}</span>
                  </div>
                </Command.Item>
              ))}
            </Command.Group>
          )}

          {/* Pages */}
          <Command.Group
            heading={t("palette.groupPages")}
            className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-muted-foreground"
          >
            {pages.map((page) => {
              const label = t(page.labelKey);
              return (
                <Command.Item
                  key={page.path}
                  value={`page ${label}`}
                  onSelect={() => handleSelectPage(page.path)}
                  className="flex items-center gap-3 rounded-md px-2 py-2 text-sm cursor-pointer aria-selected:bg-accent aria-selected:text-accent-foreground"
                >
                  <page.icon className="h-4 w-4 shrink-0 text-muted-foreground" />
                  <span>{label}</span>
                </Command.Item>
              );
            })}
          </Command.Group>

          {/* Actions */}
          <Command.Group
            heading={t("palette.groupActions")}
            className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-muted-foreground"
          >
            {actions.map((action) => {
              const label = t(action.labelKey);
              return (
                <Command.Item
                  key={action.id}
                  value={`action ${label}`}
                  keywords={action.keywords}
                  onSelect={() => handleSelectAction(action.id)}
                  className="flex items-center gap-3 rounded-md px-2 py-2 text-sm cursor-pointer aria-selected:bg-accent aria-selected:text-accent-foreground"
                >
                  <action.icon className="h-4 w-4 shrink-0 text-muted-foreground" />
                  <span>{label}</span>
                </Command.Item>
              );
            })}
          </Command.Group>
        </Command.List>
      </div>
  );

  // Tour-driven: NON-MODAL so the joyride tooltip stays interactive (no focus
  // trap, no outside-inert, no Radix overlay). Raise the content above the
  // joyride overlay (z 10000) so the palette shows over the dim; the joyride
  // floater (10001) still renders on top and its buttons remain clickable.
  // We render Radix Dialog.Root directly (NOT cmdk's Command.Dialog) because
  // cmdk's Command.Dialog does not forward `modal` to Dialog.Root at runtime —
  // it only passes open/onOpenChange and spreads the rest onto Command.Root.
  if (tourDriven) {
    return (
      <Dialog.Root open={open} onOpenChange={setOpen} modal={false}>
        <Dialog.Portal>
          {/* No own overlay: the joyride overlay (z 10000) already dims the page.
              The palette content sits ABOVE it (10001) so it shows over the dim,
              while the joyride floater/tooltip (also 10001, but its portal mounts
              AFTER this one via the step `before` hook) renders on top and stays
              clickable. Non-modal Radix renders no overlay of its own here. */}
          <Dialog.Content
            aria-label={t("palette.label")}
            // Stable anchor for the onboarding tour's command step (260608-7kj
            // step-6 fix): the tour targets this element with a SIDE placement so
            // its tooltip renders OUTSIDE the palette rectangle (not centered
            // behind it), keeping the Next/Done/Back/Skip buttons clickable.
            data-tour="command-palette"
            className="fixed top-[20%] left-1/2 -translate-x-1/2 w-full max-w-lg"
            style={{ zIndex: 10001 }}
            // Keep the tour in control of dismissal: don't auto-close on outside
            // interaction (the user may click the joyride tooltip buttons).
            onInteractOutside={(e) => e.preventDefault()}
            onPointerDownOutside={(e) => e.preventDefault()}
          >
            <Dialog.Title className="sr-only">{t("palette.label")}</Dialog.Title>
            <Command label={t("palette.label")} loop>
              {paletteInner}
            </Command>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    );
  }

  // Normal Cmd+K: keep the EXISTING modal behavior (focus trap, z-50 overlay) and
  // the commandOpen mirror intact so the `?`-suppression guard (260608-6fw) works.
  return (
    <Command.Dialog
      open={open}
      onOpenChange={setOpen}
      label={t("palette.label")}
      loop
      overlayClassName="fixed inset-0 bg-black/50 z-50"
      contentClassName="fixed top-[20%] left-1/2 -translate-x-1/2 z-50 w-full max-w-lg"
    >
      {/* Visually-hidden Radix title: cmdk renders these children inside its
          internal RadixDialog.Content, satisfying Radix's DialogTitle
          accessibility requirement (F1). The palette has no visible title. */}
      <Dialog.Title className="sr-only">{t("palette.label")}</Dialog.Title>
      {paletteInner}
    </Command.Dialog>
  );
}
