"""Every release entry in CHANGELOG.md follows one shape, so it reads the same everywhere.

The same text is the GitHub Release body and the in-app history, and an operator scans it to
decide whether to upgrade. A fixed set of groups in a fixed order, and short entries with the
headline first, keep it scannable. The rules are enforced here rather than left to review.

Releases published before the convention existed keep their original notes.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from backend.core import updates

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
CHANGELOG = REPO_ROOT / "CHANGELOG.md"

# The allowed groups, in the order they must appear. "Upgrade notes" comes first because it is
# what the operator has to act on; Security next because it decides how soon to upgrade.
SECTIONS = ("Upgrade notes", "Security", "Added", "Changed", "Fixed", "Deprecated", "Removed")

MAX_ITEMS = 8
MAX_UPGRADE_NOTES = 2
TITLE_LIMIT = {"Upgrade notes": 70}
DETAIL_LIMIT = {"Upgrade notes": 500}
DEFAULT_TITLE_LIMIT = 80
DEFAULT_DETAIL_LIMIT = 250

# Published before the convention; their notes are part of the record and are not rewritten.
LEGACY = {"2.0.0", "2.0.1"}

_BULLET = re.compile(r"^\*\*(?P<title>.+?)\*\*\s*(?P<detail>.*)$")


def _visible(text: str) -> str:
    """The text as a reader sees it: link targets and emphasis markers do not count."""
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return text.replace("**", "").replace("`", "").strip()


def _sections(body: str) -> tuple[list[tuple[str, list[str]]], list[str]]:
    """Split an entry body into (heading, bullets) pairs, and list the lines that fit neither."""
    sections: list[tuple[str, list[str]]] = []
    stray: list[str] = []
    for line in body.splitlines():
        if not line.strip():
            continue
        if line.startswith("### "):
            sections.append((line[4:].strip(), []))
        elif line.startswith("- ") and sections:
            sections[-1][1].append(line[2:].strip())
        elif line.startswith("  ") and sections and sections[-1][1]:
            sections[-1][1][-1] += " " + line.strip()
        else:
            stray.append(line)
    return sections, stray


def _entries():
    entries = updates.parse_changelog(CHANGELOG.read_text(encoding="utf-8"))
    return [e for e in entries if e.version not in LEGACY]


@pytest.mark.parametrize("entry", _entries(), ids=lambda e: e.version)
def test_release_entry_follows_the_convention(entry):
    problems: list[str] = []
    sections, stray = _sections(entry.body)

    for line in stray:
        problems.append(f"line outside a '### Group' bullet list: {line[:60]!r}")

    headings = [heading for heading, _ in sections]
    for heading in headings:
        if heading not in SECTIONS:
            problems.append(f"unknown group '### {heading}' (allowed: {', '.join(SECTIONS)})")
    known = [h for h in headings if h in SECTIONS]
    if known != sorted(set(known), key=SECTIONS.index):
        problems.append(f"groups out of order or repeated: {known} (order: {list(SECTIONS)})")

    for heading, bullets in sections:
        if not bullets:
            problems.append(f"'### {heading}' is empty — leave the group out instead")
        limit = MAX_UPGRADE_NOTES if heading == "Upgrade notes" else MAX_ITEMS
        if len(bullets) > limit:
            problems.append(f"'### {heading}' has {len(bullets)} entries (max {limit})")
        title_max = TITLE_LIMIT.get(heading, DEFAULT_TITLE_LIMIT)
        detail_max = DETAIL_LIMIT.get(heading, DEFAULT_DETAIL_LIMIT)
        for bullet in bullets:
            match = _BULLET.match(bullet)
            if not match:
                problems.append(f"entry without a bold headline: {bullet[:60]!r}")
                continue
            title, detail = _visible(match["title"]), _visible(match["detail"])
            if not title.endswith("."):
                problems.append(f"headline must end with a full stop: {title!r}")
            if len(title) > title_max:
                problems.append(f"headline is {len(title)} chars (max {title_max}): {title!r}")
            if len(detail) > detail_max:
                problems.append(
                    f"detail is {len(detail)} chars (max {detail_max}) under {title[:50]!r}"
                )

    assert not problems, f"CHANGELOG [{entry.version}]:\n  - " + "\n  - ".join(problems)


def test_the_rules_catch_a_malformed_entry():
    """The check above must actually fail on the shapes it forbids, not pass vacuously."""
    body = "\n".join(
        [
            "> ### A quoted note",
            "### Fixed",
            "- An entry with no headline.",
            "### Added",
            "### Notes",
        ]
    )
    sections, stray = _sections(body)
    assert stray == ["> ### A quoted note"]
    assert [h for h, _ in sections] == ["Fixed", "Added", "Notes"]
    assert not _BULLET.match(sections[0][1][0])
    assert _visible("**Use `x`** — see [#1](https://example.invalid/1)") == "Use x — see #1"
