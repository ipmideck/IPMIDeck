"""Guard against the shared application object accumulating routes across the suite.

Entering the lifespan re-mounts the module routes and the single-page-app fallback, and neither
is removed on exit, so every boot in a session leaves entries behind. Past a few hundred, request
handling recurses past the interpreter's limit and unrelated tests start erroring at fixture
setup — a failure that names none of the code responsible. This test names it.

It is a ceiling, not a target: the pre-existing accumulation is not fixed here, it is bounded so
that adding boots to the suite fails loudly instead of pushing a later test off a cliff.
"""

from __future__ import annotations

import sys

import backend.main as bm

# The recursion limit is the real constraint; each mounted route costs a frame during matching.
# A third of the default limit leaves generous headroom for the rest of the call stack.
_ROUTE_CEILING = sys.getrecursionlimit() // 3


def test_the_application_has_not_accumulated_routes_past_a_safe_ceiling():
    count = len(bm.app.router.routes)
    assert count < _ROUTE_CEILING, (
        f"the shared application object carries {count} routes (ceiling {_ROUTE_CEILING}). "
        "Each test that enters the lifespan leaves routes behind; boot once per configuration "
        "and reuse it rather than booting per test."
    )
