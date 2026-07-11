"""Single source of truth for product brand strings (D-09/D-10).

Phase 04.2 renames the whole product by flipping APP_NAME here. Do NOT hand-draw
the literal name anywhere — the banner is GENERATED from APP_NAME.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

APP_NAME = "IPMIDeck"  # 04.2 flips this single line

# The ONE human-edited version literal (D-01/D-03). PEP 440 canonical form "2.0.0" (the first
# stable public release): tag == dist == METADATA == this literal, zero per-surface normalization
# surprises. pyproject derives the wheel version from THIS via attr: (D-05).
# Bump this + tag the same commit to cut a release (firing the tag is a USER action, D-21).
_VERSION_FALLBACK = "2.0.0"

# Runtime resolution (D-02): an installed dist (pip/Docker) reports what was ACTUALLY shipped;
# a raw source checkout (`python -m backend.main`) falls back to the literal. The dist name
# "ipmideck" is pyproject [project].name (D-07) — if that ever changes, change it here too.
try:
    VERSION = version("ipmideck")
except PackageNotFoundError:
    VERSION = _VERSION_FALLBACK

AUTHOR = "Luigi Tanzillo"
LICENSE = "Apache-2.0"
URL = "https://github.com/dev-luigi/IPMI-FanPilot"


def banner(compact: bool = False) -> str:
    """Return figlet ASCII art generated from APP_NAME. Lazy-imports pyfiglet so the
    module stays import-cheap, but pyfiglet is a DECLARED dependency (pyproject) and MUST
    be importable in normal/Docker envs. A missing pyfiglet is BROKEN PACKAGING, not a
    degrade path — let ImportError propagate (REVIEWS MED: pyfiglet-fails-loud). The only
    sanctioned runtime-degrade is render_banner_safe() below, tested separately.

    The full (non-compact) splash uses the "ansi_shadow" font — the big block banner the
    operator sees once at launch (matches the GSD-style splash). Its glyphs are Unicode box-
    drawing/block chars (█ ╗ ═ ║ …), so any caller that PRINTS this to a piped/cp1252 Windows
    stdout MUST emit it Unicode-safely (see backend.main.print_banner_safe) — a bare print()
    would raise UnicodeEncodeError under a cp1252-encoded stream. The compact variant keeps a
    small ASCII figlet; it is only a fallback now that the pinned header uses brand_title()."""
    from pyfiglet import Figlet  # declared dep — propagate ImportError (fail loud)

    fig = Figlet(font="small" if compact else "ansi_shadow")
    return fig.renderText(APP_NAME).rstrip("\n")


def render_banner_safe(compact: bool = False) -> str:
    """Explicit, separately-tested runtime degrade: banner() but falling back to the bare
    APP_NAME if pyfiglet is genuinely unavailable. Normal code calls banner() so a packaging
    mistake surfaces loudly; only paths that must never crash on a broken install use this."""
    try:
        return banner(compact=compact)
    except ImportError:
        return APP_NAME


def brand_title(compact: bool = False) -> str:
    """Return a SINGLE-LINE brand string generated from the constants (no figlet, no newlines).

    Used by the pinned header (D-01/D-02 "splash grande poi compatto"): the multi-line figlet
    banner() is the one-time launch splash, while the always-visible compact header uses this
    one-liner so the help bar / status / credits below it are never clipped. Generated from
    APP_NAME/VERSION so the 04.2 rename still flips everything from the one brand constant.
    """
    if compact:
        return f"{APP_NAME} v{VERSION}"
    return f"{APP_NAME} · v{VERSION}"


def credits_line() -> str:
    """One-line credit string for the splash/banner (D-10)."""
    return f"{AUTHOR} · v{VERSION} · {LICENSE} · {URL}"
