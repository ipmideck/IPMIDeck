"""Runtime logging helpers (D-04/D-11/D-25).

The verbosity toggle CANNOT re-call logging.basicConfig — without force=True it is a
no-op once the root logger has handlers (RESEARCH Pitfall 2). apply_log_level() sets the
root logger AND every attached handler's level so the change takes effect immediately for
the rest of the session. Persisting the choice (config writeback) is the caller's job;
IPMIDECK_LOGGING_LEVEL still wins on the NEXT boot (env precedence untouched here).

VERBOSITY CONTRACT (D-04 — authoritative): the default/quiet level is INFO. "Quiet but no
spam" is achieved by suppress_noisy_loggers() (e.g. uvicorn.access -> WARNING) at the INFO
baseline, NOT by raising the root to WARNING. The toggle cycle is INFO -> DEBUG -> WARNING.
"""

from __future__ import annotations

import logging

# D-11 verbosity cycle. D-04: the DEFAULT/quiet level is INFO (first entry). The toggle
# cycles INFO -> DEBUG (more) -> WARNING (less) -> back to INFO.
LEVEL_CYCLE = ["INFO", "DEBUG", "WARNING"]

# Loggers whose INFO output is noise; tamed at the INFO baseline so "quiet == INFO with
# selected noisy loggers suppressed" (D-04). The Windows proactor ConnectionReset spam is
# handled separately by the monkeypatch in main.py (D-18); this covers stdlib/uvicorn noise.
_NOISY_LOGGERS = {
    "uvicorn.access": logging.WARNING,
}


def apply_log_level(level_name: str) -> int:
    """Set the root logger + all handlers to ``level_name``. Returns the numeric level."""
    level = getattr(logging, level_name.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)
    for h in root.handlers:
        h.setLevel(level)
    return level


def suppress_noisy_loggers() -> None:
    """Raise the level of known-noisy loggers so the INFO default stays clean (D-04).

    Idempotent — safe to call on every lifespan startup/restart.
    """
    for name, lvl in _NOISY_LOGGERS.items():
        logging.getLogger(name).setLevel(lvl)


def next_level(current: str) -> str:
    """Return the next level in the D-11 cycle (wraps)."""
    cur = current.upper()
    try:
        i = LEVEL_CYCLE.index(cur)
    except ValueError:
        i = 0  # unknown -> treat as the start of the cycle (INFO), next is DEBUG
    return LEVEL_CYCLE[(i + 1) % len(LEVEL_CYCLE)]
