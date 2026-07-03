"""Phase-6 baseline-invariance guards (C2/C3) — committed git-diff assertions.

This module turns the Phase-6 ground truth into ENFORCED, executable assertions so the
invariance is GUARDED on every run, not merely observed once. Phase 6 was a UI redesign:
it changed ONLY frontend/** + backend/static/**, the backend product Python is byte-identical
across the phase, and the API route declarations are untouched (the live counterpart of that
fact is pinned in test_contract_surface.py).

FIXED commit ranges (REVIEW FIX-1 — the moving-HEAD defect, deliberately avoided):
  This very test file is committed INSIDE the Phase-7 range, so any C3 assertion against
  a9d2f12..HEAD would break the instant this plan lands. ALL Phase-6 PRODUCT-diff assertions
  therefore use the FIXED range a9d2f12..b207817 — it can never see Phase-7's own additions, so
  it stays empty forever and 07-01/07-02 remain safely parallel. A SEPARATE check on
  b207817..HEAD enforces that the Phase-7 commits introduce ONLY verification scaffolding.

  PHASE6_BASELINE = a9d2f12  pre-Phase-6 baseline (== main tip; merge-base of main and the
                             Phase-6 branch).
  PHASE6_TIP      = b207817  Phase-6 branch tip = last Phase-6 product commit.

  Phase-6 PRODUCT diff  = a9d2f12..b207817  — presentation-only (frontend/ + backend/static/).
  Phase-7 SCAFFOLDING   = b207817..HEAD      — verification artifacts only (this is the ONLY
                                              range that references the moving HEAD, and only in
                                              the scaffolding/no-weakening tests below).

LOUD baseline-absent failure (REVIEW FIX-4): if either pinned commit is missing (e.g. a shallow
clone), the tests pytest.fail() LOUDLY — they NEVER pytest.skip. A skipped invariance test is
indistinguishable from a silent regression pass, so a skip must never count as C3 evidence.

All git usage here is READ-ONLY (git diff / git cat-file). No mutating git command is invoked.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

# FIXED commit constants (REVIEW FIX-1) — NEVER substitute a moving HEAD for a product-diff.
PHASE6_BASELINE = "a9d2f12"  # pre-Phase-6 baseline (== main tip)
PHASE6_TIP = "b207817"  # Phase-6 branch tip — FIXED; product diff is a9d2f12..b207817
# 08-01: Phase-7 tip — FIXED upper bound for the scaffolding-scope range. Phase 8 legitimately
# commits backend PRODUCT python (vendor correctness), so pinning the Phase-7 range END here
# (mirroring the FIX-1 moving-HEAD rationale above) keeps the "Phase-7 added ONLY scaffolding"
# guard exact and immune to Phase-8+ commits — an unbounded b207817..HEAD would falsely flag them.
PHASE7_TIP = "86268dd"  # last Phase-7 commit (== HEAD immediately before Phase 8 began)

# Repo root derived at runtime (CLAUDE.md: never hardcode an absolute user path).
# This file lives at <repo>/tests/integration/test_baseline_invariance.py -> parents[2] == repo.
REPO_ROOT = Path(__file__).resolve().parents[2]


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    """Run a READ-ONLY git command in the repo root and return the completed process."""
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def _require_baseline() -> None:
    """FAIL LOUDLY (never skip) if either pinned commit is absent (REVIEW FIX-4).

    A skipped invariance test cannot be told apart from a silent regression pass, so a missing
    baseline must FAIL — it can never count as C3 evidence.
    """
    for sha in (PHASE6_BASELINE, PHASE6_TIP, PHASE7_TIP):
        result = _git("cat-file", "-e", f"{sha}^{{commit}}")
        if result.returncode != 0:
            pytest.fail(
                f"baseline/tip commit {sha} absent — C3 NOT PROVEN "
                "(shallow clone? run `git fetch --unshallow`). "
                "This is a hard failure, NOT a skip: a skipped invariance test "
                "would be indistinguishable from a silent regression pass."
            )


def _changed_paths(rev_range: str, *pathspec: str) -> list[str]:
    """`git diff --name-only <rev_range> [-- pathspec...]` -> list of changed paths."""
    args = ["diff", "--name-only", rev_range]
    if pathspec:
        args += ["--", *pathspec]
    result = _git(*args)
    assert result.returncode == 0, f"git diff failed: {result.stderr}"
    return [line for line in result.stdout.splitlines() if line.strip()]


def _name_status(rev_range: str) -> list[tuple[str, str]]:
    """`git diff --name-status <rev_range>` -> list of (status, path) tuples.

    Status is the leading code (A/M/D/R...); rename lines (R100\told\tnew) keep the final path.
    """
    result = _git("diff", "--name-status", rev_range)
    assert result.returncode == 0, f"git diff failed: {result.stderr}"
    rows: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0]
        path = parts[-1]  # for renames (R<score>\told\tnew) the new path is last
        rows.append((status, path))
    return rows


# --- C3: Phase-6 backend PRODUCT logic is invariant (FIXED range) ---------------------------


def test_no_backend_product_python_changed_phase6():
    """Zero backend PRODUCT *.py files changed across the FIXED Phase-6 range a9d2f12..b207817.

    Scoped to backend product python (FIX-2): backend/**/*.py MINUS backend/static/** and tests/**.
    If a Phase-6 commit had touched any backend handler/engine/service, it would appear here.
    """
    _require_baseline()
    changed = _changed_paths(
        f"{PHASE6_BASELINE}..{PHASE6_TIP}",
        "backend/**/*.py",
        ":(exclude)backend/static/**",
        ":(exclude)tests/**",
    )
    assert changed == [], (
        "Phase 6 must not change backend product python, but these changed across "
        f"{PHASE6_BASELINE}..{PHASE6_TIP}:\n" + "\n".join(changed)
    )


def test_phase6_only_frontend_and_static_touched():
    """Every path changed across a9d2f12..b207817 starts with frontend/ or backend/static/.

    Phase 6 is presentation-only; any other touched path (e.g. backend/api/, pyproject.toml)
    would be a C3 violation and is listed in the failure message.
    """
    _require_baseline()
    changed = _changed_paths(f"{PHASE6_BASELINE}..{PHASE6_TIP}")
    offenders = [
        p for p in changed if not (p.startswith("frontend/") or p.startswith("backend/static/"))
    ]
    assert offenders == [], (
        "Phase 6 must touch ONLY frontend/ + backend/static/, but these are out of scope "
        f"across {PHASE6_BASELINE}..{PHASE6_TIP}:\n" + "\n".join(offenders)
    )


def test_route_declaration_files_unchanged_phase6():
    """The route-DECLARATION files are byte-identical across the FIXED Phase-6 range (C2 baseline).

    Complements test_contract_surface.py's LIVE snapshot: main.py + every backend/api/*.py +
    every backend/modules/*/routes.py is unchanged a9d2f12..b207817, so the declared surface
    could not have drifted during Phase 6. Globs are expanded in Python to real, present paths.
    """
    _require_baseline()
    decl_files = [REPO_ROOT / "backend" / "main.py"]
    decl_files += sorted((REPO_ROOT / "backend" / "api").glob("*.py"))
    decl_files += sorted((REPO_ROOT / "backend" / "modules").glob("*/routes.py"))
    # Pass repo-relative posix paths to git.
    pathspec = [f.relative_to(REPO_ROOT).as_posix() for f in decl_files if f.exists()]
    assert pathspec, "no route-declaration files resolved — glob expansion broke"
    changed = _changed_paths(f"{PHASE6_BASELINE}..{PHASE6_TIP}", *pathspec)
    assert changed == [], (
        "Route-declaration files must be unchanged across "
        f"{PHASE6_BASELINE}..{PHASE6_TIP}, but these changed:\n" + "\n".join(changed)
    )


# --- Phase-7 scaffolding scope (the ONE deliberate use of the moving HEAD) -------------------


def test_phase7_scaffolding_scope_only():
    """The Phase-7 range b207817..86268dd contains ONLY verification scaffolding (REVIEW FIX-1).

    This is the SEPARATE scaffolding check — it guards the Phase-7 commits themselves (NOT a
    Phase-6 product diff). The upper bound is PINNED to the Phase-7 tip (PHASE7_TIP), NOT a moving
    HEAD: Phase 8 legitimately adds backend PRODUCT python (per-vendor IPMI correctness), and an
    unbounded b207817..HEAD would falsely flag those Phase-8 commits. Pinning the END mirrors the
    FIX-1 rationale already applied to the Phase-6 product diff, so the guard stays exact forever.

    Allow-list per changed path in the Phase-7 range:
      * tests/integration/*.py  (the verification tests), OR
      * scripts/*               (optional check scripts).
    Explicitly: ZERO backend/**.py outside tests/, and ZERO frontend/** product code.
    """
    _require_baseline()
    changed = _changed_paths(f"{PHASE6_TIP}..{PHASE7_TIP}")

    def _allowed(path: str) -> bool:
        if path.startswith("tests/integration/") and path.endswith(".py"):
            return True
        if path.startswith("scripts/"):
            return True
        return False

    out_of_allowlist = [p for p in changed if not _allowed(p)]
    assert out_of_allowlist == [], (
        "Phase-7 range must contain ONLY verification scaffolding "
        "(tests/integration/*.py or scripts/), but these are out of the allow-list "
        f"across {PHASE6_TIP}..{PHASE7_TIP}:\n" + "\n".join(out_of_allowlist)
    )

    # Hard belt-and-suspenders: no backend product python, no frontend product code.
    backend_product = [
        p for p in changed if p.startswith("backend/") and p.endswith(".py") and not p.startswith("tests/")
    ]
    assert backend_product == [], (
        "Phase-7 must add ZERO backend product python, but found:\n" + "\n".join(backend_product)
    )
    frontend_product = [p for p in changed if p.startswith("frontend/")]
    assert frontend_product == [], (
        "Phase-7 must add ZERO frontend product code, but found:\n" + "\n".join(frontend_product)
    )


# --- No-weakening audit (REVIEW FIX-3) ------------------------------------------------------


def test_no_test_weakening():
    """Phase 6 weakened no test, and Phase 7 deletes/skips/xfails no existing test (FIX-3).

    Three sub-checks:
      (a) Phase 6 touched no test at all (a9d2f12..b207817 -- tests/ is empty).
      (b) The Phase-7 range deletes no existing test (no `D` under tests/) and does NOT modify
          pyproject.toml (so fail_under / coverage include= scope cannot be quietly relaxed).
          Newly ADDED tests/integration/*.py appear as `A`, which is allowed.
      (c) Any EXISTING test file MODIFIED in the Phase-7 range adds no skip/xfail marker.
    """
    _require_baseline()

    # (a) Phase 6 touched no test.
    phase6_tests = _changed_paths(f"{PHASE6_BASELINE}..{PHASE6_TIP}", "tests/")
    assert phase6_tests == [], (
        "Phase 6 must touch no test, but these changed across "
        f"{PHASE6_BASELINE}..{PHASE6_TIP}:\n" + "\n".join(phase6_tests)
    )

    # (b) Phase-7 range: no deleted test, no pyproject.toml modification.
    rows = _name_status(f"{PHASE6_TIP}..HEAD")
    deleted_tests = [p for (s, p) in rows if s.startswith("D") and p.startswith("tests/")]
    assert deleted_tests == [], (
        "Phase 7 must delete no existing test, but these were deleted across "
        f"{PHASE6_TIP}..HEAD:\n" + "\n".join(deleted_tests)
    )
    pyproject_mods = [p for (s, p) in rows if p == "pyproject.toml" and s.startswith(("M", "D"))]
    assert pyproject_mods == [], (
        "Phase 7 must not modify pyproject.toml (coverage scope / fail_under must not be "
        f"relaxed), but it was changed across {PHASE6_TIP}..HEAD."
    )

    # (c) Existing test files modified in the Phase-7 range must add no skip/xfail.
    weakening_markers = ("@pytest.mark.skip", "@pytest.mark.xfail", "pytest.skip(")
    modified_tests = [
        p for (s, p) in rows if s.startswith("M") and p.startswith("tests/") and p.endswith(".py")
    ]
    for path in modified_tests:
        diff = _git("diff", f"{PHASE6_TIP}..HEAD", "--", path)
        assert diff.returncode == 0, f"git diff failed for {path}: {diff.stderr}"
        added_lines = [
            ln for ln in diff.stdout.splitlines() if ln.startswith("+") and not ln.startswith("+++")
        ]
        offenders = [ln for ln in added_lines if any(m in ln for m in weakening_markers)]
        assert offenders == [], (
            f"Phase 7 added a skip/xfail marker to existing test {path}:\n"
            + "\n".join(offenders)
        )
