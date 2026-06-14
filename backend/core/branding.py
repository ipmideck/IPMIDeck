"""Single source of truth for product brand strings (D-09/D-10).

Phase 04.2 renames the whole product by flipping APP_NAME here. Do NOT hand-draw
the literal name anywhere — the banner is GENERATED from APP_NAME.
"""

from __future__ import annotations

APP_NAME = "IPMILink"  # 04.2 flips this single line
VERSION = "2.0.0-alpha.1"
AUTHOR = "Luigi Tanzillo"
LICENSE = "ISC"
URL = "https://github.com/dev-luigi/IPMI-FanPilot"


def banner(compact: bool = False) -> str:
    """Return figlet ASCII art generated from APP_NAME. Lazy-imports pyfiglet so the
    module stays import-cheap, but pyfiglet is a DECLARED dependency (pyproject) and MUST
    be importable in normal/Docker envs. A missing pyfiglet is BROKEN PACKAGING, not a
    degrade path — let ImportError propagate (REVIEWS MED: pyfiglet-fails-loud). The only
    sanctioned runtime-degrade is render_banner_safe() below, tested separately."""
    from pyfiglet import Figlet  # declared dep — propagate ImportError (fail loud)

    fig = Figlet(font="small" if compact else "standard")
    return fig.renderText(APP_NAME).rstrip("\n")


def render_banner_safe(compact: bool = False) -> str:
    """Explicit, separately-tested runtime degrade: banner() but falling back to the bare
    APP_NAME if pyfiglet is genuinely unavailable. Normal code calls banner() so a packaging
    mistake surfaces loudly; only paths that must never crash on a broken install use this."""
    try:
        return banner(compact=compact)
    except ImportError:
        return APP_NAME


def credits_line() -> str:
    """One-line credit string for the splash/banner (D-10)."""
    return f"{AUTHOR} · v{VERSION} · {LICENSE} · {URL}"
