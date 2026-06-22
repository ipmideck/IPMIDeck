# IPMIDeck

**Web-based IPMI management platform — monitor sensors, control fans, manage power, all from your browser.**

IPMIDeck is a self-hosted dashboard that connects to your servers' BMC (Baseboard Management Controller) via IPMI. It provides real-time sensor monitoring, intelligent fan curve control (FanPilot), remote power management, and hardware event logs — no CLI required.

> Looking for the legacy V1 (simple fan speed control)? See the [`v1-legacy`](../../tree/v1-legacy) branch.

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

```bash
docker run -d \
  --name ipmideck \
  --network host \
  -v ipmideck-data:/data \
  ipmideck/ipmideck:latest
```

Open `http://<your-ip>:3000` and follow the setup wizard.

> `--network host` is required for the container to reach BMCs on your local network via UDP 623.

### pip

```bash
pip install ipmideck
ipmideck serve
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

See [`PRD.md`](PRD.md) for the full configuration reference.

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
│   ├── main.py              # FastAPI app entry point
│   ├── ipmi/                # IPMI engine + command builders
│   ├── fanpilot/            # Fan curve engine + async loop
│   ├── sensors/             # Sensor polling loop
│   ├── api/                 # REST route handlers
│   ├── ws/                  # WebSocket broadcast
│   └── models/              # Pydantic schemas
├── frontend/
│   ├── src/
│   │   ├── pages/           # Dashboard, FanPilot, SEL, FRU, Settings
│   │   ├── components/      # Charts, controls, layout
│   │   └── hooks/           # WebSocket, sensors, auth
│   └── vite.config.ts
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── PRD.md
```

---

## Security

- Local authentication with bcrypt password hashing
- JWT session tokens with configurable expiry
- BMC credentials encrypted at rest (AES-256, key derived via PBKDF2)
- No external network dependencies — fully offline capable
- ipmitool args passed as list (no shell injection possible)

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

[ISC](LICENSE)

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
