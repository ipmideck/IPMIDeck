import { useState, useEffect, useCallback, useId, useMemo, useRef } from "react";
import { useTranslation, Trans } from "react-i18next";
import type { TFunction } from "i18next";
import { Header } from "@/components/layout/Header";
import { useServerStore } from "@/stores/server-store";
import { useSensorStore } from "@/stores/sensor-store";
import { useBackendOnline } from "@/stores/connection-store";
import type { SensorReading } from "@/stores/sensor-store";
import { get, post, put, del } from "@/api/client";
import { cn } from "@/lib/utils";
import { EmptyState } from "@/components/common/EmptyState";
import { sensorNamesForType } from "@/modules/sensors/sensorUtils";
import { toast } from "sonner";
import {
  Fan,
  Plus,
  Trash2,
  Save,
  Volume2,
  Gauge,
  Zap,
  Wind,
  ChevronRight,
  AlertTriangle,
  Thermometer,
  SlidersHorizontal,
  Cpu,
  RotateCcw,
} from "lucide-react";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface CurvePoint {
  temp: number;
  speed: number;
}

interface FanProfile {
  id: string;
  name: string;
  description: string;
  curve_points: CurvePoint[];
  hysteresis: number;
  safety_threshold: number;
  source_sensor: string;
  is_preset: boolean;
}

interface FanStatus {
  enabled: boolean;
  mode: "auto" | "manual" | "fanpilot";
  /** Backend returns the active profile as a row `{id, name}` (or null), not a string. */
  profile: { id: number; name: string } | null;
  current_speed_pct: number | null;
}

type FanMode = "auto" | "manual" | "fanpilot";

// localStorage key for "last opened profile" — UI preference only (profiles are
// global, not per-server, so a single key is sufficient). Read on profiles fetch,
// written whenever the operator selects a different profile.
const LAST_PROFILE_KEY = "fanpilot:last-profile-id";

// Fan-mode metadata used by the bottom bar (icon + i18n keys). Only stable mode codes
// and translation keys live at module load; label/description are resolved via t() in
// render so the bottom bar re-translates on language change. The description drives the
// button tooltip so the user understands what each mode does at a glance.
const MODE_OPTIONS: { mode: FanMode; labelKey: string; descKey: string; icon: typeof Cpu }[] = [
  { mode: "auto", labelKey: "fanpilot.modeAuto", descKey: "fanpilot.modeAutoDesc", icon: Cpu },
  { mode: "manual", labelKey: "fanpilot.modeManual", descKey: "fanpilot.modeManualDesc", icon: SlidersHorizontal },
  { mode: "fanpilot", labelKey: "fanpilot.modeFanpilot", descKey: "fanpilot.modeFanpilotDesc", icon: Fan },
];

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

const TEMP_MIN = 20;
const TEMP_MAX = 100;
const SPEED_MIN = 0;
const SPEED_MAX = 100;

// Stable empty-readings reference so the Zustand selector below never returns a
// fresh object on each render (otherwise Object.is sees a "change" → infinite
// re-render → React #185 on cold load of /fanpilot). See GAP-04.
const EMPTY_READINGS: Record<string, SensorReading> = {};

// SVG viewport dimensions for the curve editor.
// SVG_PAD_TOP intentionally generous so the live-temp / drag tooltips have room
// to render at a readable size above the plot area without being clipped.
const SVG_PAD_LEFT = 48;
const SVG_PAD_RIGHT = 16;
const SVG_PAD_TOP = 28;
const SVG_PAD_BOTTOM = 36;
const SVG_WIDTH = 640;
const SVG_HEIGHT = 360;
const PLOT_W = SVG_WIDTH - SVG_PAD_LEFT - SVG_PAD_RIGHT;
const PLOT_H = SVG_HEIGHT - SVG_PAD_TOP - SVG_PAD_BOTTOM;

const PRESET_ICONS: Record<string, React.ReactNode> = {
  Silent: <Volume2 className="h-4 w-4" />,
  Balanced: <Gauge className="h-4 w-4" />,
  Performance: <Zap className="h-4 w-4" />,
  "Full Speed": <Wind className="h-4 w-4" />,
};

/* ------------------------------------------------------------------ */
/*  Temperature colors — fixed bands shared across editor + chips      */
/* ------------------------------------------------------------------ */

// Fixed bands: <50 green, <65 yellow, <80 orange, >=80 red. Used by the curve gradient,
// the live-temp indicator, the draggable points, and the top temperature chips.
const TEMP_BANDS = [
  { upTo: 50, base: "#22c55e", dark: "#16a34a", chip: "bg-emerald-500/15 text-emerald-500 border-emerald-500/30" },
  { upTo: 65, base: "#eab308", dark: "#ca8a04", chip: "bg-yellow-500/15 text-yellow-500 border-yellow-500/30" },
  { upTo: 80, base: "#f97316", dark: "#ea580c", chip: "bg-orange-500/15 text-orange-500 border-orange-500/30" },
  { upTo: Infinity, base: "#ef4444", dark: "#dc2626", chip: "bg-red-500/15 text-red-500 border-red-500/30" },
] as const;

function tempBand(t: number) {
  for (const b of TEMP_BANDS) if (t < b.upTo) return b;
  return TEMP_BANDS[TEMP_BANDS.length - 1];
}

function tempColor(t: number): string {
  return tempBand(t).base;
}

function tempChipClass(t: number): string {
  return tempBand(t).chip;
}

// Default values for the preset profiles — sourced from migration 001_initial.sql.
// Used by the "Reset to default" button (preset profiles only).
const PRESET_DEFAULTS: Record<
  string,
  { curve_points: CurvePoint[]; hysteresis: number; safety_threshold: number }
> = {
  Silent: {
    curve_points: [
      { temp: 30, speed: 20 }, { temp: 50, speed: 30 },
      { temp: 70, speed: 60 }, { temp: 85, speed: 100 },
    ],
    hysteresis: 3, safety_threshold: 85,
  },
  Balanced: {
    curve_points: [
      { temp: 30, speed: 30 }, { temp: 50, speed: 50 },
      { temp: 70, speed: 80 }, { temp: 80, speed: 100 },
    ],
    hysteresis: 3, safety_threshold: 85,
  },
  Performance: {
    curve_points: [
      { temp: 30, speed: 50 }, { temp: 50, speed: 70 },
      { temp: 70, speed: 90 }, { temp: 75, speed: 100 },
    ],
    hysteresis: 3, safety_threshold: 85,
  },
  "Full Speed": {
    curve_points: [
      { temp: 20, speed: 100 }, { temp: 100, speed: 100 },
    ],
    hysteresis: 3, safety_threshold: 85,
  },
};

/* ------------------------------------------------------------------ */
/*  Coordinate helpers                                                 */
/* ------------------------------------------------------------------ */

function tempToX(temp: number): number {
  return SVG_PAD_LEFT + ((temp - TEMP_MIN) / (TEMP_MAX - TEMP_MIN)) * PLOT_W;
}

function speedToY(speed: number): number {
  return SVG_PAD_TOP + (1 - (speed - SPEED_MIN) / (SPEED_MAX - SPEED_MIN)) * PLOT_H;
}

function xToTemp(x: number): number {
  const t = TEMP_MIN + ((x - SVG_PAD_LEFT) / PLOT_W) * (TEMP_MAX - TEMP_MIN);
  return Math.round(Math.max(TEMP_MIN, Math.min(TEMP_MAX, t)));
}

function yToSpeed(y: number): number {
  const s = SPEED_MAX - ((y - SVG_PAD_TOP) / PLOT_H) * (SPEED_MAX - SPEED_MIN);
  return Math.round(Math.max(SPEED_MIN, Math.min(SPEED_MAX, s)));
}

/* ------------------------------------------------------------------ */
/*  SVG Fan Curve Editor                                               */
/* ------------------------------------------------------------------ */

interface CurveEditorProps {
  points: CurvePoint[];
  onChange: (pts: CurvePoint[]) => void;
  currentTemp: number | null;
  readonly?: boolean;
  t: TFunction;
}

function CurveEditor({ points, onChange, currentTemp, readonly, t }: CurveEditorProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [dragging, setDragging] = useState<number | null>(null);
  // Unique gradient id per editor instance — avoids cross-component <defs> collisions.
  const gradientId = `tempGradient-${useId()}`;

  const sorted = [...points].sort((a, b) => a.temp - b.temp);

  // Build the path data
  const lineData = sorted.map((p) => `${tempToX(p.temp)},${speedToY(p.speed)}`).join(" L ");
  const linePath = sorted.length > 0 ? `M ${lineData}` : "";

  // Filled area under curve
  const areaPath =
    sorted.length > 0
      ? `M ${tempToX(sorted[0].temp)},${speedToY(0)} L ${lineData} L ${tempToX(sorted[sorted.length - 1].temp)},${speedToY(0)} Z`
      : "";

  // Current temp interpolated speed
  let currentSpeed: number | null = null;
  if (currentTemp !== null && sorted.length >= 2) {
    if (currentTemp <= sorted[0].temp) {
      currentSpeed = sorted[0].speed;
    } else if (currentTemp >= sorted[sorted.length - 1].temp) {
      currentSpeed = sorted[sorted.length - 1].speed;
    } else {
      for (let i = 0; i < sorted.length - 1; i++) {
        if (currentTemp >= sorted[i].temp && currentTemp <= sorted[i + 1].temp) {
          const ratio =
            (currentTemp - sorted[i].temp) / (sorted[i + 1].temp - sorted[i].temp);
          currentSpeed = Math.round(sorted[i].speed + ratio * (sorted[i + 1].speed - sorted[i].speed));
          break;
        }
      }
    }
  }

  const getSVGCoords = useCallback(
    (e: React.MouseEvent | MouseEvent): { x: number; y: number } => {
      const svg = svgRef.current;
      if (!svg) return { x: 0, y: 0 };
      const pt = svg.createSVGPoint();
      pt.x = e.clientX;
      pt.y = e.clientY;
      const ctm = svg.getScreenCTM();
      if (!ctm) return { x: 0, y: 0 };
      const svgPt = pt.matrixTransform(ctm.inverse());
      return { x: svgPt.x, y: svgPt.y };
    },
    []
  );

  const handleMouseMove = useCallback(
    (e: MouseEvent) => {
      if (dragging === null || readonly) return;
      const { x, y } = getSVGCoords(e);
      const newTemp = xToTemp(x);
      const newSpeed = yToSpeed(y);
      const next = points.map((p, i) =>
        i === dragging ? { temp: newTemp, speed: newSpeed } : p
      );
      onChange(next);
    },
    [dragging, points, onChange, getSVGCoords, readonly]
  );

  const handleMouseUp = useCallback(() => {
    setDragging(null);
  }, []);

  useEffect(() => {
    if (dragging !== null) {
      window.addEventListener("mousemove", handleMouseMove);
      window.addEventListener("mouseup", handleMouseUp);
      return () => {
        window.removeEventListener("mousemove", handleMouseMove);
        window.removeEventListener("mouseup", handleMouseUp);
      };
    }
  }, [dragging, handleMouseMove, handleMouseUp]);

  const handleSvgClick = (e: React.MouseEvent<SVGSVGElement>) => {
    if (readonly || dragging !== null) return;
    // Only add if clicking in the plot area
    const { x, y } = getSVGCoords(e);
    if (x < SVG_PAD_LEFT || x > SVG_PAD_LEFT + PLOT_W) return;
    if (y < SVG_PAD_TOP || y > SVG_PAD_TOP + PLOT_H) return;
    const newTemp = xToTemp(x);
    const newSpeed = yToSpeed(y);
    // Avoid placing too close to existing points
    if (points.some((p) => Math.abs(p.temp - newTemp) < 2)) return;
    onChange([...points, { temp: newTemp, speed: newSpeed }]);
  };

  const handleContextMenu = (e: React.MouseEvent, idx: number) => {
    e.preventDefault();
    if (readonly) return;
    if (points.length <= 2) {
      toast.error(t("fanpilot.curveMin2Points"));
      return;
    }
    onChange(points.filter((_, i) => i !== idx));
  };

  // Grid lines
  const tempTicks: number[] = [];
  for (let t = TEMP_MIN; t <= TEMP_MAX; t += 10) tempTicks.push(t);
  const speedTicks: number[] = [];
  for (let s = SPEED_MIN; s <= SPEED_MAX; s += 10) speedTicks.push(s);

  return (
    <svg
      ref={svgRef}
      viewBox={`0 0 ${SVG_WIDTH} ${SVG_HEIGHT}`}
      className="w-full h-full select-none"
      onClick={handleSvgClick}
    >
      {/* Background */}
      <rect
        x={SVG_PAD_LEFT}
        y={SVG_PAD_TOP}
        width={PLOT_W}
        height={PLOT_H}
        className="fill-muted/30"
        rx={4}
      />

      {/* Grid lines - vertical (temperature) */}
      {tempTicks.map((t) => (
        <line
          key={`vg-${t}`}
          x1={tempToX(t)}
          y1={SVG_PAD_TOP}
          x2={tempToX(t)}
          y2={SVG_PAD_TOP + PLOT_H}
          stroke="currentColor"
          className="text-border"
          strokeWidth={0.5}
          strokeDasharray={t === TEMP_MIN || t === TEMP_MAX ? undefined : "2,4"}
        />
      ))}

      {/* Grid lines - horizontal (speed) */}
      {speedTicks.map((s) => (
        <line
          key={`hg-${s}`}
          x1={SVG_PAD_LEFT}
          y1={speedToY(s)}
          x2={SVG_PAD_LEFT + PLOT_W}
          y2={speedToY(s)}
          stroke="currentColor"
          className="text-border"
          strokeWidth={0.5}
          strokeDasharray={s === SPEED_MIN || s === SPEED_MAX ? undefined : "2,4"}
        />
      ))}

      {/* X-axis labels */}
      {tempTicks
        .filter((t) => t % 20 === 0)
        .map((t) => (
          <text
            key={`xl-${t}`}
            x={tempToX(t)}
            y={SVG_PAD_TOP + PLOT_H + 16}
            textAnchor="middle"
            className="fill-muted-foreground"
            fontSize={10}
          >
            {t}°C
          </text>
        ))}

      {/* Y-axis labels */}
      {speedTicks
        .filter((s) => s % 20 === 0)
        .map((s) => (
          <text
            key={`yl-${s}`}
            x={SVG_PAD_LEFT - 8}
            y={speedToY(s) + 3}
            textAnchor="end"
            className="fill-muted-foreground"
            fontSize={10}
          >
            {s}%
          </text>
        ))}

      {/* Axis titles */}
      <text
        x={SVG_PAD_LEFT + PLOT_W / 2}
        y={SVG_HEIGHT - 2}
        textAnchor="middle"
        className="fill-muted-foreground"
        fontSize={10}
        fontWeight={500}
      >
        {t("fanpilot.axisTemperature")}
      </text>
      <text
        x={12}
        y={SVG_PAD_TOP + PLOT_H / 2}
        textAnchor="middle"
        className="fill-muted-foreground"
        fontSize={10}
        fontWeight={500}
        transform={`rotate(-90, 12, ${SVG_PAD_TOP + PLOT_H / 2})`}
      >
        {t("fanpilot.axisFanSpeed")}
      </text>

      {/* Temperature gradient — green<50 / yellow<65 / orange<80 / red≥80.
          gradientUnits="userSpaceOnUse" so the stops align with the plot's X range. */}
      <defs>
        <linearGradient
          id={gradientId}
          x1={SVG_PAD_LEFT}
          x2={SVG_PAD_LEFT + PLOT_W}
          y1="0"
          y2="0"
          gradientUnits="userSpaceOnUse"
        >
          <stop offset="0%" stopColor="#22c55e" />
          {/* 50°C = (50-20)/80 = 37.5% */}
          <stop offset="37.5%" stopColor="#22c55e" />
          {/* 65°C = 56.25% */}
          <stop offset="56.25%" stopColor="#eab308" />
          {/* 80°C = 75% */}
          <stop offset="75%" stopColor="#f97316" />
          <stop offset="100%" stopColor="#ef4444" />
        </linearGradient>
      </defs>

      {/* Filled area under curve — same temp gradient, fainter */}
      {sorted.length > 0 && (
        <path d={areaPath} fill={`url(#${gradientId})`} opacity={0.18} />
      )}

      {/* Curve line — colored by temperature along its length */}
      {sorted.length > 0 && (
        <path
          d={linePath}
          fill="none"
          stroke={`url(#${gradientId})`}
          strokeWidth={2.5}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      )}

      {/* Current temperature indicator — color tracks the temperature band */}
      {currentTemp !== null &&
        currentTemp >= TEMP_MIN &&
        currentTemp <= TEMP_MAX && (() => {
          const band = tempBand(currentTemp);
          return (
            <>
              <line
                x1={tempToX(currentTemp)}
                y1={SVG_PAD_TOP}
                x2={tempToX(currentTemp)}
                y2={SVG_PAD_TOP + PLOT_H}
                stroke={band.base}
                strokeWidth={1.5}
                strokeDasharray="4,3"
                opacity={0.85}
              />
              {/* Temp label — bigger + darker band shade for solid contrast vs white text */}
              <rect
                x={tempToX(currentTemp) - 26}
                y={SVG_PAD_TOP - 23}
                width={52}
                height={20}
                rx={5}
                fill={band.dark}
                opacity={0.95}
              />
              <text
                x={tempToX(currentTemp)}
                y={SVG_PAD_TOP - 9}
                textAnchor="middle"
                fill="white"
                fontSize={11}
                fontWeight={700}
              >
                {currentTemp}°C
              </text>
              {/* Dot on curve at current temp — halo + bigger main dot makes it visually
                  distinct from regular control points that share the same band color. */}
              {currentSpeed !== null && (
                <>
                  <circle
                    cx={tempToX(currentTemp)}
                    cy={speedToY(currentSpeed)}
                    r={10}
                    fill={band.base}
                    opacity={0.22}
                  />
                  <circle
                    cx={tempToX(currentTemp)}
                    cy={speedToY(currentSpeed)}
                    r={5.5}
                    fill={band.base}
                    stroke="white"
                    strokeWidth={2}
                  />
                </>
              )}
            </>
          );
        })()}

      {/* Draggable control points */}
      {sorted.map((p, i) => {
        // Find the original index for drag tracking
        const origIdx = points.findIndex(
          (op) => op.temp === p.temp && op.speed === p.speed
        );
        return (
          <g key={`pt-${i}`}>
            {/* Larger invisible hit area */}
            <circle
              cx={tempToX(p.temp)}
              cy={speedToY(p.speed)}
              r={12}
              fill="transparent"
              className={readonly ? "" : "cursor-grab"}
              onMouseDown={(e) => {
                if (readonly) return;
                e.stopPropagation();
                setDragging(origIdx);
              }}
              onContextMenu={(e) => handleContextMenu(e, origIdx)}
            />
            {/* Visible point — colored by its temperature band */}
            <circle
              cx={tempToX(p.temp)}
              cy={speedToY(p.speed)}
              r={5}
              fill={tempColor(p.temp)}
              stroke="white"
              strokeWidth={2}
              className={cn(
                "transition-transform",
                !readonly && "cursor-grab",
                dragging === origIdx && "cursor-grabbing"
              )}
              style={{ pointerEvents: "none" }}
            />
            {/* Tooltip while dragging — bigger and offset higher so it doesn't sit
                directly on top of the point being moved. */}
            {dragging === origIdx && (
              <>
                <rect
                  x={tempToX(p.temp) - 36}
                  y={speedToY(p.speed) - 32}
                  width={72}
                  height={22}
                  rx={5}
                  fill="#18181b"
                  opacity={0.92}
                />
                <text
                  x={tempToX(p.temp)}
                  y={speedToY(p.speed) - 17}
                  textAnchor="middle"
                  fill="white"
                  fontSize={11}
                  fontWeight={700}
                >
                  {p.temp}°C / {p.speed}%
                </text>
              </>
            )}
          </g>
        );
      })}
    </svg>
  );
}

/* ------------------------------------------------------------------ */
/*  Main FanPilot Page                                                 */
/* ------------------------------------------------------------------ */

export default function FanPilotPage() {
  const { t } = useTranslation();
  const contextServerId = useServerStore((s) => s.contextServerId);
  const sensorReadings = useSensorStore((s) =>
    (contextServerId ? s.readings[contextServerId] : undefined) ?? EMPTY_READINGS
  );
  const online = useBackendOnline();

  // Profiles
  const [profiles, setProfiles] = useState<FanProfile[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editedProfile, setEditedProfile] = useState<FanProfile | null>(null);

  // Fan status
  const [status, setStatus] = useState<FanStatus | null>(null);
  const [manualSpeed, setManualSpeed] = useState(50);
  const [modeLoading, setModeLoading] = useState(false);
  // Apply-in-flight guard: prevents the user from spamming Apply (which fired
  // multiple parallel POSTs and toasts) while a request is pending.
  const [applyingSpeed, setApplyingSpeed] = useState(false);
  // `manualSpeed` should reflect the operator's INTENT, not the polled fan state.
  // We seed it ONCE from the first status fetch so the slider starts where the BMC
  // actually is, then stop overwriting it from polling — otherwise the 5s status
  // poll would snap the slider back mid-edit (and the post-apply fetchStatus would
  // do the same before the BMC had reported the new value, making the user think
  // the click silently failed).
  const manualSpeedSeededRef = useRef(false);

  // Loading
  const [loading, setLoading] = useState(true);

  // Creating
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");

  // Top temp chips — expand state for "+N more"
  const [expandedTemps, setExpandedTemps] = useState(false);

  // Reset-to-default confirm state (preset profiles only)
  const [confirmingReset, setConfirmingReset] = useState(false);
  // Save-and-Activate loading state (disables both Save buttons during the 2-step call)
  const [activating, setActivating] = useState(false);

  // Locally-controlled string state for the numeric inputs so the user can clear the
  // field (it won't snap back to "0" while typing) and so we don't render the native
  // number-input stepper. Synced FROM editedProfile on profile switch + on Reset.
  const [hysteresisStr, setHysteresisStr] = useState("");
  const [safetyStr, setSafetyStr] = useState("");

  // Real temperature sensors on this server — vendor-agnostic, driven by the backend's
  // unit-derived `type` field. Replaces the hardcoded demo names ("CPU Temp", "Inlet Temp"...)
  // that don't exist on most BMCs (e.g. the R720 reports "CPU 1"/"CPU 2"/"Inlet Temp").
  const temperatureSensors = useMemo(
    () => sensorNamesForType(sensorReadings, "temperature"),
    [sensorReadings]
  );

  // Live temp comes from the EDITED profile's source sensor — whichever sensor the user
  // chose drives the indicator line on the curve and the background fanpilot loop.
  const sourceSensor = editedProfile?.source_sensor;
  const sourceReading = sourceSensor ? sensorReadings[sourceSensor] : undefined;
  const currentTemp = sourceReading?.value ?? null;

  // All temperature sensors with a numeric value, sorted by value desc (hottest first)
  // so the top-area chip strip surfaces the most relevant ones when capped.
  const allTempChips = useMemo(() => {
    const out: { name: string; value: number }[] = [];
    for (const name of temperatureSensors) {
      const r = sensorReadings[name];
      if (r?.value != null && typeof r.value === "number") {
        out.push({ name, value: r.value });
      }
    }
    return out.sort((a, b) => b.value - a.value);
  }, [temperatureSensors, sensorReadings]);

  /* ---------- Fetch profiles ---------- */
  const fetchProfiles = useCallback(async () => {
    try {
      // Backend returns { profiles: [...] } (routes.py:47), NOT a bare array.
      // Unwrap and guard so setProfiles only ever receives an array — otherwise
      // profiles.map(...) in render throws "c.map is not a function".
      const data = await get<{ profiles: FanProfile[] }>("/api/modules/fanpilot/profiles");
      const list = Array.isArray(data.profiles) ? data.profiles : [];
      setProfiles(list);
      if (list.length > 0 && !selectedId) {
        // Restore the operator's last-opened profile (typo-prevention against
        // re-picking Balanced every page visit). Falls back to list[0] when the
        // saved ID no longer exists (deleted) or storage is unavailable.
        let restoredId: string | number | null = null;
        try {
          const saved = localStorage.getItem(LAST_PROFILE_KEY);
          if (saved) {
            const match = list.find((p) => String(p.id) === saved);
            if (match) restoredId = match.id;
          }
        } catch { /* localStorage may throw in private browsing — ignore */ }
        setSelectedId(restoredId ?? list[0].id);
      }
    } catch {
      // API may not be ready yet
    }
  }, [selectedId]);

  /* ---------- Fetch status ---------- */
  const fetchStatus = useCallback(async () => {
    if (!contextServerId) return;
    try {
      // Backend status shape (routes.py:133-137) is { server_id, enabled, profile };
      // it does NOT include `mode` or `current_speed_pct`. So the mode-active
      // highlight (status?.mode === mode) simply never matches and the speed
      // readout (current_speed_pct != null) renders "--" — both best-effort and
      // null-safe. Not redesigned here (out of scope for the GAP-02 fix).
      const data = await get<FanStatus>(
        `/api/modules/fanpilot/${contextServerId}/status`
      );
      setStatus(data);
      // Seed the slider from the BMC ONCE (first successful status fetch). After
      // that, `manualSpeed` is purely operator-controlled — see manualSpeedSeededRef.
      if (data.current_speed_pct != null && !manualSpeedSeededRef.current) {
        setManualSpeed(data.current_speed_pct);
        manualSpeedSeededRef.current = true;
      }
    } catch {
      // Server may not support it yet
    }
  }, [contextServerId]);

  useEffect(() => {
    // New server context = re-seed the slider from that server's BMC. Without
    // resetting the ref the slider would keep showing the previous server's
    // last-set value when the operator switches servers.
    manualSpeedSeededRef.current = false;
    setLoading(true);
    Promise.all([fetchProfiles(), fetchStatus()]).finally(() => setLoading(false));
  }, [fetchProfiles, fetchStatus]);

  // Live status polling — keeps the Fan Mode highlight and the speed readout fresh
  // without requiring a page refresh after a mode change or a FanPilot tick.
  useEffect(() => {
    if (!contextServerId) return;
    const interval = setInterval(fetchStatus, 5000);
    return () => clearInterval(interval);
  }, [contextServerId, fetchStatus]);

  /* ---------- Persist last opened profile ---------- */
  useEffect(() => {
    if (selectedId == null) return;
    try {
      localStorage.setItem(LAST_PROFILE_KEY, String(selectedId));
    } catch { /* localStorage may throw in private browsing — ignore */ }
  }, [selectedId]);

  /* ---------- Sync editedProfile when selection changes ---------- */
  useEffect(() => {
    const profile = profiles.find((p) => p.id === selectedId);
    if (profile) {
      // Parse curve_points if it's a JSON string
      const pts =
        typeof profile.curve_points === "string"
          ? JSON.parse(profile.curve_points as unknown as string)
          : profile.curve_points;
      setEditedProfile({ ...profile, curve_points: pts });
    } else {
      setEditedProfile(null);
    }
  }, [selectedId, profiles]);

  /* ---------- Auto-fix invalid source_sensor ----------
   * If the profile's stored source_sensor doesn't exist on this server (a default
   * "CPU Temp" left over from demo, or a profile saved against another BMC), swap
   * it to the first real temperature sensor so the curve has live data. Local edit
   * only — requires Save to persist. */
  useEffect(() => {
    if (!editedProfile) return;
    if (temperatureSensors.length === 0) return;
    if (temperatureSensors.includes(editedProfile.source_sensor)) return;
    setEditedProfile((p) => (p ? { ...p, source_sensor: temperatureSensors[0] } : p));
  }, [editedProfile, temperatureSensors]);

  // Reset transient UI state when navigating to a different profile, and seed the
  // numeric-input strings from the loaded profile.
  useEffect(() => {
    setConfirmingReset(false);
    setExpandedTemps(false);
  }, [selectedId]);

  useEffect(() => {
    setHysteresisStr(editedProfile ? String(editedProfile.hysteresis) : "");
    setSafetyStr(editedProfile ? String(editedProfile.safety_threshold) : "");
  }, [editedProfile?.id]);

  // True when the profile in the editor IS the one currently driving the fans.
  // Drives the visibility of "Save and Activate" and keeps "Save" semantically
  // identical to "save the active profile and apply live".
  const isActiveProfile =
    !!editedProfile &&
    status?.mode === "fanpilot" &&
    status.profile != null &&
    String(status.profile.id) === String(editedProfile.id);

  /* ---------- Handlers ---------- */

  const handleSave = async () => {
    if (!editedProfile) return;
    try {
      await put(`/api/modules/fanpilot/profiles/${editedProfile.id}`, {
        name: editedProfile.name,
        description: editedProfile.description,
        curve_points: editedProfile.curve_points,
        hysteresis: editedProfile.hysteresis,
        safety_threshold: editedProfile.safety_threshold,
        source_sensor: editedProfile.source_sensor,
      });
      // If this profile is currently active, the backend wakes the loop on PUT so
      // the change reaches the fans within ~1s.
      toast.success(isActiveProfile ? t("fanpilot.savedApplyingLive") : t("fanpilot.profileSaved"));
      fetchProfiles();
    } catch (e: any) {
      toast.error(e.message || t("fanpilot.saveFailed"));
    }
  };

  // Save the profile and activate it on the current server (switches the server to
  // FanPilot mode if it isn't already). Only shown for non-active profiles.
  const handleSaveAndActivate = async () => {
    if (!editedProfile || !contextServerId) return;
    setActivating(true);
    try {
      await put(`/api/modules/fanpilot/profiles/${editedProfile.id}`, {
        name: editedProfile.name,
        description: editedProfile.description,
        curve_points: editedProfile.curve_points,
        hysteresis: editedProfile.hysteresis,
        safety_threshold: editedProfile.safety_threshold,
        source_sensor: editedProfile.source_sensor,
      });
      await post(`/api/modules/fanpilot/${contextServerId}/mode`, {
        mode: "fanpilot",
        profile_id: editedProfile.id,
      });
      toast.success(t("fanpilot.savedAndActivated", { name: editedProfile.name }));
      fetchProfiles();
      fetchStatus();
    } catch (e: any) {
      toast.error(e.message || t("fanpilot.saveActivateFailed"));
    } finally {
      setActivating(false);
    }
  };

  // Reset a preset profile to its migration defaults — local edit only, user clicks
  // Save (or Save and Activate) to persist. source_sensor is intentionally NOT reset
  // because the migration default ("CPU Temp") is the demo bug we already fixed; the
  // auto-fix effect handles invalid sensors transparently.
  const handleReset = () => {
    if (!editedProfile || !editedProfile.is_preset) return;
    const defaults = PRESET_DEFAULTS[editedProfile.name];
    if (!defaults) {
      toast.error(t("fanpilot.noDefaultForPreset"));
      return;
    }
    setEditedProfile({
      ...editedProfile,
      curve_points: defaults.curve_points,
      hysteresis: defaults.hysteresis,
      safety_threshold: defaults.safety_threshold,
    });
    // Keep the local numeric-input strings in sync (their effect is keyed on profile id,
    // which doesn't change on reset, so we have to bump them explicitly).
    setHysteresisStr(String(defaults.hysteresis));
    setSafetyStr(String(defaults.safety_threshold));
    setConfirmingReset(false);
    toast.success(t("fanpilot.resetPersistHint"));
  };

  const handleCreate = async () => {
    if (!newName.trim()) return;
    try {
      // POST /profiles returns { success, profile_id } (routes.py:61), NOT a
      // FanProfile. Select the new profile by its returned id (coerced to string
      // — FanProfile ids are strings).
      const created = await post<{ success: boolean; profile_id: number }>(
        "/api/modules/fanpilot/profiles",
        {
          name: newName.trim(),
          description: "Custom profile",
          curve_points: [
            { temp: 30, speed: 20 },
            { temp: 50, speed: 40 },
            { temp: 70, speed: 60 },
            { temp: 85, speed: 80 },
            { temp: 95, speed: 100 },
          ],
          hysteresis: 3,
          safety_threshold: 85,
          source_sensor: "CPU Temp",
        }
      );
      toast.success(t("fanpilot.profileCreated"));
      setCreating(false);
      setNewName("");
      await fetchProfiles();
      if (created.profile_id != null) {
        setSelectedId(String(created.profile_id));
      }
    } catch (e: any) {
      toast.error(e.message || t("fanpilot.createFailed"));
    }
  };

  const handleDelete = async () => {
    if (!editedProfile || editedProfile.is_preset) return;
    try {
      await del(`/api/modules/fanpilot/profiles/${editedProfile.id}`);
      toast.success(t("fanpilot.profileDeleted"));
      setSelectedId(null);
      fetchProfiles();
    } catch (e: any) {
      toast.error(e.message || t("fanpilot.deleteFailed"));
    }
  };

  const handleModeChange = async (mode: FanMode) => {
    if (!contextServerId) return;
    setModeLoading(true);
    try {
      const body: Record<string, unknown> = { mode };
      if (mode === "manual") body.speed = manualSpeed;
      if (mode === "fanpilot" && selectedId) body.profile_id = selectedId;
      await post(`/api/modules/fanpilot/${contextServerId}/mode`, body);
      const modeLabel =
        mode === "auto" ? t("fanpilot.modeAuto")
        : mode === "manual" ? t("fanpilot.modeManual")
        : t("fanpilot.modeFanpilot");
      toast.success(t("fanpilot.modeSet", { mode: modeLabel }));
      fetchStatus();
    } catch (e: any) {
      toast.error(e.message || t("fanpilot.setModeFailed"));
    } finally {
      setModeLoading(false);
    }
  };

  const handleManualSpeedApply = async () => {
    if (!contextServerId || applyingSpeed) return; // re-entrancy guard
    setApplyingSpeed(true);
    const speedToApply = manualSpeed;
    try {
      await post(`/api/modules/fanpilot/${contextServerId}/mode`, {
        mode: "manual",
        speed: speedToApply,
      });
      toast.success(t("fanpilot.manualSpeedSet", { speed: speedToApply }));
      // Skip fetchStatus() here: the BMC reads back through the next sensor poll
      // (~5-10s after the wake_sensor_loop hook); calling /status now would just
      // return the stale pre-apply value and look like the change didn't take.
    } catch (e: any) {
      toast.error(e.message || t("fanpilot.setSpeedFailed"));
    } finally {
      setApplyingSpeed(false);
    }
  };

  /* ---------- Render ---------- */

  if (!contextServerId) {
    return (
      <>
        <Header title={t("nav.fanpilot")} />
        <div className="flex-1 overflow-auto p-6">
          <EmptyState
            icon={Fan}
            title={t("fanpilot.noServerTitle")}
            description={t("fanpilot.noServerDescription")}
          />
        </div>
      </>
    );
  }

  return (
    <>
      <Header title={t("nav.fanpilot")}>
        {online && status && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Fan className="h-3.5 w-3.5" />
            <span>
              {status.current_speed_pct != null ? `${status.current_speed_pct}%` : "--"}
            </span>
          </div>
        )}
      </Header>

      <div className="flex flex-1 overflow-hidden">
        {/* ---- Left panel: Profile list ---- */}
        <aside className="flex w-56 shrink-0 flex-col border-r border-border bg-card">
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              {t("fanpilot.profiles")}
            </span>
            <button
              onClick={() => setCreating(true)}
              disabled={!online}
              className="flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground transition-colors disabled:cursor-not-allowed disabled:opacity-40"
              title={online ? t("fanpilot.createProfile") : t("header.backendDisconnected")}
            >
              <Plus className="h-3.5 w-3.5" />
            </button>
          </div>

          <div className="flex-1 overflow-y-auto p-2 space-y-0.5">
            {profiles.map((p) => {
              // The profile currently driving the fans (FanPilot mode + this profile id).
              const isActive =
                status?.mode === "fanpilot" &&
                status.profile != null &&
                String(status.profile.id) === String(p.id);
              return (
                <button
                  key={p.id}
                  onClick={() => setSelectedId(p.id)}
                  className={cn(
                    "flex w-full items-center gap-2.5 rounded-md px-3 py-2 text-left text-sm transition-colors",
                    selectedId === p.id
                      ? "bg-muted text-foreground"
                      : "text-muted-foreground hover:bg-muted/50 hover:text-foreground"
                  )}
                >
                  <span className="shrink-0">
                    {PRESET_ICONS[p.name] ?? <SlidersHorizontal className="h-4 w-4" />}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex min-w-0 items-center gap-1.5">
                      <span className="truncate font-medium text-[13px]">{p.name}</span>
                      {isActive && (
                        <span className="flex shrink-0 items-center gap-1 rounded-full bg-emerald-500/15 px-1.5 py-0.5 text-[9px] font-semibold text-emerald-500">
                          <span className="h-1 w-1 rounded-full bg-emerald-500" />
                          {t("fanpilot.active")}
                        </span>
                      )}
                    </div>
                    {p.description && (
                      <div className="truncate text-[11px] text-muted-foreground">
                        {p.description}
                      </div>
                    )}
                  </div>
                  {selectedId === p.id && (
                    <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                  )}
                </button>
              );
            })}

            {/* Inline create form */}
            {creating && (
              <div className="mt-1 rounded-md border border-border bg-muted/30 p-2">
                <input
                  autoFocus
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") handleCreate();
                    if (e.key === "Escape") {
                      setCreating(false);
                      setNewName("");
                    }
                  }}
                  placeholder={t("fanpilot.profileNamePlaceholder")}
                  className="w-full rounded-md border border-input bg-background px-2 py-1 text-xs outline-none focus:ring-1 focus:ring-ring"
                />
                <div className="mt-1.5 flex gap-1">
                  <button
                    onClick={handleCreate}
                    disabled={!online}
                    title={!online ? t("header.backendDisconnected") : undefined}
                    className="flex-1 rounded-md bg-primary px-2 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {t("fanpilot.create")}
                  </button>
                  <button
                    onClick={() => {
                      setCreating(false);
                      setNewName("");
                    }}
                    className="flex-1 rounded-md bg-muted px-2 py-1 text-xs font-medium text-muted-foreground hover:text-foreground"
                  >
                    {t("fanpilot.cancel")}
                  </button>
                </div>
              </div>
            )}

            {profiles.length === 0 && !loading && (
              <p className="px-3 py-6 text-center text-xs text-muted-foreground">
                {t("fanpilot.noProfilesHint")}
              </p>
            )}
          </div>
        </aside>

        {/* ---- Center: Curve editor ---- */}
        <main className="flex flex-1 flex-col overflow-hidden">
          <div className="flex-1 overflow-auto p-6">
            {editedProfile ? (
              <div className="flex gap-6 h-full">
                {/* Curve editor */}
                <div className="flex-1 flex flex-col min-w-0">
                  <div className="mb-3 flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <h2 className="text-sm font-semibold">{editedProfile.name}</h2>
                      <p className="text-xs text-muted-foreground">
                        {t("fanpilot.editorHint")}
                      </p>
                    </div>
                    {/* Color-coded temperature strip — all temperature sensors on this server,
                        hottest first. Capped to 4 chips with a "+N more" toggle. Dimmed when
                        offline because the values shown are the LAST known ones, not live. */}
                    {allTempChips.length > 0 && (
                      <div
                        className={cn(
                          "flex max-w-[60%] flex-wrap items-center justify-end gap-1.5 transition-[filter,opacity]",
                          !online && "opacity-50 grayscale"
                        )}
                      >
                        <Thermometer className="h-3 w-3 shrink-0 text-muted-foreground" />
                        {(expandedTemps ? allTempChips : allTempChips.slice(0, 4)).map((t) => (
                          <span
                            key={t.name}
                            className={cn(
                              "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px]",
                              tempChipClass(t.value)
                            )}
                            title={`${t.name}: ${t.value}°C`}
                          >
                            <span className="opacity-80">{t.name}</span>
                            <span className="font-mono font-semibold">{t.value}°C</span>
                          </span>
                        ))}
                        {!expandedTemps && allTempChips.length > 4 && (
                          <button
                            onClick={() => setExpandedTemps(true)}
                            className="rounded-full border border-border bg-muted/50 px-2 py-0.5 text-[11px] text-muted-foreground hover:bg-muted"
                          >
                            {t("fanpilot.moreCount", { count: allTempChips.length - 4 })}
                          </button>
                        )}
                        {expandedTemps && allTempChips.length > 4 && (
                          <button
                            onClick={() => setExpandedTemps(false)}
                            className="rounded-full border border-border bg-muted/50 px-2 py-0.5 text-[11px] text-muted-foreground hover:bg-muted"
                          >
                            {t("fanpilot.collapse")}
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                  <div className="flex-1 rounded-lg border border-border bg-card p-3 min-h-[300px]">
                    <CurveEditor
                      points={editedProfile.curve_points}
                      onChange={(pts) =>
                        setEditedProfile({ ...editedProfile, curve_points: pts })
                      }
                      // Hide the live temp indicator when the backend is offline —
                      // continuing to draw a position based on the last known temp
                      // would imply a fresh reading we don't actually have.
                      currentTemp={online ? currentTemp : null}
                      t={t}
                    />
                  </div>

                  {/* Point table */}
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {[...editedProfile.curve_points]
                      .sort((a, b) => a.temp - b.temp)
                      .map((pt, i) => (
                        <span
                          key={i}
                          className="inline-flex items-center rounded-md border border-border bg-muted/50 px-2 py-0.5 text-[11px] font-mono text-muted-foreground"
                        >
                          {pt.temp}°C <span className="mx-1 text-border">/</span> {pt.speed}%
                        </span>
                      ))}
                  </div>
                </div>

                {/* ---- Right panel: Profile settings ---- */}
                <div className="w-60 shrink-0 space-y-4">
                  <div className="rounded-lg border border-border bg-card p-4 space-y-4">
                    <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                      {t("fanpilot.profileSettings")}
                    </h3>

                    {/* Source sensor — real sensors from this server, with the live value
                        inline so the user sees what the curve is actually reacting to. */}
                    <div>
                      <div className="mb-1 flex items-center justify-between">
                        <label className="text-xs font-medium text-muted-foreground">{t("fanpilot.sourceSensor")}</label>
                        {/* Hide the inline live reading when offline so we don't contradict
                            the CurveEditor (which already suppresses its live indicator). */}
                        {online && currentTemp !== null && (
                          <span className="font-mono text-[11px] text-foreground">
                            {currentTemp}°C
                          </span>
                        )}
                      </div>
                      <select
                        value={editedProfile.source_sensor}
                        onChange={(e) =>
                          setEditedProfile({ ...editedProfile, source_sensor: e.target.value })
                        }
                        disabled={temperatureSensors.length === 0}
                        className="w-full rounded-md border border-input bg-background px-2.5 py-1.5 text-xs outline-none focus:ring-1 focus:ring-ring disabled:opacity-50"
                      >
                        {temperatureSensors.length === 0 && (
                          <option value="">{t("fanpilot.noTempSensors")}</option>
                        )}
                        {temperatureSensors.map((name) => {
                          const r = sensorReadings[name];
                          // Same rationale as the inline readout above: drop the live value
                          // suffix from option labels when the backend is offline.
                          const live = online && r?.value != null ? ` — ${r.value}°C` : "";
                          return (
                            <option key={name} value={name}>
                              {name}{live}
                            </option>
                          );
                        })}
                        {/* Stored value not on this server: surface it so the select stays
                            controlled until the auto-fix effect swaps it. */}
                        {editedProfile.source_sensor &&
                          !temperatureSensors.includes(editedProfile.source_sensor) && (
                            <option value={editedProfile.source_sensor}>
                              {t("fanpilot.notOnThisServer", { name: editedProfile.source_sensor })}
                            </option>
                          )}
                      </select>
                      <p className="mt-0.5 text-[10px] text-muted-foreground">
                        {t("fanpilot.sourceSensorHint")}
                      </p>
                    </div>

                    {/* Hysteresis — text input + decimal inputMode so the native spinner
                        is gone AND the user can clear the field without it snapping back to 0.
                        Range clamping happens on blur. */}
                    <div>
                      <label className="mb-1 block text-xs font-medium text-muted-foreground">
                        {t("fanpilot.hysteresis")}
                      </label>
                      <input
                        type="text"
                        inputMode="decimal"
                        value={hysteresisStr}
                        onChange={(e) => {
                          const v = e.target.value.replace(/[^\d.]/g, "");
                          setHysteresisStr(v);
                          if (v === "") return;
                          const n = parseFloat(v);
                          if (!isNaN(n) && editedProfile && n >= 0 && n <= 20) {
                            setEditedProfile({ ...editedProfile, hysteresis: n });
                          }
                        }}
                        onBlur={() => {
                          if (!editedProfile) return;
                          const n = parseFloat(hysteresisStr);
                          if (isNaN(n)) {
                            setHysteresisStr(String(editedProfile.hysteresis));
                            return;
                          }
                          const clamped = Math.max(0, Math.min(20, n));
                          setHysteresisStr(String(clamped));
                          if (clamped !== editedProfile.hysteresis) {
                            setEditedProfile({ ...editedProfile, hysteresis: clamped });
                          }
                        }}
                        className="w-full rounded-md border border-input bg-background px-2.5 py-1.5 text-xs outline-none focus:ring-1 focus:ring-ring"
                      />
                      <p className="mt-0.5 text-[10px] text-muted-foreground">
                        {t("fanpilot.hysteresisHint")}
                      </p>
                    </div>

                    {/* Safety threshold — same pattern */}
                    <div>
                      <label className="mb-1 flex items-center gap-1 text-xs font-medium text-muted-foreground">
                        <AlertTriangle className="h-3 w-3 text-warning" />
                        {t("fanpilot.safetyThreshold")}
                      </label>
                      <input
                        type="text"
                        inputMode="decimal"
                        value={safetyStr}
                        onChange={(e) => {
                          const v = e.target.value.replace(/[^\d.]/g, "");
                          setSafetyStr(v);
                          if (v === "") return;
                          const n = parseFloat(v);
                          if (!isNaN(n) && editedProfile && n >= 0 && n <= 105) {
                            setEditedProfile({ ...editedProfile, safety_threshold: n });
                          }
                        }}
                        onBlur={() => {
                          if (!editedProfile) return;
                          const n = parseFloat(safetyStr);
                          if (isNaN(n)) {
                            setSafetyStr(String(editedProfile.safety_threshold));
                            return;
                          }
                          const clamped = Math.max(0, Math.min(105, n));
                          setSafetyStr(String(clamped));
                          if (clamped !== editedProfile.safety_threshold) {
                            setEditedProfile({ ...editedProfile, safety_threshold: clamped });
                          }
                        }}
                        className="w-full rounded-md border border-input bg-background px-2.5 py-1.5 text-xs outline-none focus:ring-1 focus:ring-ring"
                      />
                      <p className="mt-0.5 text-[10px] text-muted-foreground">
                        {t("fanpilot.safetyThresholdHint")}
                      </p>
                    </div>

                    {/* Actions — vertical stack:
                          [Save]                  ← always
                          [Save and Activate]     ← only when this profile is NOT the active one
                          [Reset to default]      ← presets only, with inline confirm
                          [Delete]                ← custom profiles only
                        Save semantics: on the active profile, the backend wakes the
                        loop so changes go live within ~1s; on a non-active profile,
                        Save just persists without activating. */}
                    <div className="space-y-2 border-t border-border pt-3">
                      <button
                        onClick={handleSave}
                        disabled={activating || !online}
                        title={!online ? t("header.backendDisconnected") : undefined}
                        className="flex w-full items-center justify-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        <Save className="h-3 w-3" />
                        {t("fanpilot.save")}
                      </button>

                      {!isActiveProfile && (
                        <button
                          onClick={handleSaveAndActivate}
                          disabled={activating || !contextServerId || !online}
                          title={!online ? t("header.backendDisconnected") : undefined}
                          className="flex w-full items-center justify-center gap-1.5 rounded-md border border-primary/40 bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                          <Fan className="h-3 w-3" />
                          {activating ? t("fanpilot.activating") : t("fanpilot.saveAndActivate")}
                        </button>
                      )}

                      {editedProfile.is_preset ? (
                        !confirmingReset ? (
                          <button
                            onClick={() => setConfirmingReset(true)}
                            className="flex w-full items-center justify-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-muted-foreground hover:bg-muted transition-colors"
                          >
                            <RotateCcw className="h-3 w-3" />
                            {t("fanpilot.resetToDefault")}
                          </button>
                        ) : (
                          <div className="rounded-md border border-red-500/30 bg-red-500/5 p-2.5">
                            <div className="flex items-start gap-1.5">
                              <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0 text-red-500" />
                              <p className="text-[11px] leading-tight text-muted-foreground">
                                <Trans
                                  i18nKey="fanpilot.resetConfirm"
                                  values={{ name: editedProfile.name }}
                                  components={[<span className="font-medium text-foreground" />]}
                                />
                              </p>
                            </div>
                            <div className="mt-2 flex gap-1.5">
                              <button
                                onClick={() => setConfirmingReset(false)}
                                className="flex-1 rounded-md border border-border px-2 py-1 text-[11px] font-medium text-muted-foreground hover:bg-muted"
                              >
                                {t("fanpilot.cancel")}
                              </button>
                              <button
                                onClick={handleReset}
                                className="flex-1 rounded-md bg-red-500 px-2 py-1 text-[11px] font-semibold text-white hover:bg-red-600"
                              >
                                {t("fanpilot.reset")}
                              </button>
                            </div>
                          </div>
                        )
                      ) : (
                        <button
                          onClick={handleDelete}
                          disabled={!online}
                          title={!online ? t("header.backendDisconnected") : undefined}
                          className="flex w-full items-center justify-center gap-1.5 rounded-md bg-destructive/10 px-3 py-1.5 text-xs font-medium text-destructive hover:bg-destructive/20 transition-colors disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          <Trash2 className="h-3 w-3" />
                          {t("fanpilot.delete")}
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            ) : loading ? (
              <EmptyState
                icon={Fan}
                title={t("fanpilot.loadingProfilesTitle")}
                description={t("fanpilot.loadingProfilesDescription")}
              />
            ) : profiles.length === 0 ? (
              <EmptyState
                icon={Fan}
                title={t("fanpilot.noProfilesTitle")}
                description={t("fanpilot.noProfilesDescription")}
                action={{ label: t("fanpilot.createProfileCta"), onClick: () => setCreating(true) }}
              />
            ) : (
              <EmptyState
                icon={Fan}
                title={t("fanpilot.selectProfileTitle")}
                description={t("fanpilot.selectProfileDescription")}
              />
            )}
          </div>

          {/* ---- Bottom bar: Fan mode + live status ---- */}
          <div className="shrink-0 border-t border-border bg-card px-6 py-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              {/* LEFT: mode toggle with icons + tooltips */}
              <div className="flex items-center gap-3">
                <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  {t("fanpilot.fanMode")}
                </span>
                <div className="flex items-center gap-1 rounded-lg bg-muted p-0.5">
                  {MODE_OPTIONS.map(({ mode, labelKey, descKey, icon: Icon }) => {
                    const active = status?.mode === mode;
                    return (
                      <button
                        key={mode}
                        disabled={modeLoading || !online}
                        onClick={() => handleModeChange(mode)}
                        title={!online ? t("header.backendDisconnected") : t(descKey)}
                        className={cn(
                          "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
                          active
                            ? "bg-background text-foreground shadow-sm"
                            : "text-muted-foreground hover:text-foreground"
                        )}
                      >
                        <Icon className="h-3.5 w-3.5" />
                        {t(labelKey)}
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* RIGHT: live status readout — gated on `online` so a stale spinning fan
                  or cached speed % never lies about the current state. When offline we
                  surface a plain "Disconnected" instead of the last-known mode. */}
              <div className="flex min-w-0 items-center gap-2 text-xs">
                {!online && (
                  <span className="text-red-500/80">{t("fanpilot.disconnectedStatus")}</span>
                )}
                {online && status?.mode === "auto" && (
                  <span className="text-muted-foreground">{t("fanpilot.bmcControlling")}</span>
                )}
                {online && status?.mode === "manual" && (
                  <span className="text-muted-foreground">
                    {t("fanpilot.fixedAt")}{" "}
                    <span className="font-mono font-semibold text-foreground">
                      {status.current_speed_pct ?? "—"}%
                    </span>
                  </span>
                )}
                {online && status?.mode === "fanpilot" && (
                  <div className="flex items-center gap-1.5">
                    <Fan
                      className="h-3.5 w-3.5 animate-spin text-blue-500"
                      style={{ animationDuration: "3s" }}
                    />
                    <span className="text-muted-foreground">{t("fanpilot.profileLabel")}</span>
                    <span className="font-medium text-foreground">
                      {status.profile?.name ?? "—"}
                    </span>
                    <span className="text-muted-foreground">·</span>
                    <span className="font-mono font-semibold text-foreground">
                      {status.current_speed_pct ?? "—"}%
                    </span>
                  </div>
                )}
              </div>
            </div>

            {/* Manual speed control — full row, only while in manual mode */}
            {status?.mode === "manual" && (
              <div className="mt-3 flex items-center gap-3">
                <span className="text-xs text-muted-foreground">{t("fanpilot.setSpeed")}</span>
                <input
                  type="range"
                  min={0}
                  max={100}
                  value={manualSpeed}
                  onChange={(e) => setManualSpeed(Number(e.target.value))}
                  className="h-1.5 max-w-xs flex-1 cursor-pointer appearance-none rounded-full bg-muted [&::-webkit-slider-thumb]:h-3.5 [&::-webkit-slider-thumb]:w-3.5 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-primary [&::-webkit-slider-thumb]:cursor-grab"
                />
                <span className="w-10 text-right text-xs font-mono font-medium">
                  {manualSpeed}%
                </span>
                <button
                  onClick={handleManualSpeedApply}
                  disabled={!online || applyingSpeed}
                  title={!online ? t("header.backendDisconnected") : undefined}
                  className="rounded-md bg-primary px-3 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90 transition-colors disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {applyingSpeed ? t("fanpilot.applying") : t("fanpilot.apply")}
                </button>
              </div>
            )}
          </div>
        </main>
      </div>
    </>
  );
}
