import { useEffect, useMemo } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useTranslation } from "react-i18next";
import {
  AlertCircle,
  ExternalLink,
  ShieldAlert,
  Sparkles,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useUIOverlayStore } from "@/stores/ui-overlay-store";
import { useUpdateStore, type ChangelogEntry } from "@/stores/update-store";

/**
 * The version history, over whatever page the operator is on.
 *
 * It is a dialog rather than a page on purpose: reading what changed is a glance, not a
 * destination, and sending someone to a separate route to read it costs them their place.
 * Radix supplies the focus trap, the Escape handling, the scroll lock and the return of focus
 * to the trigger — none of that is re-implemented here.
 *
 * The content comes from a file inside the installed package, so this renders identically on a
 * machine that has never had a network route.
 */

/** One parsed group inside an entry body: a "### Heading" and its bullet lines. */
interface BodyGroup {
  heading: string | null;
  items: string[];
  /** Prose that is not a bullet — the 2.0.0 entry opens with a paragraph. */
  paragraphs: string[];
}

/**
 * Split an entry body into its groups. The changelog is written in one consistent shape
 * ("### Group" then "- item"), so a handful of line rules cover it — which is why there is no
 * markdown dependency here, and no raw HTML anywhere near operator-visible text.
 */
function parseBody(body: string): BodyGroup[] {
  const groups: BodyGroup[] = [];
  let current: BodyGroup = { heading: null, items: [], paragraphs: [] };
  let buffer = "";

  const flushParagraph = () => {
    const text = buffer.trim();
    if (text) current.paragraphs.push(text);
    buffer = "";
  };
  const flushGroup = () => {
    flushParagraph();
    if (current.heading || current.items.length || current.paragraphs.length) {
      groups.push(current);
    }
    current = { heading: null, items: [], paragraphs: [] };
  };

  for (const rawLine of body.split("\n")) {
    const line = rawLine.trimEnd();
    const heading = line.match(/^#{3,}\s+(.*)$/);
    if (heading) {
      flushGroup();
      current.heading = heading[1].trim();
      continue;
    }
    const bullet = line.match(/^\s*[-*]\s+(.*)$/);
    if (bullet) {
      flushParagraph();
      current.items.push(bullet[1].trim());
      continue;
    }
    if (!line.trim()) {
      flushParagraph();
      continue;
    }
    // A continuation of the previous bullet keeps its indentation.
    if (/^\s{2,}\S/.test(rawLine) && current.items.length) {
      current.items[current.items.length - 1] += ` ${line.trim()}`;
      continue;
    }
    buffer = buffer ? `${buffer} ${line.trim()}` : line.trim();
  }
  flushGroup();
  return groups;
}

/** Strip the emphasis markers the changelog uses, since there is no markdown renderer here. */
function plain(text: string): string {
  return text.replace(/\*\*(.+?)\*\*/g, "$1").replace(/`([^`]+)`/g, "$1");
}

function EntryCard({ entry, isCurrent }: { entry: ChangelogEntry; isCurrent: boolean }) {
  const { t } = useTranslation();
  const groups = useMemo(() => parseBody(entry.body), [entry.body]);

  return (
    <article
      className="border-t border-border/60 py-5 first:border-t-0 first:pt-0"
      aria-labelledby={`changelog-entry-${entry.version}`}
    >
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <h3
          id={`changelog-entry-${entry.version}`}
          className="font-mono text-sm font-semibold text-foreground"
        >
          {entry.is_unreleased ? t("updates.unreleased") : entry.version}
        </h3>
        {entry.date && (
          <span className="text-xs text-muted-foreground">{entry.date}</span>
        )}
        {isCurrent && (
          <span className="rounded-full border border-border bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
            {t("updates.installed")}
          </span>
        )}
        {/* A security release reads as one without colour: badge word + glyph + token. */}
        {entry.is_security && (
          <span className="inline-flex items-center gap-1 rounded-full border border-danger/40 bg-danger/10 px-2 py-0.5 text-[11px] font-medium text-danger">
            <ShieldAlert className="h-3 w-3" aria-hidden="true" />
            {t("updates.securityRelease")}
          </span>
        )}
      </header>

      <div className="mt-3 space-y-4">
        {groups.map((group, gi) => (
          <div key={gi}>
            {group.heading && (
              <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {group.heading}
              </h4>
            )}
            {group.paragraphs.map((para, pi) => (
              <p key={pi} className="mt-2 text-sm leading-relaxed text-muted-foreground">
                {plain(para)}
              </p>
            ))}
            {group.items.length > 0 && (
              <ul className="mt-2 space-y-1.5">
                {group.items.map((item, ii) => (
                  <li
                    key={ii}
                    className="flex gap-2 text-sm leading-relaxed text-muted-foreground"
                  >
                    <span aria-hidden="true" className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-muted-foreground/60" />
                    <span>{plain(item)}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
    </article>
  );
}

export function ChangelogDialog() {
  const { t } = useTranslation();
  const open = useUIOverlayStore((s) => s.changelogOpen);
  const setOpen = useUIOverlayStore((s) => s.setChangelogOpen);

  const entries = useUpdateStore((s) => s.entries);
  const loaded = useUpdateStore((s) => s.changelogLoaded);
  const loading = useUpdateStore((s) => s.changelogLoading);
  const failed = useUpdateStore((s) => s.changelogError);
  const releasesUrl = useUpdateStore((s) => s.releasesUrl);
  const loadChangelog = useUpdateStore((s) => s.loadChangelog);
  const state = useUpdateStore((s) => s.state);

  // Fetched on first open rather than at app boot: the history is only ever read here, and a
  // request nobody asked for is a request that did not need to happen.
  useEffect(() => {
    if (open && !loaded && !loading) void loadChangelog();
  }, [open, loaded, loading, loadChangelog]);

  const currentVersion = state?.current_version ?? null;
  const showUpdateStrip = Boolean(state?.update_available && state?.latest_version);

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/50" />
        <Dialog.Content
          className={cn(
            "fixed z-50 flex flex-col overflow-hidden border border-border bg-popover text-popover-foreground shadow-2xl",
            // Below sm: a full-height sheet, because a centred box on a phone wastes the screen
            // and puts the close control somewhere awkward.
            "inset-x-0 bottom-0 top-0 rounded-none",
            "sm:inset-auto sm:left-1/2 sm:top-1/2 sm:h-auto sm:max-h-[85vh] sm:w-[min(40rem,calc(100vw-2rem))] sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-xl",
          )}
        >
          <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
            <div className="min-w-0">
              <Dialog.Title className="text-base font-semibold">
                {t("updates.changelogTitle")}
              </Dialog.Title>
              <Dialog.Description className="mt-0.5 text-xs text-muted-foreground">
                {currentVersion
                  ? t("updates.changelogSubtitleWithVersion", { version: currentVersion })
                  : t("updates.changelogSubtitle")}
              </Dialog.Description>
            </div>
            <Dialog.Close
              className="shrink-0 rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              aria-label={t("common.close")}
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </Dialog.Close>
          </div>

          {/* A newer version, when there is one. Absent otherwise — nothing is shown to an
              operator who is already up to date. */}
          {showUpdateStrip && (
            <div
              className={cn(
                "flex items-start gap-2.5 border-b px-5 py-3 text-sm",
                state?.is_security
                  ? "border-danger/30 bg-danger/10 text-danger"
                  : "border-border bg-muted/50 text-foreground",
              )}
              role="status"
            >
              {state?.is_security ? (
                <ShieldAlert className="mt-px h-4 w-4 shrink-0" aria-hidden="true" />
              ) : (
                <Sparkles className="mt-px h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
              )}
              <div className="min-w-0 flex-1">
                <p className="font-medium">
                  {state?.is_security
                    ? t("updates.securityUpdateAvailable", { version: state?.latest_version })
                    : t("updates.updateAvailable", { version: state?.latest_version })}
                </p>
                <a
                  href={state?.release_url || releasesUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-0.5 inline-flex items-center gap-1 text-xs underline underline-offset-2 hover:no-underline"
                >
                  {t("updates.viewRelease")}
                  <ExternalLink className="h-3 w-3" aria-hidden="true" />
                </a>
              </div>
            </div>
          )}

          {/* tabIndex makes the list reachable by keyboard alone, so someone who cannot use a
              pointer can still scroll a long history. */}
          <div
            className="min-h-0 flex-1 overflow-y-auto px-5 py-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
            tabIndex={0}
            role="region"
            aria-label={t("updates.changelogTitle")}
            aria-busy={loading}
          >
            {loading && (
              <div className="space-y-4" aria-hidden="true">
                {[0, 1, 2].map((i) => (
                  <div key={i} className="space-y-2">
                    <div className="h-4 w-24 rounded bg-muted" />
                    <div className="h-3 w-full rounded bg-muted/70" />
                    <div className="h-3 w-4/5 rounded bg-muted/70" />
                  </div>
                ))}
              </div>
            )}
            {loading && <p className="sr-only">{t("common.loading")}</p>}

            {!loading && failed && (
              <div
                role="alert"
                className="flex items-start gap-2 rounded-lg border border-danger/30 bg-danger/10 px-3 py-2.5 text-sm text-danger"
              >
                <AlertCircle className="mt-px h-4 w-4 shrink-0" aria-hidden="true" />
                <div className="min-w-0">
                  <p>{t("updates.changelogError")}</p>
                  <button
                    type="button"
                    onClick={() => void loadChangelog()}
                    className="mt-1.5 rounded-md border border-danger/40 px-2 py-1 text-xs font-medium transition-colors hover:bg-danger/15"
                  >
                    {t("common.retry")}
                  </button>
                </div>
              </div>
            )}

            {!loading && !failed && entries.length === 0 && loaded && (
              <div className="py-8 text-center">
                <p className="text-sm text-muted-foreground">{t("updates.changelogEmpty")}</p>
                <a
                  href={releasesUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-2 inline-flex items-center gap-1 text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground"
                >
                  {t("updates.viewAllReleases")}
                  <ExternalLink className="h-3 w-3" aria-hidden="true" />
                </a>
              </div>
            )}

            {!loading &&
              !failed &&
              entries.map((entry) => (
                <EntryCard
                  key={entry.version}
                  entry={entry}
                  isCurrent={!entry.is_unreleased && entry.version === currentVersion}
                />
              ))}
          </div>

          <div className="flex items-center justify-between gap-3 border-t border-border px-5 py-3">
            <a
              href={releasesUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground"
            >
              {t("updates.viewAllReleases")}
              <ExternalLink className="h-3 w-3" aria-hidden="true" />
            </a>
            <Dialog.Close className="rounded-md border border-border px-3 py-1.5 text-sm font-medium min-h-[--control-min] md:min-h-8 hover:bg-muted">
              {t("common.close")}
            </Dialog.Close>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
