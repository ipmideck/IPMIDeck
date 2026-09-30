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

> ### Behind a reverse proxy: check `trusted_origins` before upgrading
>
> State-changing requests are now refused when the browser reports an origin other than the one
> the dashboard is served from. If your proxy does not pass the browser's `Host` through — nginx
> does not, unless you added `proxy_set_header Host $host;` — every save will fail with
> `Cross-origin request rejected` and the dashboard will look loaded but inert.
>
> Either fix the proxy header, or name the external address:
>
> ```yaml
> server:
>   trusted_origins:
>     - https://ipmi.example.com
> ```
>
> Direct deployments and Docker port mappings need nothing. See **Behind a reverse proxy** in
> the README for the companion `forwarded_allow_ips` setting.

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
  BMC credentials. Existing installations are repaired automatically on the next start — the
  database and its write-ahead sidecars every time it is opened, `config.yaml` once during
  startup — and restoring a backup no longer widens the permissions of the restored files.
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
- **Security headers are sent on every response** — `frame-ancestors 'none'` and
  `X-Frame-Options: DENY` against clickjacking, `nosniff`, `Referrer-Policy: no-referrer`, and
  HSTS on TLS requests only — and the session cookie is `SameSite=Strict`.
- **State-changing requests from a foreign origin are rejected**, including from another port on
  the same host, which cookies alone do not separate. Requests carrying neither `Origin` nor
  `Referer` — the CLI, the container health check, scripted integrations — are unaffected.
  Deployments behind a proxy that rewrites `Host` must declare their external address in the new
  `server.trusted_origins` setting (`IPMIDECK_SERVER_TRUSTED_ORIGINS`); see the upgrade note above.
- **The session cookie's `Secure` flag is now correct behind a TLS-terminating proxy**, via the
  new `server.forwarded_allow_ips` setting (`IPMIDECK_SERVER_FORWARDED_ALLOW_IPS`).

- **Stored BMC credentials now use authenticated encryption (AES-256-GCM).** The previous
  format concealed the value but did not detect modification, so anyone who could write to the
  database could alter a stored credential undetectably. Stored values now carry a version
  marker, and **the first start after upgrading converts existing credentials automatically** —
  no action required, nothing is re-entered.

  Before it changes anything the conversion copies `ipmideck.db` and `encryption.key` next to
  themselves as `*.pre-authenc-<timestamp>.bak`. **Those copies are credential-grade** — they
  contain your BMC passwords and the key that decrypts them. Keep them until you are satisfied
  the upgrade went well, then delete them. They are never included in a backup archive.

  Downgrading afterwards is possible: stop the app, move the two `.bak` files back over the
  live names, install the older version. If you are not downgrading you do not need them —
  the new version reads both formats, so an unconverted database keeps working.
- **A credential that cannot be decrypted no longer answers differently from a BMC that is
  simply unreachable.** The connection-test and fan-mode endpoints used to fail with a server
  error in the first case and an ordinary failure in the second, which distinguished the two
  for anyone probing.
- **Credential checks are capped at 5 per minute per source address**
  (`IPMIDECK_ATTEMPT_LIMIT`, `IPMIDECK_ATTEMPT_WINDOW`). A slot is consumed whether or not the
  password turns out to be right, so holding a valid one is not a way around the limit, and the
  cap deliberately leaves the per-account failure counter alone — otherwise traffic from a
  single address would lock the operator out of their own account. The cap counts per source
  address as the app sees it: behind a reverse proxy, list the proxy in `forwarded_allow_ips`,
  otherwise every client shares the proxy's address and one party's failed attempts hold
  everyone off, a correct password included, until the window ends.
- **The telemetry WebSocket now refuses a handshake from another site**, ends the socket when
  the session behind it expires or is revoked (re-checked every 60 seconds) rather than
  streaming to it until the browser goes away, and applies the same `server.trusted_origins`
  setting as the HTTP guard for proxied deployments.
- **A misbehaving BMC can no longer make the application allocate without bound** — responses
  are size-limited before they are parsed.

### Added

- **HTTPS with no manual certificate step.** Set `https: true` (or `IPMIDECK_SERVER_HTTPS=true`,
  or use the Network card in Settings) and restart: if no certificate is configured, one is
  generated at `<data_dir>/certs/` covering `localhost`, this machine's hostname and its
  addresses. Browsers still warn that the issuer is unknown — the traffic is encrypted, only the
  identity is unverified; the README lists how to import it. If a certificate cannot be set up
  the app starts over plain HTTP rather than refusing to start, and logs that it did.
- **See what changed, from inside the app.** The version in the sidebar now shows the version
  you are actually running and opens the full release history over whatever page you are on.
  The history ships inside the package and is read from disk, so it works on an air-gapped
  install with no network at all. A security release is marked as one.
- **Optional update checks, asked once during first-run setup.** Setup asks whether IPMIDeck may
  look up published versions, as one question you confirm (the box starts ticked). Nothing is
  contacted before you answer, and nothing ever if you untick it. With it on, it checks at
  start-up and once a day and stays silent unless there is genuinely something newer; it can be
  turned off at any time under **Settings → About**. There is also a **Check now** button there,
  and the console `[g]` key now performs a real check instead of printing a promise that one
  would arrive in a later release.

  The request is a single `GET` carrying the product name and your version and nothing else: no
  identifier, no hostname, nothing about your servers. Like any request, it shows the endpoint
  your public IP address. It is logged verbatim before the socket opens so you can audit it
  yourself. A PyPI or Docker install that finds a newer version makes one more such request, to
  GitHub, to learn whether it is a security release. Nothing is downloaded or installed. The
  lookup uses the standard library only — the runtime dependencies still contain no HTTP client.

  Setting `updates.enabled: false` in `config.yaml` (or `IPMIDECK_UPDATES_ENABLED=false`) turns
  it off outright: the endpoints that could open a socket are not registered at all and the
  periodic check never starts, regardless of what was answered during setup. The version
  history keeps working.
- The startup log now names the running version and where to read what changed, so a report
  from `docker logs` identifies itself.

### Fixed

- **The container can serve HTTPS.** The image started the web server directly, and a
  certificate can only be supplied as that server is built, so `https` was silently ignored in
  Docker while the startup log still announced `https://`. The image now starts through the
  `ipmideck` command, which resolves the certificate, and its health check follows whichever
  scheme is live. The startup line reports the scheme actually served, and says so explicitly
  when `https` is configured but no certificate reached the server. Overriding the container's
  `command:` to invoke `uvicorn` directly still serves cleartext.
- **A malformed fan curve no longer stops FanPilot from controlling other servers.** Curve
  points are stored as free-form JSON, and one unreadable curve aborted every control pass at
  the same server, leaving every server after it with no curve evaluation, no fail-safe and no
  auto-recovery — fans held at their last commanded speed while temperatures rose. An unusable
  curve now resolves to 100% and failures are contained to a single server. That includes
  `NaN` and `Infinity`, which the API accepted in a curve point and which then broke both the
  control pass and the profile listing; they are now refused with a clear error, as is a
  non-finite hysteresis or safety threshold.
- **Fans held at 100% by an unusable curve now come with the reason.** FanPilot reports it
  once per server and profile, as a warning notification and a command-log entry: the curve
  has no points, a point's temperature or speed is missing or not a number, a value is `NaN`
  or `Infinity`, or the stored curve is not valid JSON. A curve that is not valid JSON used to
  be skipped with the fans left at their last speed; it now gets the same 100% as any other
  unusable curve. The notice re-arms once the curve is fixed.
- **The container restarts cleanly under host networking.** The single-instance check refused
  to start while the previous run's connections were still closing (up to about a minute
  after a restart). It now reports only a port something is actually listening on. It also
  starts on an IPv6 address instead of calling a free port busy, and on Windows it now sees
  an instance already listening on `0.0.0.0`.
- **The container health check probes the port the app listens on.** It read
  `IPMIDECK_SERVER_PORT`, but the image always listens on 3000, so setting that variable made a
  working container report unhealthy. It now reads the port the app was started with, so a
  command overridden with another `--port` (the way to move the port under host networking)
  is followed too.
- **A malformed `Origin` or `Referer` header is refused** instead of answering with a server
  error, and an empty or non-text entry in `trusted_origins` is ignored instead of failing the
  first proxied request.
- **An undecryptable stored credential is reported with a clear message** by the connection
  test and power commands, instead of the raw cryptography error.

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
