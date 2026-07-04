"""Assert the built wheel ships static/** + per-module *.sql + version 2.0.0 (SC-4).

Run `python -m build` first (writes dist/, gitignored). Then `python scripts/check-wheel.py`.

Gitignore note: dist/ + ipmideck.egg-info/ are gitignored build artifacts — never `git add` them.
"""
from __future__ import annotations

import glob
import sys
import zipfile

whls = sorted(glob.glob("dist/ipmideck-*.whl"))
if not whls:
    sys.exit("no wheel in dist/ — run `python -m build` first")
z = zipfile.ZipFile(whls[-1])
n = z.namelist()
assert any(p.startswith("backend/static/") for p in n), "no SPA (backend/static/) in wheel"
assert any(p.endswith(".sql") and "/migrations/" in p for p in n), "no *.sql migrations in wheel"
assert any(p == "ipmideck-2.0.0.dist-info/METADATA" for p in n), "version drift (expected 2.0.0)"
print(f"wheel OK: {len(n)} entries")
