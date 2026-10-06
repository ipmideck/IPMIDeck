"""Every backend error message exists, non-empty and translated, in every supported language.

`t()` silently falls back to English, so a missing translation would never surface at runtime:
the user would just read English. This is the backend half of scripts/check-i18n-parity.mjs.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from backend.core.i18n import DEFAULT, MESSAGES, SUPPORTED

_PLACEHOLDER = re.compile(r"\{(\w*)\}")
_LANGUAGES_TS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "i18n" / "languages.ts"


def test_supported_matches_frontend_languages():
    codes = re.findall(r'\bcode:\s*"([^"]+)"', _LANGUAGES_TS.read_text(encoding="utf-8"))
    assert sorted(SUPPORTED) == sorted(codes)


@pytest.mark.parametrize("code", sorted(MESSAGES))
def test_message_in_every_language(code):
    entry = MESSAGES[code]
    missing = set(SUPPORTED) - set(entry)
    extra = set(entry) - set(SUPPORTED)
    assert not missing and not extra, f"{code}: missing={sorted(missing)} extra={sorted(extra)}"

    en = entry[DEFAULT]
    for lang, text in entry.items():
        assert text.strip(), f"{code}: empty {lang} text"
        assert set(_PLACEHOLDER.findall(text)) == set(_PLACEHOLDER.findall(en)), (
            f"{code}: {lang} placeholders differ from {DEFAULT}"
        )
        if lang != DEFAULT and " " in en.strip():
            assert text != en, f"{code}: {lang} is still the English text"
