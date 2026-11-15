"""The stale-translation gate, run for real against a throwaway git repository.

What is pinned: a commit whose subject carries [i18n-skip] exempts only the en strings that
commit changed, so an untranslated string pushed alongside it still fails; the check names what
it exempted; and the range is measured from the merge base, so a base branch that moved on does
not show its own changes as untranslated ones.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

NODE = shutil.which("node")
GIT = shutil.which("git")
SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check-i18n-stale.mjs"

pytestmark = pytest.mark.skipif(
    NODE is None or GIT is None, reason="needs node and git on PATH"
)


def _env() -> dict[str, str]:
    # Git exports GIT_INDEX_FILE and friends to its hooks, and the pre-commit hook runs this
    # suite: left in place they would point the throwaway repo's commands at this clone's index.
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        [GIT, *args],
        cwd=repo,
        env=_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=True,
    )
    return result.stdout.strip()


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    for key, value in (
        ("user.name", "test"),
        ("user.email", "test@example.invalid"),
        ("commit.gpgsign", "false"),
        ("core.autocrlf", "false"),
        ("core.hooksPath", "no-hooks"),
    ):
        _git(tmp_path, "config", key, value)
    languages = tmp_path / "frontend" / "src" / "i18n" / "languages.ts"
    languages.parent.mkdir(parents=True)
    languages.write_text(
        'export const LANGUAGES = [{ code: "en" }, { code: "xx" }];\n', encoding="utf-8"
    )
    (tmp_path / "scripts").mkdir()
    shutil.copy2(SCRIPT, tmp_path / "scripts" / SCRIPT.name)
    return tmp_path


def _commit(repo: Path, subject: str, en: dict, xx: dict) -> str:
    for lng, catalog in (("en", en), ("xx", xx)):
        path = repo / "frontend" / "src" / "i18n" / "locales" / lng / "translation.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", subject)
    return _git(repo, "rev-parse", "HEAD")


def _check(repo: Path, since: str, head: str = "HEAD") -> subprocess.CompletedProcess:
    return subprocess.run(
        [NODE, "scripts/check-i18n-stale.mjs", "--since", since, "--head", head],
        cwd=repo,
        env=_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )


EN = {"a": "Alpha", "b": "Beta", "c": "Gamma"}
XX = {"a": "xx Alpha", "b": "xx Beta", "c": "xx Gamma"}


def test_the_skip_token_exempts_only_what_its_own_commit_changed(repo):
    base = _commit(repo, "chore: catalogs", EN, XX)
    _commit(repo, "fix: typo in a [i18n-skip]", {**EN, "a": "Alfa"}, XX)
    _commit(repo, "feat: reword b", {**EN, "a": "Alfa", "b": "Beta two"}, XX)

    result = _check(repo, base)

    assert result.returncode == 1
    assert "[xx] b:" in result.stderr
    assert "[xx] a:" not in result.stderr
    assert "exempts a" in result.stdout


def test_translating_the_other_string_passes(repo):
    base = _commit(repo, "chore: catalogs", EN, XX)
    _commit(repo, "fix: typo in a [i18n-skip]", {**EN, "a": "Alfa"}, XX)
    en = {**EN, "a": "Alfa", "b": "Beta two"}
    _commit(repo, "feat: reword b", en, XX)
    _commit(repo, "feat: translate b", en, {**XX, "b": "xx Beta two"})

    result = _check(repo, base)

    assert result.returncode == 0, result.stderr
    assert "1 exempted" in result.stdout


def test_the_range_starts_at_the_merge_base(repo):
    _commit(repo, "chore: catalogs", EN, XX)
    _git(repo, "branch", "upstream")
    _git(repo, "checkout", "-q", "-b", "feature")
    _commit(repo, "feat: reword b", {**EN, "b": "Beta two"}, {**XX, "b": "xx Beta two"})
    _git(repo, "checkout", "-q", "upstream")
    _commit(repo, "fix: typo in c [i18n-skip]", {**EN, "c": "Gama"}, XX)
    _git(repo, "checkout", "-q", "feature")

    result = _check(repo, "upstream", "feature")

    assert result.returncode == 0, result.stderr
