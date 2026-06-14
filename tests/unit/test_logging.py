"""Runtime logging-helper tests (D-04/D-11/D-25).

Covers backend.core.logging_util:
- apply_log_level() sets the root logger AND every attached handler (the basicConfig-no-op
  trap is avoided — RESEARCH Pitfall 2 / D-25), and falls back to INFO on an unknown name.
- LEVEL_CYCLE's default/quiet level is INFO (D-04 — NOT WARNING) and next_level() cycles
  INFO -> DEBUG -> WARNING -> INFO (D-11).
- suppress_noisy_loggers() tames uvicorn.access to WARNING at the INFO baseline (idempotent).

Each test restores the root logger level + handlers it touched so the suite stays isolated.
"""

from __future__ import annotations

import logging

from backend.core.logging_util import (
    LEVEL_CYCLE,
    apply_log_level,
    next_level,
    suppress_noisy_loggers,
)


def test_apply_log_level_sets_root_and_handlers():
    """apply_log_level updates the root logger AND each attached handler's level."""
    root = logging.getLogger()
    prev_root_level = root.level
    handler = logging.StreamHandler()
    handler.setLevel(logging.CRITICAL)
    root.addHandler(handler)
    try:
        ret = apply_log_level("DEBUG")
        assert ret == logging.DEBUG
        assert root.level == logging.DEBUG
        assert handler.level == logging.DEBUG
    finally:
        root.removeHandler(handler)
        root.setLevel(prev_root_level)


def test_apply_log_level_unknown_falls_back_to_info():
    """An unknown level name falls back to INFO (no crash)."""
    root = logging.getLogger()
    prev = root.level
    try:
        ret = apply_log_level("bogus")
        assert ret == logging.INFO
        assert root.level == logging.INFO
    finally:
        root.setLevel(prev)


def test_level_cycle_default_is_info():
    """D-04: the default/quiet level is INFO — the first cycle entry."""
    assert LEVEL_CYCLE[0] == "INFO"


def test_next_level_cycles():
    """D-11 cycle: INFO -> DEBUG -> WARNING -> INFO; unknown starts at INFO (next DEBUG)."""
    assert next_level("INFO") == "DEBUG"
    assert next_level("DEBUG") == "WARNING"
    assert next_level("WARNING") == "INFO"
    assert next_level("bogus") == "DEBUG"


def test_suppress_noisy_loggers_sets_uvicorn_access_warning():
    """suppress_noisy_loggers raises uvicorn.access to WARNING and is idempotent."""
    access = logging.getLogger("uvicorn.access")
    prev = access.level
    try:
        suppress_noisy_loggers()
        assert access.level == logging.WARNING
        suppress_noisy_loggers()  # second call must not change the result
        assert access.level == logging.WARNING
    finally:
        access.setLevel(prev)
