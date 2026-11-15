"""Helpers shared by the CSV/JSON export endpoints."""

from __future__ import annotations

import re

# Characters a spreadsheet treats as the start of a formula rather than as text. A cell
# beginning with one of these is evaluated when the file is opened, and exported cells carry
# values reported by the BMC, so a crafted sensor name or event description would otherwise
# run inside the reader's spreadsheet.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

# A filename is echoed into the Content-Disposition header inside double quotes. Anything
# outside this set — a quote, a newline, a semicolon — would let the value break out of the
# quoted string and steer the header, so it is replaced rather than escaped.
_FILENAME_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]")


def csv_safe(value: object) -> object:
    """Neutralise a value that a spreadsheet would otherwise evaluate as a formula.

    The leading apostrophe is the conventional "treat the cell as text" marker and is
    stripped by the spreadsheet on display, so the exported data still reads correctly.
    Non-strings are returned untouched — a number cannot start a formula.
    """
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def safe_filename_part(value: str) -> str:
    """Reduce a value to characters that cannot alter the Content-Disposition header."""
    cleaned = _FILENAME_SAFE_RE.sub("_", value)[:64]
    return cleaned or "export"
