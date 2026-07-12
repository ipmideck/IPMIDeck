# IPMIDeck

**Web-based IPMI management platform — monitor sensors, control fans, manage power, all from your browser.**

IPMIDeck is a self-hosted dashboard that connects to your servers' BMC (Baseboard Management Controller) via IPMI. It provides real-time sensor monitoring, intelligent fan curve control (FanPilot), remote power management, and hardware event logs — no CLI required.

> Looking for the legacy V1 (simple fan speed control)? See the [`v1-legacy`](https://github.com/ipmideck/IPMIDeck/tree/v1-legacy) branch.

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

### Power Control
- Power On, Soft Off, Hard Off, Reset, Power Cycle
- Real-time power status indicator
- Confirmation dialogs for destructive actions
- Full command audit log

### System Event Log (SEL)
- View BMC hardware event log with severity filtering
- Search, date range filters, export to CSV/JSON

### Hardware Inventory (FRU)
- Serial numbers, part numbers, manufacturer info
- Board, chassis, and product data at a glance

### Multi-Server Dashboard
- Manage multiple BMCs from a single instance
- Panoramic view with status overview of all servers

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

> `--network host` (Linux) lets the container reach BMCs on your local network via UDP 623.
> On Windows/macOS use `-p 3000:3000`.

### pip

```bash
pip install ipmideck
ipmideck start
```

Requires `ipmitool` installed on the system.

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

Configuration is auto-generated at first run in `/data/config.yaml` (Docker) or `~/.ipmideck/config.yaml` (pip).

Every setting can be overridden with environment variables using the `IPMIDECK_` prefix:

```bash
IPMIDECK_SERVER_PORT=8080
IPMIDECK_FANPILOT_SAFETY_THRESHOLD=90
IPMIDECK_DATA_RETENTION_DAYS=180
```

Every key is written to that `config.yaml` on first run — read it for the full list. The same
settings are also editable at runtime from the in-app **Settings** page.

---

## Screenshots

*Coming soon*

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

# Backend
cd backend
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows
pip install -e ".[dev]"

# Frontend
cd ../frontend
npm install
npm run dev
```

### Run

```bash
# Backend (serves API + static frontend build)
cd backend
uvicorn main:app --reload --port 3000

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
- Opaque session tokens, HMAC-SHA256 signed with a per-install secret, with configurable expiry
- BMC credentials encrypted at rest with AES-256-CBC. The 32-byte key is randomly generated and
  stored in `<data_dir>/encryption.key` — deliberately **outside** the database, so a stolen DB
  alone decrypts nothing (back the key file up separately)
- BMC passwords are never placed on the command line — `ipmitool` reads them from the environment
  (`-E` / `IPMITOOL_PASSWORD`), so they never appear in `ps`
- No external network dependencies — fully offline capable
- ipmitool arguments are passed as a list, never through a shell (no shell-injection surface)

---

## Supported Hardware

Works with any server supporting IPMI 2.0:

- **Dell PowerEdge** — R620, R630, R640, R650, R720, R730, R740, R750 and more
- **Supermicro** — All models with IPMI BMC
- **HPE ProLiant** — Models with iLO (support coming in Phase 3)
- **Lenovo ThinkSystem** — Models with XCC
- **IBM System X** — Models with IMM

> Fan curve control (FanPilot) currently supports Dell iDRAC raw commands. Supermicro and HPE support is on the roadmap.

---

## Roadmap

- [x] Project scaffolding + PRD
- [ ] Sensor polling + SQLite storage + live charts
- [ ] FanPilot fan curve editor + autonomous loop
- [ ] Power control
- [ ] SEL + FRU viewer
- [ ] Multi-server dashboard
- [ ] Supermicro + HPE vendor support
- [ ] Cloud edition (relay + agent + E2E encryption)

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
