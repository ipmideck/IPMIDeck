"""Import-safety lock (D-23) + deque log handler (D-01/D-25).

The single most important guarantee of backend/console.py: it imports cleanly on Linux even
though the interactive loop never runs there. An unconditional module-level ``import msvcrt``
(or unguarded ``import termios``) would crash the Linux Docker container at import — breaking even
the uvicorn-direct path that never uses the console. ``import backend.console`` succeeding is the
CI proxy for that container import.
"""

from __future__ import annotations

import logging
from collections import deque


def test_console_imports():
    """backend.console imports without a TTY / Windows-only backend and exposes port_in_use."""
    import backend.console

    assert hasattr(backend.console, "port_in_use")
    assert hasattr(backend.console, "read_key")
    assert hasattr(backend.console, "is_interactive")
    assert hasattr(backend.console, "DequeLogHandler")


def test_deque_log_handler_appends():
    """DequeLogHandler.emit appends one formatted line per record to the bounded deque."""
    from backend.console import DequeLogHandler

    log_lines: deque = deque(maxlen=10)
    handler = DequeLogHandler(log_lines)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    record = logging.LogRecord(
        name="ipmilink.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello console",
        args=(),
        exc_info=None,
    )
    handler.emit(record)
    assert len(log_lines) == 1
    assert log_lines[0] == "INFO hello console"
