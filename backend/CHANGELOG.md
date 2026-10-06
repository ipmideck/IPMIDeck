# Changelog

All notable changes to IPMIDeck are recorded here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

At release time the release workflow slices the `## [<version>]` section out of this file and uses
it as the GitHub Release body. Before tagging a version, promote the relevant `[Unreleased]` items
into a new dated `## [<version>] - YYYY-MM-DD` section.

Each release uses only these groups, in this order: `Upgrade notes` (at most 2, only for what an
operator must do), `Security`, `Added`, `Changed`, `Fixed`, `Deprecated`, `Removed`. Each entry is
one bullet: a bold headline ending in a full stop (at most 80 characters), then at most 250
characters of detail. At most 8 entries per group; internal changes (tests, CI, refactors) are
left out. `tests/unit/test_changelog_format.py` enforces this.

## [Unreleased]

### Upgrade notes

- **The first start logs everyone out and converts stored credentials.** Each operator logs in
  again once; nothing is lost. Stored BMC credentials are re-encrypted automatically, and
  `ipmideck.db` and `encryption.key` are first copied to `*.pre-authenc-<timestamp>.bak`. Those
  copies hold your BMC passwords: delete them once the upgrade looks good, or move them back over
  the live files to downgrade.
- **Behind a reverse proxy, set `trusted_origins` before upgrading.** Saves from a foreign origin
  are now refused. If the proxy does not pass the browser's `Host` (nginx needs
  `proxy_set_header Host $host;`), list the external address in `server.trusted_origins`, or every
  save fails with `Cross-origin request rejected`. Also list the proxy in
  `server.forwarded_allow_ips`. See **Behind a reverse proxy** in the README.

### Security

- **Fixed a pre-authentication path traversal that could read any file.** An escaping path sent
  to the web UI catch-all, encoded spellings included, could read the database and the encryption
  key. Paths must now resolve inside the web root.
- **Sessions are bound to the account, and the signing secret can be rotated.** A password change
  ends every session, `ipmideck rotate-session-secret` evicts cookies minted from a copied
  database, and rewriting the account needs the current password.
- **Setup always leaves the login on, and secrets stay out of the API.** Finishing first-run setup
  re-enables a switched-off login. The config endpoint no longer returns the session secret, and
  anonymous callers no longer see `/docs`, `/redoc` or the build version.
- **Login attempts are limited without locking the operator out.** A failed login answers 401,
  credential checks are capped per address (`IPMIDECK_ATTEMPT_LIMIT`, `IPMIDECK_ATTEMPT_WINDOW`),
  a guessed username no longer locks out the real one, and `reset-password` rejects unknown names.
- **Stored BMC credentials use authenticated encryption (AES-256-GCM).** A modified value is now
  detected, and an undecryptable credential answers like an unreachable BMC, so probing cannot
  tell the two apart. The conversion is automatic; see the upgrade notes.
- **Requests from other sites are refused.** State-changing requests and the telemetry WebSocket
  check the origin, security headers go out on every response, and the session cookie is
  `SameSite=Strict`, with a correct `Secure` flag behind a TLS proxy.
- **BMC input is validated and bounded.** Host addresses must pass an allow-list (a crafted value
  could switch off IPMI authentication), BMC responses are size-limited, and changing a server's
  address requires re-entering its credentials.
- **Files and exports are locked down.** The container runs unprivileged (uid 1000, volumes
  adopted on start), the database and `config.yaml` are owner-only, CSV cells cannot run as
  formulas, and backup archives must be stored like the credentials they contain.

### Added

- **HTTPS with no manual certificate step.** Set `https: true` (or use the Network card in
  Settings) and restart: a certificate for this machine is generated under `<data_dir>/certs/`.
  If that fails the app starts over plain HTTP and logs why.
- **See what changed, from inside the app.** The version in the sidebar opens the release
  history over any page. It ships inside the package, so it works with no network, and security
  releases are marked.
- **Update checks, on by default.** At start-up and once a day IPMIDeck asks whether a newer
  version exists, sending only the product name and version; nothing is downloaded. Turn it off
  under **Settings → About → Updates**, or everywhere with `updates.enabled: false`.
- **A Check now button, and a console `[g]` key that really checks.** Both look up the latest
  version on demand, whatever the automatic setting is.
- **ipmitool can be installed from the web UI.** The missing-ipmitool notice has an Install
  button: it runs the package manager when `ipmi.auto_install_ipmitool` is on and IPMIDeck is
  privileged, and otherwise shows the command. On Windows it finds Dell's bundled ipmitool.exe.
- **A newer version is announced in the console, with its upgrade command.** The first time the
  automatic check finds one, the console says so whatever its verbosity (the log, when there is
  no console), with the command for this install: Docker, pip or git.
- **The startup log names the running version.** A report from `docker logs` now identifies
  itself and says where to read what changed.
- **Updates can be installed from the web UI.** A notice and an Upgrade button open the new
  version's notes with a Download and install button. It backs up the data, updates pip, pipx and
  uv installs and restarts; Docker goes through Watchtower when set up. Otherwise it shows the
  command.

### Changed

- **A server port other than 623 is refused.** It was stored and silently ignored, since nothing
  ever passed it to `ipmitool`.
- **`config.example.yaml` matches the real defaults.** Polling intervals are 30s, and the
  example's `command_timeout: 10` is gone: a real BMC's sensor listing can take about 16 seconds.

### Fixed

- **A missing `ipmitool` is named, with the command that installs it.** The raw OS error and the
  traceback on every poll are replaced by one warning, a web UI notice with the install command
  and a *Check again* button, and a localized error on every action.
  ([#14](https://github.com/ipmideck/IPMIDeck/issues/14))
- **The container can serve HTTPS.** The image now starts through the `ipmideck` command, which
  sets up the certificate; `https` used to be silently ignored in Docker while the log announced
  it. The health check follows the scheme actually served.
- **One bad fan curve no longer stops FanPilot for every server.** An unusable curve, including
  `NaN` or `Infinity` points, now runs that server's fans at 100% and says why in a notification
  and the command log, while other servers keep their curves.
- **The container restarts cleanly and reports its health correctly.** Restarting under host
  networking no longer trips the single-instance check, and the health check probes the port the
  app really listens on.
- **Open tabs keep working after an upgrade.** The page is now always revalidated, so a browser
  no longer keeps an old copy that asks for files the new version removed ("Failed to fetch
  dynamically imported module"); a tab that still hits one reloads itself once.
- **Bad input gets a clear error instead of HTTP 500.** Over-long passwords, malformed durations,
  malformed `Origin` or `Referer` headers and undecryptable stored credentials now produce a
  readable message.

### Removed

- **Three config keys that nothing read.** `auth.enabled` (and `IPMIDECK_AUTH_ENABLED`),
  `auth.max_login_attempts` and `auth.lockout_duration`. The login is switched on or off in the
  Security settings, so `config.yaml` cannot turn it off. Existing files keep loading.

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
