# IPMILink — Product Requirements Document

**Self-Hosted Edition (Cloud-Ready)**

Version: Draft 1.0
Date: 2026-03-26
Author: Luigi Tanzillo

---

## 1. Project Overview

### 1.1 What is IPMILink

IPMILink is a web-based IPMI management platform that lets users monitor sensors, control fan speeds with custom curves, manage power states, and inspect hardware logs — all from a single modern dashboard. It runs as a self-hosted all-in-one application on the user's local network, with an architecture designed for a future cloud/relay edition.

### 1.2 Problem

IPMI management today requires SSH access, ipmitool CLI knowledge, and dealing with vendor-specific web interfaces (iDRAC, iLO) that are limited, outdated, and impossible to unify across multiple servers. There is no modern, self-hosted solution that combines real-time monitoring, intelligent fan control, and power management in a single dashboard.

### 1.3 Solution

A single Docker container (or pip install) that serves a modern dark-themed dashboard accessible from any browser on the LAN. The backend communicates directly with BMCs via ipmitool, stores sensor history in SQLite, and pushes live data to the frontend via WebSocket.

### 1.4 Target Users

- Homelab enthusiasts managing 1-10 bare-metal servers
- System administrators in small/medium environments
- Anyone with IPMI-capable hardware who wants a GUI alternative to CLI

---

## 2. Architecture

### 2.1 Self-Hosted (Current Target)

Single process, all-in-one. The backend serves the frontend as static files.

```
+---------------------------------------------------+
|              IPMILink Self-Hosted                  |
|                                                   |
|  +-------------+    +-------------------------+   |
|  |  Frontend   |    |       Backend           |   |
|  |  (React     |<-->|   (Python / FastAPI)    |   |
|  |   static    |    |                         |   |
|  |   build)    |    |   +------------------+  |   |
|  +-------------+    |   | IPMIService      |  |   |
|                     |   | (abstraction)    |  |   |
|                     |   +------------------+  |   |
|                     |   +------------------+  |   |
|                     |   | FanPilot Loop    |  |   |
|                     |   | (async task)     |  |   |
|                     |   +------------------+  |   |
|                     |   +------------------+  |   |
|                     |   | SQLite DB        |  |   |
|                     |   +------------------+  |   |
|                     +-------------------------+   |
+---------------------------------------------------+
          |
          | IPMI (RMCP+ / UDP 623)
          v
    +--------+  +--------+  +--------+
    | BMC 1  |  | BMC 2  |  | BMC N  |
    +--------+  +--------+  +--------+
```

### 2.2 Cloud-Readiness Strategy

The architecture is designed so that the transition to a cloud edition requires **no changes** to the frontend or API layer. The key abstraction is `IPMIService`:

| Mode | IPMIService behavior |
|---|---|
| **Self-Hosted** | Calls ipmitool directly via subprocess on the local machine |
| **Cloud (future)** | Sends commands to the Cloud Relay via WebSocket, which forwards them to the remote Agent |

What stays the same across both editions:
- All React components and dashboard UI (100%)
- All REST API endpoint signatures (100%)
- WebSocket message format (100%)
- SQLite schema for sensor data (95%)
- FanPilot algorithm and fan curve logic (100%)

What changes for Cloud edition (future work, not in scope now):
- `IPMIService` implementation swapped from local to remote
- Add Cloud Relay (WebSocket router + auth)
- Add Agent (standalone Python process with IPMIService local)
- Add OAuth / multi-user auth
- Add E2E encryption (AES-256-GCM)

### 2.3 Communication Flow

```
Browser (LAN)
    |
    |-- REST API (HTTP) --> FastAPI --> IPMIService --> ipmitool --> BMC
    |
    |-- WebSocket (WS) <-- FastAPI <-- Sensor Loop <-- ipmitool <-- BMC
```

- REST for commands (power, fan speed, config CRUD)
- WebSocket for live sensor streaming (push model)
- Both on the same port (default: 3000)

---

## 3. Tech Stack

| Component | Technology | Why |
|---|---|---|
| **Backend** | Python 3.11+ / FastAPI / Uvicorn | Async native, WebSocket built-in, serves static files |
| **Frontend** | React 18 + Vite + TypeScript | Fast build, HMR, same bundle for self-hosted and cloud |
| **Charts** | Recharts | React-native charting, composable, good for time-series |
| **Styling** | Tailwind CSS | Utility-first, easy to enforce dark theme consistently |
| **Database** | SQLite + aiosqlite | Zero config, async, embedded, handles millions of rows |
| **IPMI** | ipmitool (subprocess) | Universal compatibility. python-ipmi as future optimization |
| **WebSocket** | FastAPI WebSocket | Same port as HTTP, zero extra config |
| **Packaging** | Docker (primary) / pip (secondary) | Docker with `--network host` for BMC access |

### 3.1 Why NOT Next.js

Next.js adds SSR complexity unnecessary for a LAN dashboard. Vite produces a static bundle that FastAPI serves directly. No Node.js runtime needed in production. Same React code can be reused if Next.js is ever needed for a cloud landing page.

### 3.2 Why NOT Node.js Backend

Python has superior ipmitool integration (subprocess is native), the existing V1 IPMI logic translates directly, and FastAPI's async model is ideal for concurrent sensor polling across multiple BMCs. Using Python for both self-hosted and the future cloud agent eliminates a language split.

---

## 4. Module Specifications

### 4.1 Sensor Monitoring

**Purpose:** Real-time and historical visualization of all BMC sensor data.

#### 4.1.1 Sensor Types

| Sensor | Source | Unit | Typical Range |
|---|---|---|---|
| CPU Temperature | `ipmitool sdr type Temperature` | Celsius | 30-95 |
| Inlet/Outlet Temp | same | Celsius | 20-50 |
| Fan RPM | `ipmitool sdr type Fan` | RPM | 0-18000 |
| Voltage (12V, 5V, 3.3V, Vcore) | `ipmitool sdr type Voltage` | Volts | varies |
| Power Consumption | `ipmitool sdr type "Current"` or `dcmi power reading` | Watts | 50-800 |
| PSU Status | `ipmitool sdr type "Power Supply"` | Status | Present/Absent/Fault |
| Chassis Intrusion | `ipmitool sdr type "Physical Security"` | Status | OK/Breached |

#### 4.1.2 Polling Loop

- Async background task, runs every **5 seconds** (configurable)
- Executes `ipmitool -I lanplus -H <ip> -U <user> -P <pass> sdr elist`
- Parses output line by line (format: `Name | hex_id | status | entity | value`)
- Stores parsed readings in SQLite `sensor_readings` table
- Broadcasts latest readings to all connected WebSocket clients
- Per-server loop: each configured BMC has its own polling task

#### 4.1.3 Frontend Charts

- **Live view:** Last 5 minutes, updates every poll cycle, smooth line chart
- **Historical view:** Time range selector — 1h, 6h, 24h, 7d, 30d, custom
- **Chart types:**
  - Temperature line chart (multiple sensors overlaid, color-coded)
  - Fan RPM line chart (overlaid with temperature for correlation)
  - Power consumption area chart
  - Voltage sparklines (compact, in a grid)
- **Alerts:** Visual badge + optional browser notification when a sensor exceeds configured threshold
- Library: Recharts `<LineChart>`, `<AreaChart>`, `<ResponsiveContainer>`

#### 4.1.4 Data Retention

- Default: 365 days
- Configurable in `config.yaml`
- Automatic cleanup: daily async task deletes rows older than retention period
- Storage estimate: ~50MB/year per server at 5s interval with 10 sensors

---

### 4.2 FanPilot (Intelligent Fan Control)

**Purpose:** Automated fan speed control based on custom temperature curves, with safety overrides.

#### 4.2.1 Fan Curve Editor (Frontend)

- Interactive SVG/Canvas chart where:
  - X axis = temperature (source sensor, e.g., CPU Temp), range 20-100 C
  - Y axis = fan speed percentage, range 0-100%
- **Drag-and-drop control points** on the curve
  - Minimum 2 points, maximum 10
  - Add point: click on curve area
  - Remove point: right-click or drag to trash
  - Snap to grid (5 C / 5% increments, toggleable)
- **Interpolation mode:** Linear (default) or Smooth (cubic bezier)
- **Source sensor selector:** Dropdown to pick which temperature sensor drives the curve
- **Live preview line:** Shows current temperature as a vertical line on the chart, with the resulting fan speed highlighted

#### 4.2.2 Profiles

| Profile | Description | Preset Curve |
|---|---|---|
| **Silent** | Prioritize low noise | 20%@30C, 30%@50C, 60%@70C, 100%@85C |
| **Balanced** | Default, good compromise | 30%@30C, 50%@50C, 80%@70C, 100%@80C |
| **Performance** | Prioritize cooling | 50%@30C, 70%@50C, 90%@70C, 100%@75C |
| **Full Speed** | Always 100% | Flat line at 100% |
| **Custom** | User-defined | Saved per server |

- Profiles are saved in SQLite `fan_profiles` table
- Each server can have an active profile assigned
- Quick-switch between profiles from dashboard

#### 4.2.3 FanPilot Loop (Backend)

```
Every 5 seconds:
  1. Read current temperature from source sensor (already in polling loop)
  2. Look up fan curve for active profile
  3. Apply hysteresis:
     - If temp is RISING: use curve value directly
     - If temp is FALLING: only reduce fan speed if temp dropped
       by more than hysteresis threshold (default: 3 C)
  4. Apply safety override:
     - If temp >= safety_threshold (default: 85 C): set fans to 100%
     - Log safety event
  5. Send ipmitool commands:
     - raw 0x30 0x30 0x01 0x00  (enable manual fan control)
     - raw 0x30 0x30 0x02 0xff <hex_speed>  (set all fans)
  6. Store applied fan speed in sensor_readings for correlation charts
```

#### 4.2.4 IPMI Raw Commands (Dell-specific, extensible)

| Command | Raw | Purpose |
|---|---|---|
| Enable manual control | `raw 0x30 0x30 0x01 0x00` | Take over from BMC auto |
| Disable manual control | `raw 0x30 0x30 0x01 0x01` | Return to BMC auto |
| Set fan speed (all) | `raw 0x30 0x30 0x02 0xff <hex>` | Set all fans to % |

Note: These are Dell iDRAC-specific commands. Future versions will add support for Supermicro (`raw 0x30 0x70 0x66 0x01 0x00 <hex>`) and HPE iLO. The `IPMIService` abstraction will handle vendor-specific command mapping.

#### 4.2.5 Safety Requirements

- FanPilot loop runs **independently** of frontend/WebSocket connections
- If the backend process crashes, it MUST send `raw 0x30 0x30 0x01 0x01` (auto mode) on shutdown/signal handler
- Safety override cannot be disabled via UI — hardcoded behavior
- All fan speed changes are logged in `command_log` table

---

### 4.3 Power Control

**Purpose:** Remote power management of servers via IPMI.

#### 4.3.1 Commands

| Action | ipmitool command | Requires Confirmation |
|---|---|---|
| **Power On** | `chassis power on` | No |
| **Soft Power Off** | `chassis power soft` | Yes |
| **Hard Power Off** | `chassis power off` | Yes (double confirm) |
| **Reset** | `chassis power reset` | Yes |
| **Power Cycle** | `chassis power cycle` | Yes |
| **Status** | `chassis power status` | No (auto-polled) |

#### 4.3.2 Frontend UI

- Power status indicator: green circle (ON), red circle (OFF), yellow (unknown)
- Action buttons in a row: Power On, Soft Off, Hard Off, Reset, Cycle
- Destructive actions (Hard Off, Reset, Cycle) have red styling + confirmation modal
- Status is polled every 10 seconds alongside sensor data
- All actions logged with timestamp in command history

#### 4.3.3 Safety

- Hard Power Off requires typing "CONFIRM" in a text input (not just clicking OK)
- Rate limiting: max 1 power command per 5 seconds per server (prevent accidental double-clicks)
- Command audit log stored in SQLite

---

### 4.4 System Event Log (SEL) Viewer

**Purpose:** View and manage the BMC's hardware event log.

#### 4.4.1 Data Source

- `ipmitool sel elist` — full event log with decoded entries
- `ipmitool sel info` — log metadata (entries count, free space, last timestamp)

#### 4.4.2 Frontend UI

- Table view with columns: Date/Time, Sensor, Event Type, Description, Severity
- Severity badges: Info (blue), Warning (yellow), Critical (red)
- Filters: by severity, by sensor type, by date range
- Search: free text search across event descriptions
- Export: CSV and JSON download buttons
- Clear SEL button (with confirmation) — `ipmitool sel clear`

#### 4.4.3 Caching

- SEL is fetched on-demand (not continuously polled)
- Cached in SQLite `sel_cache` table per server
- Refresh button to re-fetch from BMC
- Auto-refresh interval: configurable (default: disabled)

---

### 4.5 Hardware Inventory (FRU) Viewer

**Purpose:** Display Field Replaceable Unit data from the BMC.

#### 4.5.1 Data Source

- `ipmitool fru print` — all FRU data

#### 4.5.2 Frontend UI

- Card-based layout showing:
  - **Board Info:** Manufacturer, Product Name, Serial, Part Number
  - **Chassis Info:** Type, Serial, Part Number
  - **Product Info:** Manufacturer, Name, Version, Serial, Asset Tag
- Read-only view (FRU data is not modifiable via IPMI in most cases)
- Copy-to-clipboard button for serial numbers
- Last fetched timestamp displayed

#### 4.5.3 Caching

- Fetched on first server connection and on manual refresh
- Cached in SQLite `fru_cache` table (FRU data rarely changes)

---

## 5. Dashboard Design

### 5.1 Visual Style: Dark Tech/Cyber

The dashboard follows a dark, high-contrast, server-monitoring aesthetic.

#### 5.1.1 Color Palette

| Role | Color | Hex |
|---|---|---|
| **Background (primary)** | Deep navy/charcoal | `#1e1e2e` |
| **Background (card/surface)** | Slightly lighter | `#252532` |
| **Background (input/elevated)** | Dark blue-grey | `#2a2a3e` |
| **Border** | Subtle grey | `#3a3a4a` |
| **Text (primary)** | Light grey | `#e0e0e0` |
| **Text (secondary/muted)** | Medium grey | `#a0a0a0` |
| **Accent (primary)** | Cyan | `#00d4ff` |
| **Accent (success)** | Neon green | `#00ff88` |
| **Accent (danger)** | Red | `#ff5555` |
| **Accent (warning)** | Amber | `#ffaa00` |

#### 5.1.2 Typography

- **Font:** `'Segoe UI', system-ui, -apple-system, sans-serif`
- **Monospace (values/data):** `'JetBrains Mono', 'Fira Code', 'Courier New', monospace`
- **Headings:** Uppercase, letter-spacing 1-2px, font-weight 600-700
- **Labels:** 12px uppercase, `#a0a0a0`
- **Values/metrics:** Monospace, larger size, accent color

#### 5.1.3 Component Styling

- Cards: `bg-[#252532]`, `rounded-xl`, `border border-[#3a3a4a]`, subtle shadow
- Buttons: Gradient backgrounds, hover lift (`translateY(-2px)`), glow shadow on accent color
- Inputs: Dark bg, border glow on focus (cyan), monospace for passwords
- Charts: Dark grid, colored lines with glow, semi-transparent area fills
- Status indicators: Pulsing dots (green=ok, red=critical, yellow=warning)
- Transitions: 200-300ms ease on all interactive elements

### 5.2 Layout

#### 5.2.1 Page Structure

```
+----------------------------------------------------------+
| TOPBAR: Logo | Server Selector | Status Dots | Settings   |
+----------------------------------------------------------+
|                                                          |
|  MAIN CONTENT AREA (scrollable)                          |
|                                                          |
|  +--------------------+  +--------------------+          |
|  | TEMP CHART (large) |  | FAN RPM CHART      |          |
|  |                    |  |                    |          |
|  +--------------------+  +--------------------+          |
|                                                          |
|  +--------------------+  +--------------------+          |
|  | POWER CARD         |  | FANPILOT CARD      |          |
|  | Status + Buttons   |  | Active Profile +   |          |
|  |                    |  | Mini Curve Preview  |          |
|  +--------------------+  +--------------------+          |
|                                                          |
|  +--------------------+  +--------------------+          |
|  | VOLTAGE SPARKLINES |  | PSU STATUS          |          |
|  +--------------------+  +--------------------+          |
|                                                          |
+----------------------------------------------------------+
```

#### 5.2.2 Pages / Routes

| Route | Page | Description |
|---|---|---|
| `/` | Dashboard | Main view with sensor charts, power control, FanPilot status |
| `/fanpilot` | Fan Curve Editor | Full-page fan curve editor with profile management |
| `/sel` | System Event Log | SEL table viewer with filters |
| `/fru` | Hardware Inventory | FRU card view |
| `/settings` | Settings | Server management (add/remove BMC), config, auth |
| `/setup` | First-Run Wizard | Shown on first boot — credentials, first BMC, connection test |

#### 5.2.3 Responsive Behavior

- **Desktop (>1280px):** 2-column grid for charts and cards
- **Tablet (768-1280px):** Single column, charts stack vertically
- **Mobile (<768px):** Single column, simplified charts, bottom nav

---

## 6. API Specification

### 6.1 REST Endpoints

#### Auth
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/auth/login` | Login with username/password, returns JWT |
| `POST` | `/api/auth/logout` | Invalidate session |
| `GET` | `/api/auth/me` | Current user info |
| `POST` | `/api/auth/setup` | First-run: create admin user |

#### Servers (BMC management)
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/servers` | List all configured servers |
| `POST` | `/api/servers` | Add a new BMC server |
| `PUT` | `/api/servers/:id` | Update server config |
| `DELETE` | `/api/servers/:id` | Remove a server |
| `POST` | `/api/servers/:id/test` | Test IPMI connection |

#### Sensors
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/servers/:id/sensors` | Latest sensor readings |
| `GET` | `/api/servers/:id/sensors/history` | Historical data (query: `from`, `to`, `sensor_name`) |

#### Power
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/servers/:id/power` | Current power status |
| `POST` | `/api/servers/:id/power` | Execute power command (body: `{ action: "on|soft_off|hard_off|reset|cycle" }`) |

#### FanPilot
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/servers/:id/fanpilot` | Current FanPilot state (active profile, current speed, mode) |
| `POST` | `/api/servers/:id/fanpilot/mode` | Set mode: `{ mode: "auto|manual|fanpilot" }` |
| `GET` | `/api/fanpilot/profiles` | List all fan profiles |
| `POST` | `/api/fanpilot/profiles` | Create a profile |
| `PUT` | `/api/fanpilot/profiles/:id` | Update a profile (curve points, hysteresis, etc.) |
| `DELETE` | `/api/fanpilot/profiles/:id` | Delete a profile |
| `POST` | `/api/servers/:id/fanpilot/apply` | Apply a profile to a server (body: `{ profile_id }`) |

#### SEL
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/servers/:id/sel` | Get SEL entries (query: `severity`, `from`, `to`, `search`) |
| `GET` | `/api/servers/:id/sel/info` | SEL metadata (count, free space) |
| `POST` | `/api/servers/:id/sel/clear` | Clear SEL (requires confirmation token) |
| `GET` | `/api/servers/:id/sel/export` | Export as CSV or JSON (query: `format=csv|json`) |

#### FRU
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/servers/:id/fru` | Get FRU data |
| `POST` | `/api/servers/:id/fru/refresh` | Force re-fetch from BMC |

#### System
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Health check |
| `GET` | `/api/config` | Get app config (non-sensitive) |
| `PUT` | `/api/config` | Update app config |
| `GET` | `/api/logs` | Command audit log |

### 6.2 WebSocket Events

Connection: `ws://<host>:3000/ws` (with JWT as query param or first message)

#### Server -> Client (Push)

```json
{
  "type": "sensor_update",
  "server_id": "uuid",
  "timestamp": "2026-03-26T12:00:00Z",
  "sensors": {
    "cpu_temp": { "value": 45, "unit": "C", "status": "ok" },
    "fan_1": { "value": 3200, "unit": "RPM", "status": "ok" },
    "power": { "value": 180, "unit": "W", "status": "ok" }
  }
}
```

```json
{
  "type": "power_status",
  "server_id": "uuid",
  "status": "on"
}
```

```json
{
  "type": "fanpilot_status",
  "server_id": "uuid",
  "mode": "fanpilot",
  "active_profile": "Silent",
  "current_speed_pct": 35,
  "source_temp": 42
}
```

```json
{
  "type": "alert",
  "server_id": "uuid",
  "severity": "warning",
  "sensor": "cpu_temp",
  "message": "CPU temperature exceeds 80C",
  "value": 82
}
```

#### Client -> Server (Commands via REST, not WS)

WebSocket is **read-only push** from server to client. All commands go through REST endpoints. This keeps the API surface simple and makes the future cloud relay transparent (relay just forwards REST to agent).

---

## 7. Database Schema

SQLite database at `<data_dir>/ipmilink.db`.

### 7.1 Tables

```sql
-- App users (local auth)
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,  -- bcrypt
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Configured BMC servers
CREATE TABLE servers (
    id TEXT PRIMARY KEY,  -- UUID
    name TEXT NOT NULL,
    host TEXT NOT NULL,
    port INTEGER DEFAULT 623,
    username_enc TEXT NOT NULL,  -- AES-256 encrypted
    password_enc TEXT NOT NULL,  -- AES-256 encrypted
    vendor TEXT DEFAULT 'dell',  -- dell, supermicro, hpe, generic
    poll_interval INTEGER DEFAULT 5,
    fanpilot_profile_id INTEGER REFERENCES fan_profiles(id),
    fanpilot_enabled INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Sensor readings (time-series data)
CREATE TABLE sensor_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id TEXT NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    sensor_name TEXT NOT NULL,
    sensor_type TEXT NOT NULL,  -- temperature, fan, voltage, power, status
    value REAL,
    unit TEXT,
    status TEXT,  -- ok, warning, critical, absent
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Index for fast time-range queries
CREATE INDEX idx_readings_server_time ON sensor_readings(server_id, timestamp);
CREATE INDEX idx_readings_server_sensor_time ON sensor_readings(server_id, sensor_name, timestamp);

-- Fan control profiles
CREATE TABLE fan_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    curve_points TEXT NOT NULL,  -- JSON: [{"temp": 30, "speed": 20}, ...]
    interpolation TEXT DEFAULT 'linear',  -- linear, smooth
    hysteresis REAL DEFAULT 3.0,
    safety_threshold REAL DEFAULT 85.0,
    source_sensor TEXT DEFAULT 'CPU Temp',
    is_preset INTEGER DEFAULT 0,  -- 1 for built-in presets
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Command audit log
CREATE TABLE command_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id TEXT REFERENCES servers(id) ON DELETE CASCADE,
    command_type TEXT NOT NULL,  -- power, fan_speed, fan_mode, sel_clear
    command_detail TEXT,  -- JSON with command specifics
    result TEXT,  -- success, error
    error_message TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- SEL cache
CREATE TABLE sel_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id TEXT NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    event_id TEXT,
    timestamp DATETIME,
    sensor_name TEXT,
    event_type TEXT,
    description TEXT,
    severity TEXT,  -- info, warning, critical
    raw_data TEXT,
    fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_sel_server_time ON sel_cache(server_id, timestamp);

-- FRU cache
CREATE TABLE fru_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id TEXT NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    section TEXT NOT NULL,  -- board, chassis, product
    field TEXT NOT NULL,
    value TEXT,
    fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- App configuration (key-value)
CREATE TABLE app_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### 7.2 Seed Data (First Run)

Insert default fan profiles (Silent, Balanced, Performance, Full Speed) on first migration.

---

## 8. Project Structure

```
ipmilink/
├── backend/
│   ├── main.py                  # FastAPI app, lifespan, static serving
│   ├── config.py                # Load/validate config.yaml
│   ├── database.py              # SQLite connection, migrations
│   ├── auth.py                  # JWT, bcrypt, login/logout
│   ├── ipmi/
│   │   ├── __init__.py
│   │   ├── service.py           # IPMIService interface + LocalIPMIService
│   │   ├── parser.py            # Parse ipmitool output (sdr, sel, fru)
│   │   └── commands.py          # Raw command builders per vendor
│   ├── fanpilot/
│   │   ├── __init__.py
│   │   ├── engine.py            # Fan curve interpolation + hysteresis
│   │   └── loop.py              # Async FanPilot background task
│   ├── sensors/
│   │   ├── __init__.py
│   │   └── loop.py              # Async sensor polling background task
│   ├── api/
│   │   ├── __init__.py
│   │   ├── auth_routes.py
│   │   ├── server_routes.py
│   │   ├── sensor_routes.py
│   │   ├── power_routes.py
│   │   ├── fanpilot_routes.py
│   │   ├── sel_routes.py
│   │   ├── fru_routes.py
│   │   └── system_routes.py
│   ├── ws/
│   │   ├── __init__.py
│   │   └── handler.py           # WebSocket manager + broadcast
│   └── models/
│       ├── __init__.py
│       └── schemas.py           # Pydantic models for request/response
│
├── frontend/
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx              # Router setup
│   │   ├── api/
│   │   │   └── client.ts        # Fetch wrapper, WebSocket hook
│   │   ├── hooks/
│   │   │   ├── useWebSocket.ts  # WS connection + auto-reconnect
│   │   │   ├── useSensors.ts    # Sensor data state management
│   │   │   └── useAuth.ts       # Auth state + JWT storage
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx
│   │   │   ├── FanPilot.tsx
│   │   │   ├── SEL.tsx
│   │   │   ├── FRU.tsx
│   │   │   ├── Settings.tsx
│   │   │   └── Setup.tsx
│   │   ├── components/
│   │   │   ├── layout/
│   │   │   │   ├── TopBar.tsx
│   │   │   │   └── PageLayout.tsx
│   │   │   ├── charts/
│   │   │   │   ├── TemperatureChart.tsx
│   │   │   │   ├── FanRPMChart.tsx
│   │   │   │   ├── PowerChart.tsx
│   │   │   │   └── VoltageSparkline.tsx
│   │   │   ├── power/
│   │   │   │   ├── PowerStatus.tsx
│   │   │   │   └── PowerControls.tsx
│   │   │   ├── fanpilot/
│   │   │   │   ├── CurveEditor.tsx
│   │   │   │   ├── ProfileSelector.tsx
│   │   │   │   └── FanPilotCard.tsx
│   │   │   ├── sel/
│   │   │   │   ├── SELTable.tsx
│   │   │   │   └── SELFilters.tsx
│   │   │   ├── fru/
│   │   │   │   └── FRUCards.tsx
│   │   │   └── common/
│   │   │       ├── StatusDot.tsx
│   │   │       ├── ConfirmModal.tsx
│   │   │       └── AlertBanner.tsx
│   │   └── styles/
│   │       └── globals.css      # Tailwind base + custom theme vars
│   ├── index.html
│   ├── vite.config.ts
│   ├── tailwind.config.ts
│   ├── tsconfig.json
│   └── package.json
│
├── config.example.yaml          # Example configuration
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml               # Python dependencies + project metadata
├── README.md
└── PRD.md                       # This document
```

---

## 9. Security

### 9.1 Authentication

- **First-run setup:** Wizard creates a local admin user (username + password)
- **Password storage:** bcrypt hash in SQLite `users` table
- **Session:** JWT token with configurable expiry (default: 24h)
- **JWT secret:** Auto-generated on first run, stored in `app_config` table

### 9.2 BMC Credential Security

- BMC usernames and passwords are encrypted with **AES-256-CBC**
- Encryption key is derived from the admin password using **PBKDF2** (not a hardcoded key like V1)
- Credentials are decrypted in-memory only when executing IPMI commands
- Never logged, never sent to the frontend

### 9.3 Network Security

- Default bind: `0.0.0.0:3000` (accessible from LAN)
- Configurable to `127.0.0.1` (localhost only)
- Optional HTTPS with self-signed cert or Let's Encrypt
- BMC traffic: RMCP+ (UDP 623) on local network only — never exposed
- No external network dependencies (fully offline capable)

### 9.4 Input Validation

- All API inputs validated with Pydantic models
- IP addresses validated against regex pattern
- No shell injection possible: ipmitool args passed as list (not string concatenation)
- Rate limiting on auth endpoints (5 attempts / minute)

---

## 10. Configuration

### 10.1 Config File: `config.yaml`

```yaml
server:
  host: 0.0.0.0
  port: 3000
  https: false
  # cert_file: /path/to/cert.pem
  # key_file: /path/to/key.pem

auth:
  session_expiry: 24h
  max_login_attempts: 5
  lockout_duration: 15m

ipmi:
  poll_interval: 5            # seconds
  power_poll_interval: 10     # seconds
  command_timeout: 10         # seconds
  backend: ipmitool           # ipmitool | python-ipmi (future)

fanpilot:
  enabled: true
  default_safety_threshold: 85  # Celsius
  default_hysteresis: 3         # Celsius
  loop_interval: 5              # seconds

data:
  db_path: /data/ipmilink.db
  retention_days: 365
  cleanup_interval: 24h         # how often to run retention cleanup

logging:
  level: info                   # debug, info, warning, error
  file: /data/ipmilink.log      # null for stdout only
```

### 10.2 Environment Variable Overrides

Every config key can be overridden with env vars using the prefix `IPMILINK_`:

```
IPMILINK_SERVER_PORT=8080
IPMILINK_AUTH_SESSION_EXPIRY=48h
IPMILINK_DATA_DB_PATH=/custom/path/db.sqlite
```

### 10.3 Docker Volume

```
/data/
├── ipmilink.db        # SQLite database
├── ipmilink.log       # Log file
└── config.yaml        # Config (auto-generated on first run, user-editable)
```

---

## 11. Cloud-Readiness Checklist

These patterns are baked into the self-hosted code so the cloud transition is mechanical, not architectural:

| Pattern | Implementation | Cloud Impact |
|---|---|---|
| **IPMIService interface** | `service.py` defines abstract methods; `LocalIPMIService` implements them via subprocess | Add `RemoteIPMIService` that sends commands via WS to relay |
| **server_id on every message** | All sensor data, commands, and WS events include `server_id` | Relay routes by server_id to the correct agent |
| **Standardized WS message format** | JSON with `type`, `server_id`, `timestamp`, `payload` | Relay forwards messages unchanged |
| **REST-only commands** | Commands go via REST, not WS | Cloud frontend hits relay REST API instead of local API |
| **Stateless sensor flow** | Backend reads -> broadcasts -> stores. No intermediate state needed | Relay does read -> broadcast (no store). Agent does read -> store locally |
| **Config-driven mode** | `config.yaml` has all tunables | Add `mode: cloud` option that switches IPMIService implementation |

---

## 12. Roadmap

### Phase 1 — MVP (Current Scope)

- [ ] Project scaffolding (backend + frontend + Docker)
- [ ] Setup wizard (first-run user creation + first BMC)
- [ ] Sensor polling loop + SQLite storage
- [ ] WebSocket broadcast to frontend
- [ ] Dashboard with live temperature + fan RPM charts
- [ ] Power control (all 6 commands)
- [ ] FanPilot: fan curve editor + profiles + async loop
- [ ] SEL viewer with filters and export
- [ ] FRU viewer
- [ ] Docker image + docker-compose

### Phase 2 — Multi-Server + Polish

- [ ] Multi-server dashboard (panoramic view, add/remove servers)
- [ ] Alert system (configurable thresholds, browser notifications)
- [ ] Historical chart improvements (zoom, pan, comparison)
- [ ] Voltage and power consumption charts
- [ ] Profile import/export (JSON)
- [ ] Improved mobile responsive layout

### Phase 3 — Advanced

- [ ] Supermicro + HPE iLO vendor support
- [ ] Serial over LAN (SOL) via browser terminal
- [ ] Auto-discovery of BMCs on the network
- [ ] Prometheus exporter (`/metrics` endpoint)
- [ ] Config backup/restore
- [ ] Plugin system for community extensions
- [ ] Cloud Edition (relay + agent + OAuth + E2E encryption)
