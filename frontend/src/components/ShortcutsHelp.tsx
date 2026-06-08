import { Command } from "cmdk";
import * as Dialog from "@radix-ui/react-dialog";
import { useTranslation } from "react-i18next";
import { useUIOverlayStore } from "@/stores/ui-overlay-store";

// Read-only keyboard-shortcuts reference. Opened with "?" (handled in
// useKeyboardShortcuts), bound to ui-overlay-store.helpOpen. Reuses the cmdk
// Command.Dialog shell from CommandPalette for visual consistency (D-06).

const groupHeadingClass =
  "[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-muted-foreground";

const rowClass = "flex items-center gap-3 rounded-md px-2 py-2 text-sm";

const kbdClass =
  "ml-auto rounded border border-border bg-muted px-1.5 py-0.5 font-mono text-xs";

export function ShortcutsHelp() {
  const { t } = useTranslation();
  const open = useUIOverlayStore((s) => s.helpOpen);
  const setHelpOpen = useUIOverlayStore((s) => s.setHelpOpen);

  return (
    <Command.Dialog
      open={open}
      onOpenChange={setHelpOpen}
      label={t("shortcuts.title")}
      overlayClassName="fixed inset-0 bg-black/50 z-50"
      contentClassName="fixed top-[20%] left-1/2 -translate-x-1/2 z-50 w-full max-w-lg"
    >
      {/* Visually-hidden Radix title: cmdk renders these children inside its
          internal RadixDialog.Content, so this satisfies Radix's DialogTitle
          accessibility requirement (F1). The visible heading below stays. */}
      <Dialog.Title className="sr-only">{t("shortcuts.title")}</Dialog.Title>
      <div className="rounded-xl border border-border bg-popover text-popover-foreground shadow-2xl overflow-hidden">
        <div className="border-b border-border px-4 py-3 text-sm font-medium">
          {t("shortcuts.title")}
        </div>
        <Command.List className="max-h-80 overflow-y-auto p-2">
          {/* Navigation */}
          <Command.Group heading={t("shortcuts.groupNavigation")} className={groupHeadingClass}>
            <div className={rowClass}>
              <span>{t("nav.dashboard")}</span>
              <kbd className={kbdClass}>D</kbd>
            </div>
            <div className={rowClass}>
              <span>{t("nav.fanpilot")}</span>
              <kbd className={kbdClass}>F</kbd>
            </div>
            <div className={rowClass}>
              <span>{t("nav.sel")}</span>
              <kbd className={kbdClass}>E</kbd>
            </div>
            <div className={rowClass}>
              <span>{t("nav.fru")}</span>
              <kbd className={kbdClass}>H</kbd>
            </div>
            <div className={rowClass}>
              <span>{t("nav.modules")}</span>
              <kbd className={kbdClass}>M</kbd>
            </div>
          </Command.Group>

          {/* Servers */}
          <Command.Group heading={t("shortcuts.groupServers")} className={groupHeadingClass}>
            <div className={rowClass}>
              <span>{t("shortcuts.switchServer")}</span>
              <kbd className={kbdClass}>1–9</kbd>
            </div>
          </Command.Group>

          {/* Help */}
          <Command.Group heading={t("shortcuts.groupHelp")} className={groupHeadingClass}>
            <div className={rowClass}>
              <span>{t("shortcuts.showHelp")}</span>
              <kbd className={kbdClass}>?</kbd>
            </div>
            <div className={rowClass}>
              <span>{t("shortcuts.commandPalette")}</span>
              <kbd className={kbdClass}>⌘/Ctrl + K</kbd>
            </div>
          </Command.Group>
        </Command.List>
      </div>
    </Command.Dialog>
  );
}
