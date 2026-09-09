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
- **The container no longer runs as root.** It runs as a dedicated unprivileged user
  (uid/gid 1000). Existing data volumes are adopted automatically on first start — no manual
  `chown`. If the ownership cannot be changed (a read-only mount, NFS without `no_root_squash`,
  CIFS with a fixed uid/gid) the container still starts and logs a warning.
- **The database and `config.yaml` are now created readable only by their owner.** They were
  written with the default umask, so on a typical host every local account could read the stored
  BMC credentials. Existing installations are repaired automatically on the next start, and
  restoring a backup no longer widens the permissions of the restored files.
- **A failed login now answers HTTP 401** instead of 200, and a correct password is never
  refused because of the brute-force counter. That counter is keyed on a username supplied by
  the caller, so burning the attempt budget on a guessed name previously locked the real
  operator out of their own instance for the whole lockout window.
- **The BMC host address is validated against an allow-list.** Values that are not addresses at
  all were accepted and passed to `ipmitool`, where `-C0` selects cipher suite 0 and disables
  authentication on the IPMI session. The credential-test endpoint had no validation whatsoever.
- **Changing a server's address now requires re-entering its BMC credentials.** Those
  credentials are never returned by the API, so changing only the address re-pointed unreadable
  root-equivalent credentials at a machine of the caller's choosing.
- **CSV exports can no longer carry executable cells.** Event descriptions come verbatim from
  the BMC, and a cell starting with `=`, `+`, `-` or `@` is evaluated as a formula on open.
  Export filenames can no longer break out of the `Content-Disposition` header either.
- **Over-long passwords and malformed durations produce clear errors instead of HTTP 500.**
  A password beyond bcrypt's 72-byte limit crashed login and first-run setup, and the
  credential-change endpoint leaked the raw library exception text.
- **Interactive API documentation (`/docs`, `/redoc`) is disabled outside demo and debug mode**,
  and `/api/health` no longer discloses the build version or connection counts to anonymous
  callers.
- **Security headers are sent on every response**, state-changing requests from a foreign origin
  are rejected, and the session cookie is `SameSite=Strict`.
- **The session cookie's `Secure` flag is now correct behind a TLS-terminating proxy**, via the
  new `server.forwarded_allow_ips` setting (`IPMIDECK_SERVER_FORWARDED_ALLOW_IPS`).

### Fixed

- **A malformed fan curve no longer stops FanPilot from controlling other servers.** Curve
  points are stored as free-form JSON, and one unreadable curve aborted every control pass at
  the same server, leaving every server after it with no curve evaluation, no fail-safe and no
  auto-recovery — fans held at their last commanded speed while temperatures rose. An unusable
  curve now resolves to 100% and failures are contained to a single server.

### Changed

- **Removed the `auth.enabled`, `auth.max_login_attempts` and `auth.lockout_duration` config
  keys** (and `IPMIDECK_AUTH_ENABLED`). None of them were read by anything. Whether
  authentication is enabled lives in the database and is changed from the Security settings, so
  that write access to `config.yaml` cannot be used to turn the login off. `auth.session_expiry`
  is unaffected and continues to work; existing configuration files keep loading.
- **A server port other than 623 is now refused** with an explanation instead of being stored
  and silently ignored — nothing ever passed that value to `ipmitool`.
- `config.example.yaml` polling intervals now match the real defaults (30s). The example's
  `command_timeout: 10` was actively harmful: the default is 30s because a real BMC's sensor
  listing can take around 16 seconds.



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
