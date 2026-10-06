import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, Copy } from "lucide-react";

/**
 * A command to run on the machine hosting IPMIDeck, selectable and with a copy button. The copy
 * can fail (the clipboard needs a secure context, and a LAN address over plain http is not one),
 * so the text itself stays selectable in one click.
 */
export function CommandLine({ command }: { command: string }) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(timer);
  }, [copied]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
    } catch {
      // Clipboard denied (plain http on a LAN address): the command stays selectable.
    }
  };

  return (
    <div className="mt-2 flex items-center gap-1 rounded-md border border-border bg-background/60 py-1 pl-3 pr-1">
      <code className="min-w-0 flex-1 select-all break-all font-mono text-xs text-foreground">
        {command}
      </code>
      <button
        type="button"
        onClick={copy}
        className="shrink-0 rounded p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        aria-label={copied ? t("banner.ipmitoolCopied") : t("banner.ipmitoolCopy")}
        title={copied ? t("banner.ipmitoolCopied") : t("banner.ipmitoolCopy")}
      >
        {copied ? (
          <Check className="h-3.5 w-3.5 text-success" aria-hidden="true" />
        ) : (
          <Copy className="h-3.5 w-3.5" aria-hidden="true" />
        )}
      </button>
    </div>
  );
}
