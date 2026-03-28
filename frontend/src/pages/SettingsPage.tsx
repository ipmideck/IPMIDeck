import { Header } from "@/components/layout/Header";
import { ExternalLink, Heart, Code2 } from "lucide-react";

export default function SettingsPage() {
  return (
    <>
      <Header title="Settings" />
      <div className="flex-1 overflow-auto p-6">
        <div className="mx-auto max-w-2xl space-y-6">
          {/* Placeholder for settings sections */}
          <div className="rounded-lg border border-border bg-card p-6">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
              Servers
            </h2>
            <p className="mt-2 text-sm text-muted-foreground">
              Manage your BMC server connections. Add, edit, or remove servers.
            </p>
          </div>

          <div className="rounded-lg border border-border bg-card p-6">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
              Authentication
            </h2>
            <p className="mt-2 text-sm text-muted-foreground">
              Configure local authentication. Enable or disable login requirement.
            </p>
          </div>

          <div className="rounded-lg border border-border bg-card p-6">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
              Appearance
            </h2>
            <p className="mt-2 text-sm text-muted-foreground">
              Toggle between dark and light mode.
            </p>
          </div>

          {/* About section */}
          <div className="rounded-lg border border-border bg-card p-6">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
              About IPMILink
            </h2>
            <div className="mt-4 space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">Version</span>
                <span className="font-mono text-sm">2.0.0-alpha.1</span>
              </div>
              <div className="border-t border-border" />
              <div className="flex items-start gap-4 pt-1">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-muted font-semibold">
                  LT
                </div>
                <div className="min-w-0">
                  <p className="text-sm font-medium">Luigi Tanzillo</p>
                  <p className="text-xs text-muted-foreground">
                    Creator &amp; Developer
                  </p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <a
                      href="https://github.com/dev-luigi"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                    >
                      <Code2 className="h-3 w-3" />
                      dev-luigi
                      <ExternalLink className="h-2.5 w-2.5" />
                    </a>
                  </div>
                </div>
              </div>
              <div className="border-t border-border" />
              <p className="flex items-center gap-1 text-xs text-muted-foreground">
                Made with <Heart className="h-3 w-3 text-red-500" /> for the homelab community
              </p>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
