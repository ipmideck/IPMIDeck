"""What the operator is told about how often IPMIDeck checks has to be what the server does.

The README and the setup question are read before anyone agrees to the check, so each number
they give is pinned to the constant that implements it: changing the cadence without changing
the words fails here. The setup question stays one line and names only the daily cadence. The changelog entry is kept short by its own convention and leaves the
numbers to the README.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


from backend.core import update_service as svc

ROOT = Path(__file__).resolve().parents[2]


def _flat(name: str) -> str:
    return re.sub(r"\s+", " ", (ROOT / name).read_text(encoding="utf-8"))


def test_the_readme_states_the_cadence_the_service_keeps():
    text = _flat("README.md")
    first_retry = svc._BACKOFF_START_SECONDS // 60
    ceiling = svc._BACKOFF_CEILING_SECONDS // 3600
    assert re.search(
        rf"retried after {first_retry} minutes[^.]*doubles[^.]*up to {ceiling} hours", text
    )
    assert svc._SECURITY_RETRY_SECONDS == 3600
    assert re.search(
        rf"the whole check[^.]*every hour, at most {svc._SECURITY_RETRY_LIMIT} times[^.]*once a day",
        text,
    )
    assert svc.CHECK_INTERVAL_SECONDS == 24 * 3600
    assert "stable release is never offered a pre-release" in text
    assert "again after an hour" not in text


def test_the_setup_question_states_the_cadence_in_one_line():
    """The wizard keeps it to a line; the retry details live in the README, pinned above."""
    catalog = json.loads(
        (ROOT / "frontend/src/i18n/locales/en/translation.json").read_text(encoding="utf-8")
    )
    hint = catalog["setup"]["auth"]["updateChecksHint"]
    assert svc.CHECK_INTERVAL_SECONDS == 24 * 3600
    assert "once a day" in hint.lower()
    assert len(hint) <= 70
