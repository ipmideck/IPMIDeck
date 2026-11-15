"""Export sanitisation: spreadsheet formulas and Content-Disposition filenames."""

from __future__ import annotations

import pytest

from backend.core.csv_export import csv_safe, safe_filename_part


@pytest.mark.parametrize(
    "value",
    ["=1+1", "+1", "-1", "@SUM(A1)", "\tx", "\rx", '=cmd|\' /c calc\'!A1'],
)
def test_csv_safe_neutralises_formula_prefixes(value):
    """A cell a spreadsheet would evaluate is prefixed so it is read as text."""
    out = csv_safe(value)
    assert out == "'" + value
    assert not out.startswith(("=", "+", "-", "@", "\t", "\r"))


@pytest.mark.parametrize("value", ["CPU Temp", "", "12.5", "a=b"])
def test_csv_safe_leaves_ordinary_values_untouched(value):
    assert csv_safe(value) == value


def test_csv_safe_passes_non_strings_through():
    assert csv_safe(42) == 42
    assert csv_safe(None) is None


@pytest.mark.parametrize(
    "value",
    ['a"b', "a\r\nb", "a;b", "a/b", "a\\b", "a b"],
)
def test_safe_filename_part_strips_header_breaking_characters(value):
    """Nothing survives that could terminate the quoted filename or add a header."""
    out = safe_filename_part(value)
    assert all(c.isalnum() or c in "._-" for c in out), out


def test_safe_filename_part_is_never_empty():
    """An empty result would produce a nameless attachment."""
    assert safe_filename_part('"";') == "___"
    assert safe_filename_part("") == "export"


def test_safe_filename_part_is_bounded():
    assert len(safe_filename_part("a" * 500)) == 64
