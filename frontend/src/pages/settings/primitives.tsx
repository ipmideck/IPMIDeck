import { forwardRef, type ReactNode } from "react";
import { cn } from "@/lib/utils";

/** Human-readable byte size for the System/Data DB-size readout (04-W5-01). */
export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(1)} GB`;
}

interface SectionPanelProps {
  /** id used for aria-labelledby wiring + focus-move target. */
  headingId: string;
  /** Visible section title (translated). */
  title: string;
  /** Optional one-line description under the title. */
  description?: string;
  /** Optional trailing control rendered on the title row (e.g. Add server). */
  action?: ReactNode;
  children: ReactNode;
}

/**
 * Shared panel scaffold for every section: a single H1 that leads the panel and
 * receives focus on section switch (D-13 §8 — focus moves to the panel heading).
 * The heading is the labelledby target for the panel region.
 *
 * The ref lands on the <h1> so the shell can move focus to it after navigation;
 * tabIndex={-1} makes it programmatically focusable without entering the tab order.
 */
export const SectionPanel = forwardRef<HTMLHeadingElement, SectionPanelProps>(
  function SectionPanel({ headingId, title, description, action, children }, ref) {
    return (
      <section aria-labelledby={headingId} className="min-w-0">
        <div className="mb-6 flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h1
              id={headingId}
              ref={ref}
              tabIndex={-1}
              className="text-xl font-semibold tracking-tight text-foreground outline-none"
            >
              {title}
            </h1>
            {description && (
              <p className="mt-1 text-sm text-muted-foreground">{description}</p>
            )}
          </div>
          {action && <div className="shrink-0">{action}</div>}
        </div>
        {children}
      </section>
    );
  },
);

interface FieldGroupProps {
  /** Group heading (translated). */
  title: string;
  /** Optional one-line description under the group title. */
  description?: string;
  /** Optional trailing control on the group title row. */
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}

/**
 * A grouped block within a panel. Replaces the old "card per concern" stacking
 * (the brief's two-rails / nested-card risk): a panel is one surface, grouped by
 * thin-ruled blocks with breathing room, not by nested bordered cards.
 */
export function FieldGroup({ title, description, action, children, className }: FieldGroupProps) {
  return (
    <div className={cn("border-t border-border/60 py-6 first:border-t-0 first:pt-0", className)}>
      <div className="mb-4 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-foreground">{title}</h2>
          {description && (
            <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>
          )}
        </div>
        {action && <div className="shrink-0">{action}</div>}
      </div>
      {children}
    </div>
  );
}

/** Standard text input styling shared across sections (consistency). */
export const inputClass =
  "w-full rounded-md border border-border bg-background px-3 py-2 text-sm min-h-[--control-min] md:min-h-9 focus-visible:ring-2 focus-visible:ring-ring/40";

/** Primary action button styling. */
export const primaryBtnClass =
  "rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground min-h-[--control-min] md:min-h-9 disabled:cursor-not-allowed disabled:opacity-50";

/** Secondary / outline button styling. */
export const secondaryBtnClass =
  "rounded-md border border-border px-3 py-2 text-sm font-medium hover:bg-muted min-h-[--control-min] md:min-h-9 disabled:cursor-not-allowed disabled:opacity-50";
