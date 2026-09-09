# Changelog

All notable changes to IPMIDeck are recorded here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

At release time the release workflow slices the `## [<version>]` section out of this file and uses
it as the GitHub Release body. Before tagging a version, promote the relevant `[Unreleased]` items
into a new dated `## [<version>] - YYYY-MM-DD` section.

## [Unreleased]

> ### Upgrading logs everyone out — once
>
> **Every existing session is invalidated by this upgrade. Each operator must log in again
> exactly once.** Nothing is lost and no credentials change; the login page simply appears the
> first time you open the dashboard after updating.
>
> Why: session tokens are now bound to the account credentials, and a token that does not carry
> that binding is **refused**. Tokens issued by earlier versions do not carry it — and neither
> does a token forged from a stolen signing secret. The two are indistinguishable on that point,
> so accepting the ones without it would have left the forgery path open and made the fix
> cosmetic. A password change now also ends every existing session, which it previously did not.
>
> If you are reading this **while responding to an incident**, the companion action is the new
> `ipmideck rotate-session-secret` command: it replaces the session signing secret, so cookies
> minted offline from a copied or stolen database stop working. Stop the app, run it, restart.

### Security

- **Fixed a pre-authentication path traversal in the SPA catch-all (SEC-01).** An unauthenticated
  request for an escaping path (`../../`, and its `%2e` / `%2f` encoded spellings) could read any
  file the server process could — including the database and the credential encryption key. Paths
  are now canonicalised and required to resolve inside the web root.
- **The session signing secret can now be rotated (SEC-02).** New CLI action
  `ipmideck rotate-session-secret`. Previously a secret read out of a copied database kept minting
  valid cookies forever, with no supported way to evict them.
- **Changing the account password now ends every existing session (SEC-03).** It previously
  revoked nothing.
- **Completing first-run setup always leaves authentication enabled (SEC-04).** An instance whose
  authentication had been switched off before setup used to stay open permanently, with no visible
  symptom. Note that a freshly started, not-yet-configured instance is still claimable by anyone
  who can reach it, until first-run setup is completed.
- **Rewriting the account now requires the current password (SEC-05).** A valid-looking session
  cookie alone could previously replace the sole account through the Security settings — including
  on an instance with authentication disabled. The Security form has one new
  `Current password` field for this.
- **The app-config endpoint no longer returns the session secret (SEC-07).** The read path now
  enforces the same allow-list the write path already had.
- **`reset-password` no longer reports success for a username that does not exist (F17).**
- **Backup archives are credential-grade.** An archive bundles the encryption key, the database
  and the configuration together, so it must be stored as carefully as the credentials themselves.


### Added

- **See what changed, from inside the app.** The version in the sidebar now shows the version
  you are actually running and opens the full release history over whatever page you are on.
  The history ships inside the package and is read from disk, so it works on an air-gapped
  install with no network at all. A security release is marked as one.
- **Optional update checks, off until you say otherwise.** First-run setup now asks — one
  question, box already ticked — whether IPMIDeck may look up published versions. With it on,
  it checks at start-up and once a day and stays silent unless there is genuinely something
  newer. There is also a **Check now** button under Settings → About, and the console `[g]` key
  now performs a real check instead of printing a promise that one would arrive in a later
  release.

  The request is a single `GET` carrying the product name and your version and nothing else: no
  identifier, no hostname, nothing about your servers. It is logged verbatim before the socket
  opens so you can audit it yourself. Nothing is downloaded or installed. The lookup uses the
  standard library only — the runtime dependencies still contain no HTTP client.

  Setting `updates.enabled: false` in `config.yaml` (or `IPMIDECK_UPDATES_ENABLED=false`) turns
  it off outright: the endpoints that could open a socket are not registered at all and the
  periodic check never starts, regardless of what was answered during setup. The version
  history keeps working.
- The startup log now names the running version and where to read what changed, so a report
  from `docker logs` identifies itself.


## [2.0.1] - 2026-07-25

### Fixed

- Session expiry is now honored. `IPMIDECK_AUTH_SESSION_EXPIRY` (and the `auth.session_expiry`
  config key) now set the session token and cookie lifetime; previously the setting had no effect
  and the lifetime was always 24 hours.
- FanPilot status no longer reports "active" for monitoring-only vendors (HPE, Lenovo, and unknown
  BMCs). Their fans stay under the BMC's own control, and the dashboard now shows that instead of a
  false "FanPilot active" state.

## [2.0.0] - 2026-07-13

Complete rewrite. v1 was a single-page app that pushed fan commands at one Dell PowerEdge; v2 is a
self-hosted IPMI platform — a Python/FastAPI backend serving a React dashboard, talking to any
number of BMCs over ipmitool. Everything runs locally: SQLite on disk, no cloud, no telemetry.

### Added

- Multi-server dashboard with live sensors (temperature, fan RPM, voltage, power) over a WebSocket,
  history charts, and a drag-and-drop widget grid.
- FanPilot: a backend fan-curve engine with hysteresis, a non-negotiable safety override at the
  critical threshold, and fail-safe handling when a BMC becomes unreachable.
- Power control (on, soft off, hard off, reset, cycle) with an audit log and per-server energy-cost
  tracking.
- Hardware event log (SEL) and FRU inventory, both browsable, searchable, and exportable to CSV/JSON.
- 12 languages, dark and light themes, optional local authentication, HTTPS with self-signed
  certificates, and one-click backup/restore.
- Ships as a multi-arch Docker image (`devluigi06/ipmideck`) and the `ipmideck` package on PyPI.

### Notes

- Fan control is vendor-specific: Dell is tested on real hardware; Supermicro and IBM are
  experimental; HPE, Lenovo, and unknown BMCs are monitoring-only (full sensors, power, SEL, and
  FRU, but no fan writes).

[Unreleased]: https://github.com/ipmideck/IPMIDeck/compare/v2.0.1...HEAD
[2.0.1]: https://github.com/ipmideck/IPMIDeck/compare/v2.0.0...v2.0.1
[2.0.0]: https://github.com/ipmideck/IPMIDeck/compare/84df472...v2.0.0
