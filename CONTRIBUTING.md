# Contributing to IPMIDeck

## Running tests / pre-commit gate

IPMIDeck enforces a **local** pre-commit gate (`.githooks/pre-commit`). It runs, in
order: `ruff` lint → backend `pytest` (with the coverage gate) → i18n parity →
frontend `vitest` → SPA freshness (`backend/static` must match a clean build of
`frontend/src`). A commit is blocked if any step fails.

### One-time setup (per clone)

Point git at the committed hooks directory. This writes only the repo-local
`.git/config` (it does **not** touch your global git config):

```sh
git config core.hooksPath .githooks
```

Confirm it is active:

```sh
git config --get core.hooksPath   # -> .githooks
```

The hook is a POSIX `sh` script and runs under the bundled Git-Bash on Windows.

### Running the checks manually

You can run any gate step on its own:

```sh
# Lint the Python source (project linter; target py311, line-length 100)
python -m ruff check backend tests

# Backend tests + the 80% coverage gate over the four safety-critical modules
python -m pytest --cov --cov-report=term-missing

# Frontend tests (Vitest + React Testing Library)
cd frontend && npm run test

# i18n catalog parity (all 12 catalogs must match the English master keys)
node scripts/check-i18n-parity.mjs

# SPA freshness — is the committed backend/static bundle current with frontend/src?
node scripts/check-spa-built.mjs
```

### The same gate runs in CI

The local hook is the **first** gate, not the only one. GitHub Actions runs the same checks:

- **`.github/workflows/ci.yml`** — on every push and pull request. It calls the reusable gate
  (`gate.yml`) and additionally builds the Docker image with `push: false`.
- **`.github/workflows/gate.yml`** — the reusable gate: ruff → pytest + coverage → i18n parity →
  vitest → **`npx tsc -b --noEmit`** → SPA freshness. Note the TypeScript project typecheck: it is
  the one step CI runs that the local hook does not.
- **`.github/workflows/release.yml`** — publishes to PyPI and Docker Hub, but **only** on a
  `v*.*.*` tag push and only when the gate is green. See [RELEASING.md](RELEASING.md).

Keep the local hook installed anyway: it gives you the same verdict in seconds instead of after a
round-trip through CI.
