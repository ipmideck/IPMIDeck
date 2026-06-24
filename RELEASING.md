# Releasing IPMIDeck

This document describes how the **first public release** (`2.0.0`) of IPMIDeck is published to
PyPI and GHCR. The packaging plumbing and proof build are already in place — what remains are a
few **maintainer-only** prerequisites and the single action that fires the release.

> **Publish path: OIDC Trusted Publishing only.** IPMIDeck is published exclusively by the
> tag-triggered [`.github/workflows/release.yml`](.github/workflows/release.yml) using PyPI
> **Trusted Publishing (OIDC)**. There is **no manual `twine upload` path** and no long-lived PyPI
> API token in this project — a manual `twine` upload is **not a supported release method**. Do not
> run `twine` locally; let the workflow do the publish via OIDC.

End users install the released package with `pip install ipmideck` (see [README](README.md#pip)) —
that is the user-facing install doc; this file is the operator-facing release runbook.

---

## How a release fires (overview)

1. The version bump to `2.0.0` is **already committed** (the single source of truth is
   `backend/core/branding.py` → `_VERSION_FALLBACK = "2.0.0"`; `pyproject.toml` derives the wheel
   version from it via `[tool.setuptools.dynamic]`).
2. The maintainer pushes the tag `v2.0.0`.
3. The push triggers `release.yml`, which runs in order:
   - **guard** — asserts the pushed tag (stripped of its `v`) equals `_VERSION_FALLBACK` (`2.0.0`),
     so a tag/literal drift fails the release;
   - **tests** — the reusable test gate (`gate.yml`);
   - **pypi** — builds the wheel + sdist and publishes to PyPI via OIDC Trusted Publishing
     (`pypa/gh-action-pypi-publish`, `id-token: write`, no secret);
   - **ghcr** — builds and pushes the container image to GHCR.

Everything above is automated. The steps below are the **one-time setup** plus the **one action**
the maintainer performs.

---

## Maintainer-only prerequisites

These are **not** performed by automation or by any AI assistant — they require a human with a PyPI
account and push access. They are documented here, not executed.

### 1. One-time: create a PyPI account

- Create an account at https://pypi.org and verify the email address.
- (Enabling 2FA is strongly recommended.)

### 2. One-time: add a *pending* Trusted Publisher on PyPI

The `ipmideck` project does **not exist on PyPI yet** (chicken-and-egg: a project is created on its
first successful publish). PyPI solves this with a **pending publisher** you configure in advance.

On https://pypi.org → **Account settings → Publishing → "Add a new pending publisher"**, choose the
**GitHub Actions** form and enter these **exact** values (they must match the shipped
`release.yml`):

| Field             | Value                                          |
| ----------------- | ---------------------------------------------- |
| PyPI Project Name | `ipmideck`                                     |
| Owner             | `dev-luigi` (the GitHub user/org owning the repo) |
| Repository name   | `IPMI-FanPilot` (current repo slug — a slug rename is deferred) |
| Workflow name     | `release.yml` (the workflow filename only, not a path) |
| Environment name  | *leave BLANK* — the `pypi` job declares no `environment:` |

> **Chicken-and-egg caveat:** a pending publisher does **not reserve the project name**. Configure
> it and then publish promptly — the name is only claimed on the first successful upload, at which
> point the pending publisher **auto-converts** to a normal Trusted Publisher and creates the
> `ipmideck` project.

### 3. Fire the release (the only maintainer action that publishes)

The version bump is already committed by the packaging phase. To cut `2.0.0`, the maintainer runs:

```bash
git tag v2.0.0
git push origin v2.0.0
```

That tag push triggers `release.yml` → guard → tests → pypi (OIDC publish) → ghcr. No further
manual steps; in particular, **do not** run `twine` and **do not** create or store a PyPI API token.

---

## Optional hardening (maintainer decision)

PyPA recommends scoping a Trusted Publisher to a dedicated GitHub Actions **environment** (e.g.
`environment: pypi` on the `pypi` job, with the matching Environment name set on the pending
publisher). This adds an approval/protection gate around the publish step. It is **optional** — the
release pipeline shipped without it, and adopting it is a maintainer decision (it requires editing
both `release.yml` and the publisher config to keep them in sync).

---

## What is intentionally NOT here

- No PyPI account credentials, API tokens, or secrets — OIDC means there is nothing to store.
- No `twine upload` instructions — that path is deliberately unsupported (see the note at the top).
- The actual account creation, publisher configuration, and tag push are **maintainer actions** and
  are not performed as part of preparing the package.
