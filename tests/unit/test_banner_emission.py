"""Unicode-safe splash-emission lock (04.1-04 ANSI Shadow banner).

The launch splash uses the ANSI Shadow figlet font, whose glyphs are Unicode block/box-drawing
chars (█ ╗ ═ ║ …). On a real interactive Windows console Python writes via WriteConsoleW so those
print fine, BUT when stdout is PIPED/redirected on Windows the stream encoding is cp1252 and a bare
``print(banner())`` raises UnicodeEncodeError. backend.main.print_banner_safe() must emit the banner
WITHOUT crashing on such a stream (re-emitting as UTF-8 bytes via the binary buffer, degrading to
plain ASCII only as a last resort). These tests reproduce the cp1252/ascii pipe and assert no raise.

These are pure-Python tests — they never launch the interactive console or any process.
"""

from __future__ import annotations

import io

import backend.main as bm
from backend.core.branding import banner


class _Cp1252TextStream:
    """A stdout stand-in that behaves like a Windows PIPED stdout: its text-level write() encodes
    through cp1252 and raises UnicodeEncodeError on chars cp1252 can't represent (the █/╗/═ glyphs),
    but it exposes a binary .buffer that accepts raw UTF-8 bytes (like sys.stdout.buffer)."""

    encoding = "cp1252"

    def __init__(self) -> None:
        self.buffer = io.BytesIO()

    def write(self, s: str) -> int:
        # Mirrors CPython's text-IO behavior on a cp1252 stream: non-representable chars blow up.
        data = s.encode("cp1252")  # raises UnicodeEncodeError on the block glyphs
        return self.buffer.write(data)

    def flush(self) -> None:  # pragma: no cover - trivial
        pass


class _AsciiNoBufferStream:
    """An ascii text stream with NO usable .buffer — forces the last-ditch plain-ASCII degrade."""

    encoding = "ascii"
    buffer = None  # print_banner_safe's buffer fast-path must fall through to the ASCII fallback

    def __init__(self) -> None:
        self.captured: list[str] = []

    def write(self, s: str) -> int:
        s.encode("ascii")  # raises UnicodeEncodeError on any non-ASCII (the block glyphs)
        self.captured.append(s)
        return len(s)

    def flush(self) -> None:  # pragma: no cover - trivial
        pass


def test_print_banner_safe_does_not_raise_under_cp1252_pipe(monkeypatch):
    """REGRESSION: emitting the ANSI Shadow banner to a cp1252-encoded/piped stdout must NOT raise.

    A bare print(banner()) raises UnicodeEncodeError here; print_banner_safe() instead re-emits the
    block art as UTF-8 bytes on the binary buffer, so the operator still sees the splash under
    `docker logs` / a redirected stream.
    """
    art = banner()  # the big ANSI Shadow block art (contains █)
    assert "█" in art  # sanity: this is genuinely the Unicode-block banner

    fake = _Cp1252TextStream()
    monkeypatch.setattr(bm.sys, "stdout", fake)

    # Must complete without raising UnicodeEncodeError.
    bm.print_banner_safe(art)

    # The bytes that landed on the binary buffer decode back to the original art (UTF-8 fallback).
    emitted = fake.buffer.getvalue().decode("utf-8")
    assert "█" in emitted
    assert art in emitted


def test_print_banner_safe_degrades_to_ascii_without_buffer(monkeypatch):
    """When even the binary buffer is unavailable, print_banner_safe degrades to plain ASCII instead
    of crashing — the process never dies merely trying to print a banner."""
    art = banner()
    fake = _AsciiNoBufferStream()
    monkeypatch.setattr(bm.sys, "stdout", fake)

    # ascii write() of the block art raises, .buffer is None -> last-ditch render_banner_safe/APP_NAME.
    # render_banner_safe() also returns block art (UnicodeEncodeError again) -> APP_NAME fallback.
    bm.print_banner_safe(art)

    joined = "".join(fake.captured)
    assert "IPMIDeck" in joined  # the plain-ASCII brand made it out, no exception escaped


def test_print_banner_safe_passes_through_on_utf8_stream(monkeypatch):
    """On a normal UTF-8 stream the fast path prints the art verbatim (no degrade)."""

    class _Utf8Stream:
        encoding = "utf-8"

        def __init__(self) -> None:
            self.text = ""

        def write(self, s: str) -> int:
            self.text += s
            return len(s)

        def flush(self) -> None:  # pragma: no cover - trivial
            pass

    art = banner()
    fake = _Utf8Stream()
    monkeypatch.setattr(bm.sys, "stdout", fake)

    bm.print_banner_safe(art)
    assert art in fake.text  # verbatim, including the block glyphs
