# IPMILink — Product Requirements Document

**Self-Hosted Edition (Cloud-Ready)**

Version: Draft 1.3
Date: 2026-03-28
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

### 2.4 Modular Architecture

IPMILink is built as a **module-based platform**. The core provides infrastructure (auth, database, WebSocket, IPMI service). Every feature (sensors, FanPilot, power, SEL, FRU) is a self-contained module that plugs into the core.

#### 2.4.1 Module Structure

Each module lives in its own directory and contains everything it needs:

```
modules/
├── sensors/
│   ├── manifest.py          # Module metadata + registration
│   ├── routes.py            # FastAPI router (REST endpoints)
│   ├── tasks.py             # Background async tasks
│   ├── models.py            # Pydantic schemas
│   ├── migrations/          # SQLite migration files
│   │   └── 001_initial.sql
│   └── widgets.json         # Widget definitions for the dashboard
│
├── fanpilot/
│   ├── manifest.py
│   ├── routes.py
│   ├── engine.py            # Fan curve interpolation + hysteresis
│   ├── tasks.py             # Fan control async loop
│   ├── models.py
│   ├── migrations/
│   └── widgets.json
│
├── power/
├── sel/
└── fru/
```

#### 2.4.2 Module Manifest

Every module declares its capabilities via a `manifest.py`:

```python
from core.modules import ModuleManifest

module = ModuleManifest(
    id="fanpilot",
    name="FanPilot",
    version="1.0.0",
    description="Intelligent fan curve control with drag-and-drop editor",
    author="IPMILink",
    category="cooling",
    icon="fan",
    dependencies=["sensors"],       # Requires sensors module
    routes=router,                  # FastAPI APIRouter
    background_tasks=[fan_loop],    # Async tasks to start
    event_handlers={                # Events this module listens to
        "sensor_reading": on_sensor_reading,
    },
    migrations_dir="migrations/",
)
```

#### 2.4.3 Module Lifecycle

On application startup, the core:

1. Scans the `modules/` directory for `manifest.py` files
2. Validates dependencies (error if a required module is missing)
3. Sorts modules by dependency order (topological sort)
4. Runs pending database migrations for each module
5. Mounts each module's routes under `/api/<module_id>/`
6. Registers event handlers on the event bus
7. Starts background tasks
8. Loads widget definitions for the frontend

#### 2.4.4 Module Enable/Disable

Each module can be toggled on/off from Settings. Disabled modules:
- Do not have their routes mounted
- Do not run background tasks
- Do not respond to events
- Do not appear in the dashboard widget catalog
- Keep their data in SQLite (not deleted)

State is stored in `app_config` table: `modules.fanpilot.enabled = true/false`

#### 2.4.5 Event Bus

Modules communicate through an async event bus. The core provides it; modules emit and subscribe.

| Event | Emitted by | Consumed by | Payload |
|---|---|---|---|
| `sensor_reading` | sensors | fanpilot, (future: alerts) | `{ server_id, sensor_name, value, unit }` |
| `temperature_critical` | sensors | fanpilot | `{ server_id, sensor_name, value, threshold }` |
| `fan_speed_changed` | fanpilot | sensors (for logging) | `{ server_id, speed_pct, profile }` |
| `power_state_changed` | power | (future: alerts, scheduler) | `{ server_id, state, previous_state }` |
| `sel_critical_event` | sel | (future: alerts) | `{ server_id, event_type, description }` |
| `module_installed` | core | core (UI refresh) | `{ module_id }` |
| `module_uninstalled` | core | core (UI refresh) | `{ module_id }` |

The event bus is in-process (asyncio queues). No external message broker needed.

#### 2.4.6 Module Config

Each module owns its own config section in `config.yaml`:

```yaml
modules:
  sensors:
    enabled: true
    poll_interval: 5
    retention_days: 365
  fanpilot:
    enabled: true
    safety_threshold: 85
    hysteresis: 3
    loop_interval: 5
  power:
    enabled: true
    poll_interval: 10
  sel:
    enabled: true
  fru:
    enabled: true
```

The core passes only the relevant section to each module. Modules never read each other's config.

### 2.5 Widget Grid System

The dashboard home is a **customizable widget grid** where the user composes their own layout from widgets provided by installed modules.

#### 2.5.1 Grid Specification

- Base grid: **6 columns** (desktop), **4 columns** (tablet), **2 columns** (mobile)
- Row height: **120px** (fixed)
- Gap: **16px**
- Library: **react-grid-layout** (drag-and-drop, resize, responsive breakpoints, layout serialization)

#### 2.5.2 Widget Sizes

| Size | Columns x Rows | Use Case |
|---|---|---|
| `1x1` | 1 col, 1 row | Single metric — current CPU temp, power status dot |
| `2x1` | 2 col, 1 row | Status bar — FanPilot mode + speed, PSU summary |
| `2x2` | 2 col, 2 row | Standard card — mini chart, quick actions, profile selector |
| `3x2` | 3 col, 2 row | Medium chart — temperature last 1h, fan RPM trend |
| `4x2` | 4 col, 2 row | Large chart — multi-sensor overlay, power consumption |
| `6x2` | Full width, 2 row | Panoramic chart — full timeline with zoom |
| `6x3` | Full width, 3 row | Full editor — fan curve editor inline on dashboard |

#### 2.5.3 Widget Definition (per module)

Each module declares its widgets in `widgets.json`:

```json
{
  "widgets": [
    {
      "id": "fanpilot-curve",
      "name": "Fan Curve",
      "description": "Live fan curve with current temperature indicator",
      "sizes": ["2x2", "3x2", "6x3"],
      "default_size": "3x2",
      "refresh_interval": 5,
      "category": "cooling"
    },
    {
      "id": "fanpilot-status",
      "name": "FanPilot Quick Status",
      "description": "Current mode, active profile, fan speed",
      "sizes": ["1x1", "2x1"],
      "default_size": "2x1",
      "refresh_interval": 5,
      "category": "cooling"
    },
    {
      "id": "fanpilot-actions",
      "name": "FanPilot Quick Actions",
      "description": "Profile switcher and manual override buttons",
      "sizes": ["2x2"],
      "default_size": "2x2",
      "refresh_interval": null,
      "category": "cooling"
    }
  ]
}
```

Frontend widget components are registered in an index:

```typescript
// frontend/src/modules/fanpilot/widgets/index.ts
export const widgets = {
  "fanpilot-curve": FanCurveWidget,
  "fanpilot-status": FanPilotStatusWidget,
  "fanpilot-actions": FanPilotActionsWidget,
}
```

#### 2.5.4 Dashboard Layout Persistence

- Layout is a JSON array of `{ widget_id, module_id, server_id, x, y, w, h }`
- Saved in SQLite `dashboard_layouts` table per user
- Default layout provided when no custom layout exists
- Reset to default button available in Settings

```sql
CREATE TABLE dashboard_layouts (
    user_id INTEGER REFERENCES users(id),
    layout JSON NOT NULL,  -- Serialized react-grid-layout state
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id)
);
```

#### 2.5.5 Widget Interaction Flow

1. User clicks "+" button on dashboard (or "Add Widget" in empty area)
2. Widget catalog slides in — shows all widgets from installed modules, grouped by category
3. Each widget shows a preview thumbnail, name, available sizes
4. User clicks a widget — it's added to the grid at default size in the first available position
5. User drags to reposition, drags corner to resize (within declared sizes)
6. User clicks "x" on a widget to remove it from dashboard (module stays installed)
7. Layout auto-saves on every change

### 2.6 Module Marketplace (Roadmap)

The marketplace is the long-term vision for module distribution. Not in MVP scope, but the architecture supports it from day one.

#### 2.6.1 Phases

**Phase 1 (MVP):** All modules are **built-in**. They ship with the app. Users can enable/disable from Settings. Widget grid is fully functional.

**Phase 2:** Module catalog page (`/modules`) shows built-in modules as cards with enable/disable toggle, description, widget previews, and dependency info.

**Phase 3:** External module registry. Users can browse, download, and install community modules from within the app.

#### 2.6.2 Registry (Phase 3)

A static JSON index hosted at `registry.ipmilink.io` (GitHub Pages or static endpoint):

```json
{
  "version": 1,
  "modules": [
    {
      "id": "alerts",
      "name": "Alerts",
      "version": "1.0.0",
      "author": "IPMILink",
      "category": "notifications",
      "description": "Configurable alert thresholds with email, webhook, and Telegram notifications",
      "icon": "bell",
      "dependencies": ["sensors"],
      "min_core_version": "2.0.0",
      "download_url": "https://registry.ipmilink.io/modules/alerts-1.0.0.zip",
      "checksum": "sha256:abc123...",
      "widgets": [
        { "id": "alerts-panel", "name": "Active Alerts", "sizes": ["2x2", "4x2"] },
        { "id": "alerts-history", "name": "Alert History", "sizes": ["3x2", "6x2"] }
      ]
    }
  ]
}
```

#### 2.6.3 Installation Flow (Phase 3)

1. User opens `/modules` page
2. "Available" tab shows modules from the registry not yet installed
3. User clicks "Install" on a module
4. Backend downloads the ZIP, verifies SHA-256 checksum
5. Extracts to `modules/<module_id>/`
6. Runs module migrations
7. Registers routes, tasks, event handlers
8. Module's widgets appear in the dashboard widget catalog
9. No restart required (hot-load)

#### 2.6.4 Future Module Ideas

| Module | Category | Description |
|---|---|---|
| **alerts** | notifications | Configurable thresholds + email/webhook/Telegram |
| **scheduler** | automation | Scheduled profile switches (e.g., Silent at night) |
| **metrics-exporter** | integrations | Prometheus `/metrics` endpoint for Grafana |
| **console (SOL)** | remote-access | Serial over LAN via xterm.js in browser |
| **discovery** | network | Auto-scan LAN for BMC devices |
| **backup** | system | Export/import config + profiles + data as ZIP |
| **benchmarks** | diagnostics | Thermal stress test to validate fan profiles |
| **multi-server** | management | Panoramic view of all servers with status overview |

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

### 5.1 Visual Style: shadcn/ui Professional Dark

The dashboard follows a professional, minimal dark theme inspired by shadcn/ui. No neon, no glow effects — clean, readable, and production-grade.

#### 5.1.1 Color Palette (Zinc-based dark)

| Role | Token | Hex |
|---|---|---|
| **Background** | `--background` | `#09090b` |
| **Foreground** | `--foreground` | `#fafafa` |
| **Card** | `--card` | `#0a0a0c` |
| **Muted** | `--muted` | `#18181b` |
| **Muted foreground** | `--muted-foreground` | `#a1a1aa` |
| **Border** | `--border` | `#27272a` |
| **Primary** | `--primary` | `#f4f4f5` |
| **Destructive** | `--destructive` | `#ef4444` |
| **Chart Blue** | `--chart-1` | `#2563eb` |
| **Chart Emerald** | `--chart-2` | `#10b981` |
| **Chart Amber** | `--chart-3` | `#f59e0b` |
| **Chart Violet** | `--chart-4` | `#8b5cf6` |
| **Success** | `--success` | `#22c55e` |
| **Warning** | `--warning` | `#eab308` |
| **Danger** | `--danger` | `#ef4444` |

#### 5.1.2 Typography

- **Sans:** `'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif`
- **Monospace (values/data):** `'JetBrains Mono', 'Fira Code', monospace`
- **Headings:** Normal case (not uppercase), letter-spacing -0.02em, font-weight 600
- **Labels:** 13px, font-weight 500, `--muted-foreground`
- **Values/metrics:** Monospace, larger size, `--foreground`

#### 5.1.3 Component Styling (shadcn patterns)

- Cards: `bg-card`, `rounded-[0.5rem]`, `border border-border`, subtle shadow-sm
- Buttons: Flat backgrounds, no gradients, subtle hover (`bg-muted`), no glow
- Inputs: `bg-input`, `border-border`, ring on focus
- Charts: Minimal grid lines, solid colored lines, 8% opacity area fills
- Status indicators: Static dots (no animation), `--success`/`--danger`/`--warning`
- Badges: Pill-shaped, 12% opacity background tint of the semantic color
- Transitions: 150ms ease on interactive elements

### 5.2 Layout

#### 5.2.1 Page Structure (Sidebar + Main)

```
+----------+---------------------------------------------+
|          | HEADER: Breadcrumb | Time Tabs | + Add Widget |
| SIDEBAR  +---------------------------------------------+
|          |                                             |
| Logo     |  WIDGET GRID (6-col, scrollable)            |
| -------- |                                             |
| Platform |  +------+ +------+ +------+ +------+ ...   |
|  Dashbrd |  | CPU  | | Inlet| | Fan% | | Watt |       |
|  FanPlot |  | R720 | | R720 | | R630 | | R720 |       |
|  SEL     |  +------+ +------+ +------+ +------+       |
|  FRU     |                                             |
| -------- |  +------------------+ +------------------+  |
| System   |  | Temp Chart R720  | | Fan Curve R720   |  |
|  Modules |  +------------------+ +------------------+  |
|  Settings|                                             |
| -------- |  +------------------+ +----------+ +-----+  |
| [Server] |  | Fan RPM R630     | | Power    | |Volts|  |
| Dell R720|  |                  | | R720     | |R720 |  |
| .1.110   |  +------------------+ +----------+ +-----+  |
+----------+---------------------------------------------+
```

Key design decisions:
- **Sidebar** is always visible on desktop, collapsible on tablet, hidden on mobile
- **Server selector** in sidebar footer — shows the "active context" server with status dot
- **Dashboard widgets are cross-server** — each widget has a server_id, shown as a subtle tag
- **Module pages (FanPilot, SEL, FRU)** operate on the selected context server from the sidebar

#### 5.2.2 Pages / Routes

| Route | Page | Server Scope | Description |
|---|---|---|---|
| `/` | Dashboard | **All servers** (cross-server widgets) | Customizable widget grid |
| `/fanpilot` | Fan Curve Editor | Context server (from sidebar) | Full-page editor with profile management |
| `/sel` | System Event Log | Context server | SEL table with filters |
| `/fru` | Hardware Inventory | Context server | FRU card view |
| `/modules` | Module Catalog | N/A | Enable/disable modules |
| `/settings` | Settings | N/A | Server management, config, auth |
| `/settings/servers` | Server Management | N/A | Add/edit/remove servers |
| `/setup` | First-Run Wizard | N/A | First boot — credentials, first BMC |

#### 5.2.3 Responsive Behavior

- **Desktop (>1280px):** Sidebar (240px) + 6-column widget grid
- **Tablet (768-1280px):** Sidebar collapsed to icons (48px) + 4-column grid
- **Mobile (<768px):** No sidebar (hamburger menu), 2-column grid

### 5.3 Multi-Server Management

#### 5.3.1 Server Entity

Each server is a configured BMC connection with:

| Field | Type | Description |
|---|---|---|
| `id` | UUID | Unique identifier |
| `name` | String | User-defined display name (e.g., "Dell R720 - Plex") |
| `description` | String | Optional description (e.g., "Living room rack, top unit") |
| `host` | String | BMC IP address |
| `port` | Integer | IPMI port (default: 623) |
| `username` | String (encrypted) | IPMI username |
| `password` | String (encrypted) | IPMI password |
| `vendor` | Enum | `dell`, `supermicro`, `hpe`, `generic` |
| `color` | String | Hex color for visual identification in widgets |
| `icon` | String | Optional icon identifier |

#### 5.3.2 Server Selector (Sidebar Footer)

- Shows the **active context server**: name, IP, connection status dot
- Click opens a dropdown/popover listing all configured servers with:
  - Status dot (green=online, red=offline, gray=not polling)
  - Server name + IP
  - Click to switch context
- "Manage Servers" link at the bottom → navigates to `/settings/servers`
- The context server determines which server's data is shown on FanPilot, SEL, FRU pages

#### 5.3.3 Cross-Server Dashboard

The dashboard (`/`) is **not tied to one server**. Each widget on the grid is bound to a specific server.

- When adding a widget via "+ Add Widget", the user selects:
  1. Which module's widget (e.g., "Temperature Chart" from sensors module)
  2. Which server it displays data from
  3. Widget size
- Each widget shows a subtle **server tag** in the header (e.g., "R720" or a colored dot) so the user knows which server each widget belongs to
- This allows layouts like:
  - R720 CPU temp next to R630 CPU temp for comparison
  - All servers' power status in one row
  - FanPilot status for R720 + temperature chart for R630

#### 5.3.4 Server Color Coding

Each server has an assigned color (user-configurable). This color appears as:
- A thin left-border accent on widgets belonging to that server
- The status dot color ring in the server selector
- Legend entries in multi-server comparison charts

Default colors are auto-assigned from a predefined professional palette:
`#2563eb` (blue), `#10b981` (emerald), `#f59e0b` (amber), `#8b5cf6` (violet), `#ec4899` (pink), `#6366f1` (indigo)

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

#### Dashboard
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/dashboard/layout` | Get current user's widget grid layout |
| `PUT` | `/api/dashboard/layout` | Save widget grid layout (JSON body) |
| `DELETE` | `/api/dashboard/layout` | Reset layout to default |

#### Context
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/context/server` | Get active context server ID |
| `PUT` | `/api/context/server` | Set active context server (body: `{ server_id }`) |

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
    description TEXT,     -- user-defined description
    host TEXT NOT NULL,
    port INTEGER DEFAULT 623,
    username_enc TEXT NOT NULL,  -- AES-256 encrypted
    password_enc TEXT NOT NULL,  -- AES-256 encrypted
    vendor TEXT DEFAULT 'dell',  -- dell, supermicro, hpe, generic
    color TEXT DEFAULT '#2563eb', -- hex color for widget identification
    poll_interval INTEGER DEFAULT 5,
    fanpilot_profile_id INTEGER REFERENCES fan_profiles(id),
    fanpilot_enabled INTEGER DEFAULT 0,
    is_online INTEGER DEFAULT 0,  -- cached connection status
    last_seen DATETIME,           -- last successful poll timestamp
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

### 9.1 Authentication (Simplified — LAN Only)

Authentication is **optional and local-only**. There is no OAuth, no cloud accounts, no JWT refresh flow.

- **First-run setup:** Wizard offers to create a username + password. User can skip this step.
- **Password storage:** bcrypt hash in SQLite `users` table
- **Session:** Simple session cookie with configurable expiry (default: 24h). No JWT complexity needed for LAN.
- **Disable auth:** In Settings, the user can toggle authentication off entirely. When disabled, the app is open to anyone on the LAN. A warning banner is shown.
- **Change credentials:** Username and password are editable in Settings. Can also be reset via CLI: `ipmilink reset-password`
- **No multi-user:** Single user account. If auth is enabled, one set of credentials.

### 9.2 BMC Credential Security

- BMC usernames and passwords are encrypted with **AES-256-CBC**
- Encryption key is derived from a generated app secret stored in `app_config` (not from the user password, since auth can be disabled)
- App secret is generated once at first run, stored in SQLite
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
- Basic rate limiting on login endpoint (5 attempts / minute) when auth is enabled

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

## 11. UX Features

### 11.1 Dark/Light Mode Toggle

- Toggle in sidebar header or Settings page
- Uses shadcn/ui theming system — CSS variables swap between dark and light tokens
- Preference saved in `app_config` table and `localStorage`
- Default: dark mode
- System preference detection (`prefers-color-scheme`) as initial default

### 11.2 Command Palette (Cmd+K)

Global search and action launcher accessible from anywhere via `Cmd+K` (Mac) or `Ctrl+K` (Windows/Linux).

**Search categories:**
- **Servers:** Jump to server context ("Dell R720", "192.0.2.10")
- **Pages:** Navigate to any page ("FanPilot", "Event Log", "Settings")
- **Actions:** Execute commands ("Power off R720", "Switch to Silent profile", "Export SEL")
- **Sensors:** Jump to specific sensor data ("CPU Temp R720", "Fan 1 RPM")

**Implementation:** shadcn `<Command>` component (built on cmdk). Backend provides a `/api/search` endpoint for server/sensor queries; pages and actions are client-side.

### 11.3 Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Cmd/Ctrl + K` | Open command palette |
| `1` - `9` | Switch to server 1-9 (context) |
| `D` | Go to Dashboard |
| `F` | Go to FanPilot |
| `E` | Go to Event Log (SEL) |
| `H` | Go to Hardware (FRU) |
| `M` | Go to Modules |
| `Space` | Pause/resume live polling |
| `Cmd/Ctrl + Shift + E` | Export dashboard as image |
| `?` | Show keyboard shortcuts help |

Shortcuts are active only when no input/textarea is focused. Help modal shows all shortcuts.

### 11.4 Toast Notifications

Every user action and system event produces a toast notification using Sonner (shadcn's recommended toast library).

| Event | Toast Type | Example |
|---|---|---|
| Fan speed changed | Success | "FanPilot: speed set to 35% on R720" |
| Power command executed | Success | "R720: soft power off initiated" |
| Profile switched | Info | "FanPilot: switched to Silent profile" |
| IPMI command error | Error | "R720: connection timeout" |
| Server went offline | Warning | "R630 is unreachable" |
| Safety override triggered | Warning | "FanPilot: CPU at 87°C — fans set to 100%" |
| Widget added/removed | Info | "Temperature Chart added to dashboard" |
| Config saved | Success | "Settings saved" |

Position: bottom-right. Auto-dismiss after 4 seconds. Errors persist until dismissed.

### 11.5 Export Dashboard as Image

- Button in header: "Export" (or `Cmd+Shift+E`)
- Uses `html-to-image` library to capture the widget grid as PNG
- Includes IPMILink watermark (small, bottom-right)
- Opens browser download dialog
- Useful for sharing setups on Reddit, forums, Discord

### 11.6 Drag Widget from Sidebar

Alternative to the "+ Add Widget" → catalog flow:

- In edit mode (toggle via pencil icon in header), the sidebar shows a "Widgets" section below the nav
- Widgets are listed as small draggable chips grouped by module
- User drags a chip onto the grid → it becomes a widget at default size
- Server assignment: uses the current context server by default, changeable via widget settings

### 11.7 Comparison Widget

A special widget provided by the sensors module that overlays the same sensor from multiple servers on one chart.

- Widget ID: `sensors-comparison`
- Available sizes: `3x2`, `4x2`, `6x2`
- Configuration: select sensor type (e.g., "CPU Temp") + select 2-6 servers
- Each server's line uses that server's assigned color
- Legend shows server name + current value
- Useful for thermal comparison across identical hardware

### 11.8 Sparklines in Metric Widgets

The 1x1 metric widgets (CPU temp, inlet temp, power draw, fan speed) include a mini sparkline showing the last 5 minutes of data.

- Sparkline is a simple polyline SVG, 60px wide, rendered below the metric value
- Color matches the metric's semantic color (blue for temp, amber for fan, etc.)
- No axes, no labels — just the trend shape
- Data comes from the same WebSocket feed, buffered client-side (last 60 data points)

### 11.9 Onboarding Tour

On first login after setup, a guided tour highlights key UI elements:

1. **Sidebar navigation** — "This is where you switch between modules"
2. **Server selector** — "Your servers are here. Click to switch context"
3. **Widget grid** — "This is your dashboard. Drag widgets to rearrange"
4. **Add Widget button** — "Click here to add new widgets from your modules"
5. **FanPilot** — "Set up fan curves to keep your servers cool and quiet"

Implementation: lightweight library (e.g., `driver.js` or custom overlay). Tour can be restarted from Settings. Dismissed state saved in `localStorage`.

### 11.10 Empty States

Every page has a designed empty state with illustration and call-to-action:

| Page | Empty State Message | CTA |
|---|---|---|
| Dashboard (no widgets) | "Your dashboard is empty" | "Add your first widget" |
| Dashboard (no servers) | "No servers configured" | "Add a server" → Settings |
| FanPilot (no profiles) | "No fan profiles yet" | "Create your first profile" |
| SEL (no events) | "No events recorded" | "Refresh from BMC" |
| Modules (all enabled) | "All modules are active" | N/A (informational) |

Empty states use a minimal SVG illustration (monochrome, matching the theme) and a single primary CTA button.

---

## 12. Architectural Decisions

### 12.1 Frontend State Management: Zustand

Global state is managed with **Zustand** (lightweight, performant, no boilerplate).

Stores:
- `useServerStore` — server list, active context server, connection statuses
- `useSensorStore` — latest sensor readings per server (fed by WebSocket)
- `useLayoutStore` — dashboard widget grid layout
- `useAuthStore` — auth state, user info
- `useModuleStore` — installed modules, enabled/disabled state

WebSocket data flows directly into Zustand stores. Widgets subscribe to the specific slice they need via selectors — only re-render when their data changes.

### 12.2 Data Downsampling: Query-Time Aggregation

Raw sensor data is stored at full resolution (every 5 seconds). When the frontend requests historical data, the backend aggregates on-the-fly using SQLite:

| Requested Range | Aggregation | Approx Points |
|---|---|---|
| Last 5 min | None (raw) | 60 |
| Last 1 hour | 30s average | 120 |
| Last 6 hours | 2min average | 180 |
| Last 24 hours | 5min average | 288 |
| Last 7 days | 30min average | 336 |
| Last 30 days | 2h average | 360 |
| Custom | Auto (target ~300 points) | ~300 |

Query pattern:
```sql
SELECT
  strftime('%Y-%m-%d %H:%M', timestamp, 'start of minute', printf('-%d minutes', (strftime('%M', timestamp) % 5))) as bucket,
  AVG(value) as value,
  sensor_name
FROM sensor_readings
WHERE server_id = ? AND timestamp > ? AND sensor_name = ?
GROUP BY bucket, sensor_name
ORDER BY bucket
```

No background compaction job. Raw data stays intact until the retention cleanup deletes rows older than `retention_days`.

### 12.3 Demo Mode (Mock IPMI)

For development and for users who want to try the app without real hardware:

- Activated via `--demo` flag or `IPMILINK_DEMO=true` env var
- `DemoIPMIService` replaces `LocalIPMIService` — same interface, fake data
- Generates realistic sensor data: CPU temp oscillating 35-55°C with noise, fan RPM correlated to temp, power draw 150-200W with spikes
- Simulates 2 virtual servers ("Demo R720", "Demo R630")
- All modules work normally — FanPilot applies curves to simulated temps, power control toggles virtual state, SEL has sample events
- Demo mode shows a persistent banner: "Running in demo mode — no real hardware connected"

### 12.4 Build Pipeline

**Development:**
```
Terminal 1: cd backend && uvicorn main:app --reload --port 3000
Terminal 2: cd frontend && npm run dev  (Vite dev server on :5173, proxies /api to :3000)
```

**Production (Docker):**
```dockerfile
# Stage 1: Build frontend
FROM node:20-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/ .
RUN npm ci && npm run build

# Stage 2: Python backend + built frontend
FROM python:3.11-slim
RUN apt-get update && apt-get install -y ipmitool && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/ ./backend/
COPY --from=frontend /app/frontend/dist ./backend/static/
RUN pip install --no-cache-dir -e ./backend
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "3000"]
```

FastAPI serves the frontend static build from `backend/static/`. The frontend's `vite.config.ts` sets `base: '/'` and the build output goes to `dist/`.

### 12.5 Graceful Shutdown

On `SIGTERM` or `SIGINT` (Docker stop, Ctrl+C):

```
1. Stop accepting new WebSocket connections
2. FanPilot: for each server with manual fan control active:
     → Send `raw 0x30 0x30 0x01 0x01` (restore BMC auto mode)
     → Log "Safety: restored auto mode on <server>"
3. Stop all sensor polling loops
4. Close all WebSocket connections
5. Flush pending SQLite writes
6. Close SQLite connection
7. Exit
```

Step 2 is **critical** — if the app crashes without restoring auto mode, fans stay at the last manual speed. Python `atexit` + `signal` handlers ensure this runs even on unexpected termination. Docker `STOPSIGNAL SIGTERM` with a 30-second grace period.

### 12.6 Error Handling Strategy

| Error | Behavior | User Feedback |
|---|---|---|
| **ipmitool timeout** (BMC unreachable) | Mark server `is_online=false`, stop polling for that server, retry every 30s | Toast: "R720 is unreachable". Status dot goes red. |
| **ipmitool command error** (bad credentials, unsupported command) | Log error, do not retry automatically | Toast: error message. Command log entry with error detail. |
| **FanPilot fails to set speed** | Retry once after 5s. If still fails, restore auto mode for safety. | Toast: "FanPilot error on R720 — restored auto mode" |
| **SQLite write fails** (disk full, locked) | Log error, continue polling (data lost for that tick), show warning | Toast: "Database write failed — check disk space" |
| **WebSocket disconnect** (browser side) | Auto-reconnect with linear backoff: 1s, 3s, 5s, 10s, then every 10s | UI shows "Reconnecting..." badge in header |
| **Module crash** (unhandled exception in a module) | Catch at module boundary, disable the module, log stack trace | Toast: "Module <name> encountered an error and was disabled" |

### 12.7 Testing Strategy

**Backend (pytest):**
- Unit tests: IPMI parser (parse sdr/sel/fru output against real captured output files)
- Unit tests: FanPilot engine (curve interpolation, hysteresis, safety override)
- Unit tests: Module loader, event bus
- Integration tests: FastAPI routes with `TestClient`, SQLite in-memory
- Mock: `DemoIPMIService` used for all tests — no real BMC needed

**Frontend (Vitest + React Testing Library):**
- Unit tests: Zustand stores (sensor data flow, layout persistence)
- Component tests: Widget rendering, fan curve editor interactions
- No E2E for MVP — manual testing with demo mode

**CI:** GitHub Actions — `pytest` + `npm run test` + `npm run build` on every PR.

### 12.8 Frontend Routing: React Router v7

```
/              → Dashboard (widget grid)
/fanpilot      → FanPilot page (context server)
/sel           → SEL page (context server)
/fru           → FRU page (context server)
/modules       → Module catalog
/settings      → Settings (general, servers, auth)
/setup         → First-run wizard (redirect if already configured)
```

Lazy loading per page with `React.lazy()` + `Suspense`. Sidebar nav highlights the active route.

---

## 13. Cloud-Readiness Checklist

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

## 14. Roadmap

### Phase 1 — MVP (Current Scope)

**Core Infrastructure:**
- [ ] Project scaffolding (core + module system + frontend + Docker)
- [ ] Core: module loader, event bus, config, auth, database, WebSocket manager
- [ ] Core: IPMIService interface + LocalIPMIService
- [ ] Setup wizard (first-run user creation + first BMC)

**Modules:**
- [ ] Module: sensors (polling loop, SQLite storage, WebSocket broadcast)
- [ ] Module: power (6 commands, status polling)
- [ ] Module: fanpilot (engine, async loop, curve editor, profiles)
- [ ] Module: sel (viewer, filters, export)
- [ ] Module: fru (viewer, caching)

**Dashboard & Widgets:**
- [ ] Widget grid with react-grid-layout (drag, drop, resize)
- [ ] Widget catalog ("Add Widget" panel)
- [ ] Dashboard layout persistence (per user)
- [ ] Cross-server widgets (server_id per widget)
- [ ] Sparklines in 1x1 metric widgets
- [ ] Module enable/disable from Settings

**UX:**
- [ ] Dark/Light mode toggle
- [ ] Command palette (Cmd+K)
- [ ] Keyboard shortcuts
- [ ] Toast notifications (Sonner)
- [ ] Empty states with illustrations and CTAs
- [ ] Onboarding tour (first login)

**Packaging:**
- [ ] Docker image + docker-compose

### Phase 2 — Multi-Server + Polish

- [ ] Multi-server management (add/remove/edit servers with name, description, color)
- [ ] Server groups/tags
- [ ] Comparison widget (same sensor across multiple servers)
- [ ] Drag widget from sidebar
- [ ] Export dashboard as image
- [ ] Module catalog page (`/modules`) with visual cards
- [ ] Alert module (configurable thresholds, browser notifications)
- [ ] Scheduler module (time-based profile switching)
- [ ] Historical chart improvements (zoom, pan, comparison)
- [ ] Profile import/export (JSON)
- [ ] Improved mobile responsive layout

### Phase 3 — Marketplace + Advanced

- [ ] External module registry (`registry.ipmilink.io`)
- [ ] In-app module install/uninstall (hot-load, no restart)
- [ ] Metrics-exporter module (Prometheus `/metrics`)
- [ ] Console module (SOL via xterm.js)
- [ ] Discovery module (auto-scan LAN for BMCs)
- [ ] Supermicro + HPE iLO vendor support
- [ ] Cloud Edition (relay + agent + OAuth + E2E encryption)
