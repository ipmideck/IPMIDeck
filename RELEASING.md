# Releasing IPMIDeck

This document describes how the **first public release** (`2.0.0`) of IPMIDeck is published to
**PyPI** and **Docker Hub**. The packaging plumbing and proof build are already in place — what
remains are a few **maintainer-only** prerequisites and the single action that fires the release.

> **PyPI publish path: OIDC Trusted Publishing only.** IPMIDeck is published to PyPI exclusively by
> the tag-triggered [`.github/workflows/release.yml`](.github/workflows/release.yml) using PyPI
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
3. The push triggers `release.yml`:
   - **guard** — asserts the pushed tag (stripped of its `v`) equals `_VERSION_FALLBACK` (`2.0.0`),
     so a tag/literal drift fails the release *before* anything is published;
   - **tests** — the reusable test gate (`gate.yml`);
   - **pypi** — builds the wheel + sdist and publishes to PyPI via OIDC Trusted Publishing
     (`pypa/gh-action-pypi-publish`, `id-token: write`, no secret);
   - **dockerhub-preflight** + **dockerhub** — multi-arch (amd64 + arm64) build and push to
     `devluigi06/ipmideck`, then syncs this repo's `README.md` as the Docker Hub repo description.
     **Skip-safe:** if the `DOCKERHUB_TOKEN` secret is absent, the preflight reports no token and
     the `dockerhub` job is skipped — the rest of the release still succeeds;
   - **release-draft** — creates a **draft** GitHub Release with generated notes. The maintainer
     presses Publish.

> `release-draft` depends on `guard` + `tests` only — deliberately **not** on `dockerhub`. A
> skipped job skips its dependents in GitHub Actions, so hanging the draft off the skip-safe
> `dockerhub` job would mean no Release is ever drafted when the token is unset.

There is **no publish to the GitHub container registry** — Docker Hub is the only container
registry for this project.

Everything above is automated. The steps below are the **one-time setup** plus the **one action**
the maintainer performs.

---

## Maintainer-only prerequisites

These are **not** performed by automation or by any AI assistant — they require a human with a PyPI
account, a Docker Hub account, and push access. They are documented here, not executed.

### 1. One-time: create a PyPI account

- Create an account at https://pypi.org and verify the email address.
- (Enabling 2FA is strongly recommended.)

### 2. One-time: add a *pending* Trusted Publisher on PyPI

The `ipmideck` project does **not exist on PyPI yet** (chicken-and-egg: a project is created on its
first successful publish). PyPI solves this with a **pending publisher** you configure in advance.

On https://pypi.org → **Account settings → Publishing → "Add a new pending publisher"**, choose the
**GitHub Actions** form and enter these **exact** values (they must match the shipped
`release.yml`):

| Field             | Value                                                     |
| ----------------- | --------------------------------------------------------- |
| PyPI Project Name | `ipmideck`                                                |
| Owner             | `ipmideck` (the GitHub org owning the repo)               |
| Repository name   | `IPMIDeck`                                                |
| Workflow name     | `release.yml` (the workflow filename only, not a path)    |
| Environment name  | *leave BLANK* — the `pypi` job declares no `environment:`  |

> **The repo moved.** If a pending publisher was already configured against the project's old
> GitHub location, it must be **updated or recreated** with the values above — PyPI matches the
> OIDC claim against owner + repository + workflow, so a stale entry means the publish is rejected.

> **Chicken-and-egg caveat:** a pending publisher does **not reserve the project name**. Configure
> it and then publish promptly — the name is only claimed on the first successful upload, at which
> point the pending publisher **auto-converts** to a normal Trusted Publisher and creates the
> `ipmideck` project.

### 3. One-time: Docker Hub access token + repo secret

The container image is published to **`devluigi06/ipmideck`** on Docker Hub. The `dockerhub` job
authenticates with a Docker Hub **access token**, supplied as a GitHub repository secret.

1. On https://hub.docker.com (account **`devluigi06`**) → **Account Settings → Personal access
   tokens → Generate new token**. Give it **Read, Write, Delete** scope — the write scope is needed
   to push the image, and the description-sync step (`peter-evans/dockerhub-description@v4`)
   requires a token with delete scope to update the repository description.
2. On GitHub → the **`ipmideck/IPMIDeck`** repo → **Settings → Secrets and variables → Actions →
   New repository secret**:
   - Name: **`DOCKERHUB_TOKEN`**
   - Value: the token from step 1
3. That is all. The username (`devluigi06`) is a public handle and is hardcoded in `release.yml`;
   only the token is secret.

> **Skip-safe by design.** `release.yml` probes for the secret in a `dockerhub-preflight` job. If
> `DOCKERHUB_TOKEN` is not set, the `dockerhub` job is skipped and the release still succeeds
> (PyPI publish + draft Release). Set the secret when you want images published.

> The token is **never** stored in this repository, never printed in logs, and is never handled by
> an AI assistant — it goes straight from Docker Hub into GitHub's secret store.

### 4. Fire the release (the only maintainer action that publishes)

The version bump is already committed by the packaging phase. To cut `2.0.0`, the maintainer runs:

```bash
git tag v2.0.0
git push origin v2.0.0
```

That tag push triggers `release.yml` → guard → tests → pypi (OIDC publish) + dockerhub (image push)
→ release-draft. No further manual steps; in particular, **do not** run `twine` and **do not**
create or store a PyPI API token. The GitHub Release is created as a **draft** — review the
generated notes, then press Publish.

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
- No manual `docker login` / `docker build` / `docker push` — the `dockerhub` job does all three in
  CI using the `DOCKERHUB_TOKEN` repository secret. The maintainer never pushes an image by hand.
- The actual account creation, publisher configuration, token creation, and tag push are
  **maintainer actions** and are not performed as part of preparing the package.
