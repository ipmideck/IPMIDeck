"""The version history must ship inside the package and stay identical to the authored file."""

from __future__ import annotations

import pathlib
import tomllib

import pytest

from backend.core import updates

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
ROOT_CHANGELOG = REPO_ROOT / "CHANGELOG.md"
PACKAGED_CHANGELOG = REPO_ROOT / "backend" / "CHANGELOG.md"


def test_packaged_copy_matches_the_authored_file():
    """The authored file is the one at the repository root; the packaged copy is what an
    installed instance reads. If they drift, installs show a stale history — so drift fails here
    rather than silently shipping."""
    assert PACKAGED_CHANGELOG.exists(), "the packaged version history is missing"
    assert PACKAGED_CHANGELOG.read_bytes() == ROOT_CHANGELOG.read_bytes(), (
        "backend/CHANGELOG.md has drifted from the repository-root CHANGELOG.md — "
        "copy the root file over it"
    )


def test_packaged_copy_is_declared_as_package_data():
    """Without the declaration the file is present in the source tree but absent from the wheel,
    which is exactly the case nobody notices until an installed instance shows nothing."""
    with open(REPO_ROOT / "pyproject.toml", "rb") as fh:
        pyproject = tomllib.load(fh)
    declared = pyproject["tool"]["setuptools"]["package-data"]["backend"]
    assert "CHANGELOG.md" in declared


def test_read_changelog_resolves_inside_the_package():
    text = updates.read_changelog_text()
    assert text.startswith("# Changelog")
    assert updates._CHANGELOG_PATH.parent.name == "backend"


def test_oversized_history_is_refused(tmp_path):
    """A corrupt or hostile file must not decide how much memory this process allocates."""
    big = tmp_path / "CHANGELOG.md"
    big.write_text("x" * (updates._MAX_CHANGELOG_BYTES + 1), encoding="utf-8")
    assert updates.read_changelog_text(big) == ""


def test_unreadable_history_degrades_to_empty(tmp_path):
    assert updates.read_changelog_text(tmp_path / "nope.md") == ""


@pytest.mark.parametrize("entry_version", ["Unreleased", "2.0.1", "2.0.0"])
def test_every_documented_release_is_parsed(entry_version):
    versions = [e.version for e in updates.parse_changelog(updates.read_changelog_text())]
    assert entry_version in versions
