"""SEL background-loop warning names the exception type (D-18).

The reverted Quick re-applied here makes the "sel poll failed" warning log repr(e) instead of
the bare str(e) (which was blank for some exceptions). The PRIMARY check is BEHAVIORAL via
caplog: drive the real `_poll_one_server` error branch with a fake ipmi whose get_sel raises,
then assert the captured WARNING record contains the exception CLASS name. An ADDITIONAL
source-grep locks repr(e) in place as a regression guard.

No real BMC / ipmitool is involved — the IPMI call is a fake that raises immediately.

asyncio_mode="auto" (pyproject) => async tests need NO decorator.
"""

from __future__ import annotations

import logging
from pathlib import Path

from backend.modules import ModuleContext, get_ctx, set_ctx
from backend.modules.sel import tasks as sel_tasks


class _RaisingIPMI:
    """An IPMI stand-in whose get_sel raises — drives the _poll_one_server except branch."""

    async def get_sel(self, host, user, password):
        raise TimeoutError("boom")


async def test_sel_warning_names_exception_class(caplog):
    """BEHAVIORAL: a failing SEL poll logs a WARNING whose message names the exception class."""
    # Install a minimal ctx with a raising ipmi; db/ws are unused on the error path (we return
    # before touching them). Restore the previous ctx afterward so other tests are unaffected.
    try:
        prev_ctx = get_ctx()
    except Exception:
        prev_ctx = None
    set_ctx(ModuleContext(db=None, ipmi=_RaisingIPMI(), ws=None, config=None))
    try:
        with caplog.at_level(logging.WARNING, logger="ipmilink.modules.sel"):
            await sel_tasks._poll_one_server(
                {"id": "1", "host": "192.0.2.10", "username": "u", "password": "p"}
            )
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert warnings, "expected a WARNING record from the SEL poll error branch"
        rendered = warnings[-1].getMessage()
        assert "sel poll failed" in rendered
        # repr(e) puts the exception CLASS name into the message (was blank with str(e)).
        assert "TimeoutError" in rendered
    finally:
        if prev_ctx is not None:
            set_ctx(prev_ctx)


def test_sel_tasks_uses_repr_regression_lock():
    """ADDITIONAL source lock: the warning logs repr(e), not the bare str(e)."""
    src = Path("backend/modules/sel/tasks.py").read_text(encoding="utf-8")
    assert "repr(e)" in src
    # Timeout untouched — the 45s bump was reverted and is NOT D-18 noise-reduction scope.
    assert "timeout=15.0" in src
