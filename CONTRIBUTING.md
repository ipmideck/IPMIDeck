# Contributing to IPMIDeck

## Running tests / pre-commit gate

IPMIDeck enforces a **local** pre-commit gate (`.githooks/pre-commit`). It runs, in
order: `ruff` lint → backend `pytest` (with the coverage gate) → i18n parity →
frontend `vitest`. A commit is blocked if any step fails.

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
```

### Why a local hook instead of CI?

CI via **GitHub Actions is intentionally NOT configured**: this project follows a
no-push policy, so there is no remote to run Actions against. The local
`.githooks/pre-commit` hook is the enforced gate. Adopt GitHub Actions only
if/when a remote push workflow is introduced.
