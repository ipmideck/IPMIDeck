import { useMemo, type ReactNode } from "react";
import { TriangleAlert } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Release notes as the changelog writes them, rendered without a markdown dependency and with
 * no raw HTML anywhere near operator-visible text. Shared by the version history and the update
 * dialog, so a release reads the same in both.
 */

/** A run of prose, or a fenced code sample kept line for line. */
interface BodyBlock {
  text: string;
  code: boolean;
}

/** One parsed group inside an entry body: a "### Heading" and its bullet lines. */
interface BodyGroup {
  heading: string | null;
  items: string[];
  /** Prose that is not a bullet — the 2.0.0 entry opens with a paragraph. */
  paragraphs: BodyBlock[];
  /** Written as a "> " blockquote: an upgrade note the operator has to act on. */
  callout: boolean;
}

const emptyGroup = (callout = false): BodyGroup => ({
  heading: null,
  items: [],
  paragraphs: [],
  callout,
});

/**
 * Split an entry body into its groups. The changelog is written in one consistent shape
 * ("### Group" then "- item", plus "> " upgrade notes), so a handful of line rules cover it —
 * which is why there is no markdown dependency here, and no raw HTML anywhere near
 * operator-visible text.
 */
export function parseBody(body: string): BodyGroup[] {
  const groups: BodyGroup[] = [];
  let current = emptyGroup();
  let buffer = "";
  let code: string[] | null = null;
  // Set while the current group came from a "> " quote, which ends where the quote does.
  let inQuote = false;

  const flushParagraph = () => {
    const text = buffer.trim();
    if (text) current.paragraphs.push({ text, code: false });
    buffer = "";
  };
  const flushGroup = (callout = false) => {
    flushParagraph();
    if (current.heading || current.items.length || current.paragraphs.length) {
      groups.push(current);
    }
    current = emptyGroup(callout);
    inQuote = callout;
  };

  for (const sourceLine of body.split("\n")) {
    const quoted = sourceLine.match(/^\s*>\s?(.*)$/);
    const rawLine = quoted ? quoted[1] : sourceLine;
    const line = rawLine.trimEnd();

    if (/^\s*```/.test(line)) {
      if (code) {
        current.paragraphs.push({ text: code.join("\n"), code: true });
        code = null;
      } else {
        flushParagraph();
        code = [];
      }
      continue;
    }
    if (code) {
      code.push(line);
      continue;
    }

    // Leaving a quote ends the note, so the prose after it is not drawn inside the box.
    if (inQuote && !quoted && line.trim()) flushGroup();

    const heading = line.match(/^#{3,}\s+(.*)$/);
    if (heading) {
      flushGroup(Boolean(quoted));
      current.heading = heading[1].trim();
      // The changelog's own group for what an operator must do when upgrading.
      if (/^upgrade notes$/i.test(current.heading)) current.callout = true;
      continue;
    }
    if (quoted && !current.callout) flushGroup(true);

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
    if (/^\s{2,}\S/.test(rawLine) && current.items.length && !buffer) {
      current.items[current.items.length - 1] += ` ${line.trim()}`;
      continue;
    }
    buffer = buffer ? `${buffer} ${line.trim()}` : line.trim();
  }
  if (code) current.paragraphs.push({ text: code.join("\n"), code: true });
  flushGroup();
  return groups;
}

/**
 * The inline markup the changelog uses — **bold**, `code` and [links](url) — as React nodes.
 * Links keep only their text: the dialog is read, not navigated.
 */
function inline(text: string): ReactNode[] {
  const unlinked = text.replace(/\[([^\]]+)\]\([^)]+\)/g, "$1");
  return unlinked.split(/(\*\*.+?\*\*|`[^`]+`)/g).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      return (
        <strong key={i} className="font-semibold text-foreground">
          {part.slice(2, -2).replace(/`([^`]+)`/g, "$1")}
        </strong>
      );
    }
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
      return (
        <code key={i} className="rounded bg-muted px-1 py-px font-mono text-[0.92em] text-foreground">
          {part.slice(1, -1)}
        </code>
      );
    }
    return part;
  });
}

/** A heading as plain text: the group labels are small caps, where inline styling would be noise. */
function plainText(text: string): string {
  return text.replace(/\*\*(.+?)\*\*/g, "$1").replace(/`([^`]+)`/g, "$1");
}

function GroupBody({ group }: { group: BodyGroup }) {
  return (
    <>
      {group.paragraphs.map((block, pi) =>
        block.code ? (
          <pre
            key={pi}
            className="mt-2 overflow-x-auto rounded-md border border-border bg-background/60 px-3 py-2 font-mono text-xs leading-relaxed text-foreground"
          >
            {block.text}
          </pre>
        ) : (
          <p key={pi} className="mt-2 text-[13px] leading-relaxed text-muted-foreground">
            {inline(block.text)}
          </p>
        ),
      )}
      {group.items.length > 0 && (
        <ul className="mt-2 space-y-1.5">
          {group.items.map((item, ii) => (
            <li
              key={ii}
              className="flex gap-2 text-[13px] leading-relaxed text-muted-foreground"
            >
              <span aria-hidden="true" className="mt-[8px] h-1 w-1 shrink-0 rounded-full bg-muted-foreground/60" />
              <span className="min-w-0">{inline(item)}</span>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

export function ReleaseNotesBody({ body, className }: { body: string; className?: string }) {
  const groups = useMemo(() => parseBody(body), [body]);
  return (
    <div className={cn("space-y-4", className)}>
      {groups.map((group, gi) =>
        group.callout ? (
          // An upgrade note: boxed and marked with a glyph, so it reads as "act on this"
          // without relying on the tint alone.
          <aside
            key={gi}
            className="rounded-lg border border-warning/40 bg-warning/10 px-3.5 py-3"
          >
            {group.heading && (
              <h4 className="flex items-start gap-2 text-[13px] font-semibold text-foreground">
                <TriangleAlert className="mt-px h-3.5 w-3.5 shrink-0 text-warning" aria-hidden="true" />
                <span className="min-w-0">{inline(group.heading)}</span>
              </h4>
            )}
            <GroupBody group={group} />
          </aside>
        ) : (
          <div key={gi}>
            {group.heading && (
              <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {plainText(group.heading)}
              </h4>
            )}
            <GroupBody group={group} />
          </div>
        ),
      )}
    </div>
  );
}
