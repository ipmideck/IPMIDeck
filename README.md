<h1 align="center">🖥️ IPMIDeck</h1>

<p align="center"><strong>Web-based IPMI management platform — monitor sensors, control fans, manage power, all from your browser.</strong></p>

<p align="center">
  <img alt="IPMIDeck dashboard home — live multi-server sensor monitoring with temperature, fan, power and energy widgets" src="docs/screenshots/dashboard.png">
</p>

<p align="center">
  <a href="https://www.python.org/"><img alt="Python 3.11+" src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white"></a>
  <a href="LICENSE"><img alt="License: Apache 2.0" src="https://img.shields.io/badge/License-Apache%202.0-D22128?logo=apache&logoColor=white"></a>
  <a href="https://hub.docker.com/r/devluigi06/ipmideck"><img alt="Docker Hub pulls" src="https://img.shields.io/docker/pulls/devluigi06/ipmideck?logo=docker&logoColor=white&label=Docker%20pulls&color=2496ED"></a>
  <a href="https://pypi.org/project/ipmideck/"><img alt="PyPI version" src="https://img.shields.io/pypi/v/ipmideck?logo=pypi&logoColor=white&label=PyPI&color=FFD43B"></a>
  <img alt="Supported BMCs: Dell, Supermicro, IBM, HPE, Lenovo, Generic" src="https://img.shields.io/badge/BMC-Dell%20%7C%20Supermicro%20%7C%20IBM%20%7C%20HPE%20%7C%20Lenovo%20%7C%20Generic-06B6D4">
</p>

<p align="center"><strong>Documentation:</strong> <a href="https://docs.ipmideck.com">docs.ipmideck.com</a></p>

<p align="center">
  <a href="#features">Features</a> •
  <a href="#quick-start">Quick Start</a> •
  <a href="#documentation">Documentation</a> •
  <a href="#configuration">Configuration</a> •
  <a href="#supported-hardware">Supported Hardware</a>
</p>

IPMIDeck is a self-hosted dashboard that connects to your servers' BMC (Baseboard Management Controller) via IPMI. It provides real-time sensor monitoring, intelligent fan curve control (FanPilot), remote power management, and hardware event logs — no CLI required.

---

## Features

### Sensor Monitoring
- Real-time temperature, fan RPM, voltage, and power consumption
- Live charts with historical data (up to 1 year)
- Configurable alert thresholds with browser notifications

### FanPilot — Intelligent Fan Control
- Visual drag-and-drop fan curve editor
- Built-in profiles: Silent, Balanced, Performance, Full Speed, Custom
- Configurable hysteresis to prevent fan oscillation
- Safety override: fans go to 100% above critical temperature
- Autonomous loop — works independently of the dashboard

![IPMIDeck FanPilot profile settings — source sensor, hysteresis, and the 85°C safety threshold that forces fans to 100%](docs/screenshots/safety-override.png)

### Power Control
- Power On, Soft Off, Hard Off, Reset, Power Cycle
- Real-time power status indicator
- Confirmation dialogs for destructive actions
- Full command audit log

![IPMIDeck power control widget — live power draw with history graph and On / Soft Off / Hard Off / Reset / Cycle actions](docs/screenshots/power-control.png)

### System Event Log (SEL)
- View BMC hardware event log with severity filtering
- Search, date range filters, export to CSV/JSON

### Hardware Inventory (FRU)
- Serial numbers, part numbers, manufacturer info
- Board, chassis, and product data at a glance

### Multi-Server Dashboard
- Manage multiple BMCs from a single instance
- Panoramic view with status overview of all servers

![IPMIDeck server switcher popover listing multiple servers across vendors from a single instance](docs/screenshots/server-switcher.png)

---

## Quick Start

### Docker (recommended)

Pull from Docker Hub (primary registry):

```bash
docker pull devluigi06/ipmideck:latest

# Linux (reaches BMCs on your LAN via UDP 623):
docker run -d --name ipmideck --network host \
  -v ipmideck-data:/data \
  devluigi06/ipmideck:latest

# Windows / macOS (Docker Desktop has no host networking — map the port instead):
docker run -d --name ipmideck -p 3000:3000 \
  -v ipmideck-data:/data \
  devluigi06/ipmideck:latest
```

Or with Docker Compose:

```bash
docker compose up -d                                  # pull&go (docker-compose.yml)
docker compose -f docker-compose.dev.yml up --build   # build from source
```

Open `http://<your-ip>:3000` and follow the setup wizard.

> The container runs as an unprivileged user (uid/gid 1000), not root. A named volume or an
> existing data directory created by an earlier version is adopted automatically on first
> start — no manual `chown`. The only case needing a one-time host-side
> `chown -R 1000:1000 <dir>` is a bind mount on a filesystem that refuses to change ownership
> (a read-only mount, NFS without `no_root_squash`, or CIFS with a fixed uid/gid). The
> container still starts in that case and logs a warning rather than failing.

> `--network host` (Linux) lets the container reach BMCs on your local network via UDP 623.
> On Windows/macOS use `-p 3000:3000`.

### pip

```bash
pip install ipmideck
ipmideck start
```

Requires `ipmitool` installed on the system.

---

## Documentation

Full documentation lives at **[docs.ipmideck.com](https://docs.ipmideck.com/en/getting-started)** — start with the [Getting Started guide](https://docs.ipmideck.com/en/getting-started). The docs cover installation, first-run setup, per-vendor **Enable IPMI** guides (Dell iDRAC, HPE iLO, Supermicro, Lenovo XCC, IBM IMM), configuration, the CLI and interactive console, the FAQ, and troubleshooting.

---

## Tech Stack

| Component | Technology |
|---|---|
| Backend | Python / FastAPI / Uvicorn |
| Frontend | React / Vite / TypeScript / Recharts |
| Styling | Tailwind CSS |
| Database | SQLite (aiosqlite) |
| IPMI | ipmitool (subprocess) |
| Packaging | Docker / pip |

---

## Configuration

Configuration is auto-generated at first run at `/data/config.yaml` (Docker / Linux) or `./data/config.yaml` (Windows). Override the data directory with `IPMIDECK_DATA_DIR`.

A documented subset of settings can be overridden with `IPMIDECK_`-prefixed environment variables:

```bash
IPMIDECK_SERVER_PORT=8080
IPMIDECK_SERVER_HTTPS=true
IPMIDECK_IPMI_POLL_INTERVAL=30
IPMIDECK_LOGGING_LEVEL=info
IPMIDECK_DATA_RETENTION_DAYS=180
```

In the Docker image the app always listens on port 3000 inside the container: the image starts
it with `--port 3000`, which takes precedence over `IPMIDECK_SERVER_PORT` and `config.yaml`.
Change the published port with the port mapping (`-p 8080:3000`) instead. Under
`--network host` a port mapping has no effect, so override the command instead, for example
`ipmideck --host 0.0.0.0 --port 8080 start`; the container's health check follows the port
given there.

The `config.yaml` written on first run covers the common settings, not every key — read it for
what it contains, and add the rest by hand if you need them. The same settings are also
editable at runtime from the in-app **Settings** page.

Note that whether authentication is enabled is **not** a config-file setting. It is stored in
the database and changed from the Security settings, so write access to `config.yaml` cannot be
used to turn the login off.

---

## Interactive Console

Launched on a host with an attached terminal (a TTY — e.g. `ipmideck start` run directly, not under Docker, systemd, or a pipe), IPMIDeck opens an interactive operator console: a pinned header with keybindings above a live, streaming log. From it you can cycle log verbosity, inspect active sessions and configured servers, print the access URL, change the bind address, and restart or quit — without leaving the terminal.

![IPMIDeck interactive operator console — pinned header with keybindings and a live log, plus the configured-servers view](docs/screenshots/console.png)

Keys: `[v]` verbosity · `[c]` sessions · `[s]` servers · `[u]` url · `[g]` update · `[b]` change bind · `[r]` restart · `[q]` quit · `[ESC]` back. The console is not shown when IPMIDeck runs under Docker, systemd, or with piped output — there it logs plainly to stdout.

> The hosts shown are RFC5737 documentation addresses, not real servers.

See the [Interactive Console docs](https://docs.ipmideck.com/en/console) for full details.

---

## Screenshots

### FanPilot — visual fan curve editor

![IPMIDeck FanPilot page with the drag-and-drop fan curve editor](docs/screenshots/fanpilot.png)

### System Event Log — BMC hardware events

![IPMIDeck System Event Log with severity filtering](docs/screenshots/event-log.png)

### Hardware Inventory (FRU) — board, chassis, and product data

![IPMIDeck Hardware Inventory page showing FRU board, chassis, and product identifiers](docs/screenshots/fru.png)

> Hardware identifiers are synthetic and the hosts shown are RFC5737 documentation addresses.

---

## Development

### Prerequisites

- Python 3.11+
- Node.js 20+ (for frontend development)
- ipmitool

### Setup

```bash
git clone https://github.com/ipmideck/IPMIDeck.git
cd IPMIDeck

# Backend — run from the repo root (pyproject.toml lives here)
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows
pip install -e ".[dev]"

# Frontend
cd frontend
npm install
npm run dev
```

### Run

```bash
# Backend — from the repo root (serves API + static frontend build)
uvicorn backend.main:app --reload --port 3000
# or:  python -m backend.main --reload
# or:  ipmideck start --reload   (after `pip install -e ".[dev]"`)

# Frontend dev server (with HMR, proxies API to backend)
cd frontend
npm run dev
```

---

## Project Structure

```
ipmideck/
├── backend/
│   ├── main.py              # FastAPI app + lifespan + CLI entry point
│   ├── console.py           # interactive TTY operator console
│   ├── core/                # database, auth, crypto, config, branding, events,
│   │                        #   websocket, modules (loader), ipmi_service, ipmi_demo
│   ├── api/                 # auth / server / dashboard / system / module routes
│   ├── models/              # Pydantic schemas
│   ├── modules/             # self-contained feature modules
│   │   │                    #   (manifest + routes + tasks + migrations each)
│   │   ├── sensors/
│   │   ├── fanpilot/        #   + engine.py (curve / hysteresis / safety override)
│   │   ├── power/
│   │   ├── sel/
│   │   └── fru/
│   └── static/              # compiled React SPA (build artifact — do not hand-edit)
├── frontend/
│   ├── src/
│   │   ├── pages/           # Dashboard, FanPilot, SEL, FRU, Settings, Login, Setup
│   │   ├── components/      # common/, dashboard/, layout/
│   │   ├── modules/         # per-module widgets (sensors, fanpilot, power)
│   │   ├── stores/          # Zustand stores
│   │   ├── hooks/           # useWebSocket, useKeyboardShortcuts, …
│   │   ├── i18n/locales/    # 12 language catalogs
│   │   ├── api/             # HTTP client
│   │   ├── lib/
│   │   └── styles/
│   └── vite.config.ts
├── scripts/                 # rebuild-spa, check-spa-built, check-i18n-parity,
│                            #   check-wheel, lint-workflows, smoke-docker
├── tests/                   # unit/, integration/, fixtures/ipmi/
├── Dockerfile
├── docker-compose.yml
├── docker-compose.dev.yml
├── .dockerignore
└── pyproject.toml
```

---

## Security

- Local authentication with bcrypt password hashing
- Session tokens signed with HMAC-SHA256 using a per-install secret, with configurable
  expiry (`IPMIDECK_AUTH_SESSION_EXPIRY` / the `auth.session_expiry` config key — e.g. `24h`,
  `90m`, `1h`; default `24h`; values above `30d` are capped at 30 days, with a warning in the
  log). The signature is what makes a token trustworthy: the payload
  itself is base64url-encoded JSON, so treat the cookie as readable by whoever holds it
- BMC credentials encrypted at rest with AES-256-GCM, which detects tampering as well as
  concealing the value. The 32-byte key is randomly generated and stored in
  `<data_dir>/encryption.key` — deliberately **outside** the database, so in normal operation
  a stolen DB alone decrypts nothing (back the key file up separately). Credentials written by
  earlier versions (AES-256-CBC, unauthenticated) are converted automatically on the first
  start after upgrading; see the changelog for the copies it leaves behind. The one exception
  is an installation upgraded from a version that kept the key in the database and whose
  migration was interrupted: until it completes, the in-database key is still usable
- BMC passwords are never placed on the command line — `ipmitool` reads them from the environment
  (`-E` / `IPMITOOL_PASSWORD`), so they never appear in `ps`
- No external network dependencies — fully offline capable
- ipmitool arguments are passed as a list, never through a shell (no shell-injection surface)
- Optional HTTPS/TLS for the dashboard, with one-click self-signed certificate generation
- Credential checks are capped at 5 per minute per source address
  (`IPMIDECK_ATTEMPT_LIMIT`, `IPMIDECK_ATTEMPT_WINDOW` in seconds). A slot is consumed whether
  or not the password turns out to be right, and the cap deliberately does not touch the
  per-account failure counter, so traffic from one address cannot lock the operator out.
  Behind a reverse proxy, list it in `forwarded_allow_ips` (see
  [Behind a reverse proxy](#behind-a-reverse-proxy)): otherwise every client shares the proxy's
  address and one party's failed attempts hold everyone off until the window ends
- State-changing requests (`POST`/`PUT`/`PATCH`/`DELETE`) are refused when the browser reports
  an origin other than the one the dashboard is served from, including a different port on the
  same host. Requests with no `Origin` and no `Referer` — the CLI, the container health check,
  scripted integrations — are unaffected
- Defensive response headers on everything served: `frame-ancestors 'none'` (plus
  `X-Frame-Options: DENY`) to keep the dashboard out of a hostile iframe, `nosniff`,
  `Referrer-Policy: no-referrer`, and HSTS when the request itself arrived over TLS

### Behind a reverse proxy

Two settings exist for proxied deployments, both under `server:` in `config.yaml`:

| Setting | When you need it |
|---------|------------------|
| `forwarded_allow_ips` | Your TLS proxy is not on `127.0.0.1`. Without it the forwarded scheme is discarded and the session cookie loses its `Secure` flag. |
| `trusted_origins` | Your proxy does not pass the browser's `Host` through. |

`trusted_origins` is the one that bites. nginx does **not** forward the original `Host` unless
you add `proxy_set_header Host $host;`, so the guard above compares the browser's
`https://ipmi.example.com` against the `localhost:3000` it was handed, and every save fails with
`Cross-origin request rejected`. Either fix the proxy header or name the real address:

```yaml
server:
  trusted_origins:
    - https://ipmi.example.com
```

An entry with a scheme requires that scheme to match, so listing an `https` origin does not
also trust its cleartext twin. Origins that are neither this server's own nor on the list are
still rejected. Both settings also take an environment variable
(`IPMIDECK_SERVER_FORWARDED_ALLOW_IPS`, `IPMIDECK_SERVER_TRUSTED_ORIGINS` — the latter
comma-separated).


![IPMIDeck Settings — optional HTTPS/TLS with one-click self-signed certificate generation](docs/screenshots/settings-https.png)

![IPMIDeck Settings — local authentication enabled, with a confirm-with-password flow to disable it](docs/screenshots/settings-password.png)

### HTTPS

Over plain HTTP the session cookie and every BMC password typed into the dashboard cross the
network in the clear. On a trusted LAN that may be an acceptable trade, and it stays the
default so nothing changes under you — but it is worth turning off.

Set `https: true` in `config.yaml` (or `IPMIDECK_SERVER_HTTPS=true`, or the Network card in
Settings) and restart. If no certificate is configured, one is generated for you at
`<data_dir>/certs/server.crt` and used automatically. It covers `localhost`, this machine's
hostname and its addresses, so it works whether you reach the dashboard by name or by IP.

This works in Docker too — the image starts through the `ipmideck` command, which is what
resolves the certificate. A certificate can only be given to the web server as it starts, so a
container whose `command:` is overridden to run `uvicorn` directly serves cleartext however the
configuration reads. The startup log always states the scheme it actually came up on, and says
so explicitly when `https` is on but no certificate reached the server.

**Your browser will show a security warning the first time.** Nobody signed the certificate —
there is no certificate authority involved — so the browser cannot vouch for *who* you are
talking to. The traffic is encrypted either way; only the identity is unverified. On a LAN
you can click through ("Advanced" → "Proceed"), or remove the warning for good by importing
the certificate:

| Platform | How |
|---|---|
| Windows | `certutil -addstore -f Root <data_dir>\certs\server.crt` (as administrator) |
| macOS | Open `server.crt` in Keychain Access → System → set it to **Always Trust** |
| Linux | Copy to `/usr/local/share/ca-certificates/` and run `sudo update-ca-certificates` |
| Firefox | Keeps its own store: Settings → Privacy & Security → Certificates → Import |

**To use your own certificate instead** — from your internal CA, or Let's Encrypt — point
`cert_file` and `key_file` at the PEM pair. Files you supply are never overwritten.

```yaml
server:
  https: true
  cert_file: /etc/ssl/ipmideck/fullchain.pem
  key_file: /etc/ssl/ipmideck/privkey.pem
```

**Or terminate TLS at a reverse proxy** (Caddy, nginx, Traefik) and leave IPMIDeck on HTTP
bound to `127.0.0.1`. If you do, make sure the proxy forwards the original scheme, otherwise
the session cookie is not marked secure. A proxy that is not on `127.0.0.1` must also be listed
in `forwarded_allow_ips`, and one that rewrites the `Host` header needs its public origin in
`trusted_origins` — see [Behind a reverse proxy](#behind-a-reverse-proxy).

To regenerate, delete `<data_dir>/certs/` and restart, or run `ipmideck --gen-cert`.
`server.key` is as sensitive as `encryption.key` — protect and back it up the same way.

If a certificate cannot be set up at all, IPMIDeck logs the reason and starts over plain HTTP
rather than refusing to start: being locked out of your own dashboard is worse than the
warning you were already living with.

---

## Supported Hardware

Sensor monitoring, power control, SEL and FRU work on **any** server with an IPMI 2.0 BMC.

**Fan control (FanPilot) is vendor-specific.** The table below is the honest support matrix — it
mirrors the vendor profiles the app actually ships, and the same tier badges appear in the vendor
picker when you add a server:

| Vendor | Fan control | Tier | Notes |
|---|---|---|---|
| **Dell PowerEdge** (iDRAC) | Yes | Tested | Raw iDRAC fan commands, validated on real hardware (PowerEdge R720) |
| **Supermicro** (X10+) | Yes | Experimental | Both fan zones |
| **IBM System x** (IMM) | Yes | Experimental | Dual fan bank |
| **HPE ProLiant** (iLO) | No | Monitoring-only | iLO exposes no IPMI fan-control interface |
| **Lenovo ThinkSystem** (XCC) | No | Monitoring-only | No reliable in-band restore path |
| **Generic / unknown BMC** | No | Monitoring-only | Never issues raw vendor writes it cannot verify |

Monitoring-only vendors still get full sensor, power, SEL and FRU support — FanPilot simply leaves
their fans under BMC control rather than sending raw commands it cannot confirm.

---

## License

[Apache-2.0](https://github.com/ipmideck/IPMIDeck/blob/main/LICENSE)

---

## Author

**Luigi Tanzillo** — [github.com/dev-luigi](https://github.com/dev-luigi)

---

## Disclaimer

This tool is provided as-is for managing IPMI-enabled servers. Use at your own risk. Improper fan control can damage hardware. Always test in a non-production environment first. The author is not responsible for any damage caused by misuse of this application.

---

## Star History

<a href="https://www.star-history.com/?repos=ipmideck%2FIPMIDeck&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=ipmideck/IPMIDeck&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=ipmideck/IPMIDeck&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=ipmideck/IPMIDeck&type=date&legend=top-left" />
 </picture>
</a>
