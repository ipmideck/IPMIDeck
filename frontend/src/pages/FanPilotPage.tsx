import { useState, useEffect, useCallback, useRef } from "react";
import { Header } from "@/components/layout/Header";
import { useServerStore } from "@/stores/server-store";
import { useSensorStore } from "@/stores/sensor-store";
import { get, post, put, del } from "@/api/client";
import { cn } from "@/lib/utils";
import { EmptyState } from "@/components/common/EmptyState";
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
  profile: string | null;
  current_speed_pct: number;
}

type FanMode = "auto" | "manual" | "fanpilot";

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

const TEMP_MIN = 20;
const TEMP_MAX = 100;
const SPEED_MIN = 0;
const SPEED_MAX = 100;

// SVG viewport dimensions for the curve editor
const SVG_PAD_LEFT = 48;
const SVG_PAD_RIGHT = 16;
const SVG_PAD_TOP = 16;
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

const SENSOR_OPTIONS = [
  "CPU Temp",
  "Inlet Temp",
  "Exhaust Temp",
  "System Temp",
  "GPU Temp",
  "PCH Temp",
];

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
}

function CurveEditor({ points, onChange, currentTemp, readonly }: CurveEditorProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [dragging, setDragging] = useState<number | null>(null);

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
      toast.error("Curve must have at least 2 points");
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
        Temperature
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
        Fan Speed
      </text>

      {/* Filled area under curve */}
      {sorted.length > 0 && (
        <path d={areaPath} fill="#2563eb" opacity={0.08} />
      )}

      {/* Curve line */}
      {sorted.length > 0 && (
        <path d={linePath} fill="none" stroke="#2563eb" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" />
      )}

      {/* Current temperature indicator */}
      {currentTemp !== null &&
        currentTemp >= TEMP_MIN &&
        currentTemp <= TEMP_MAX && (
          <>
            <line
              x1={tempToX(currentTemp)}
              y1={SVG_PAD_TOP}
              x2={tempToX(currentTemp)}
              y2={SVG_PAD_TOP + PLOT_H}
              stroke="#ef4444"
              strokeWidth={1.5}
              strokeDasharray="4,3"
              opacity={0.8}
            />
            {/* Temp label */}
            <rect
              x={tempToX(currentTemp) - 20}
              y={SVG_PAD_TOP - 14}
              width={40}
              height={16}
              rx={4}
              fill="#ef4444"
              opacity={0.9}
            />
            <text
              x={tempToX(currentTemp)}
              y={SVG_PAD_TOP - 3}
              textAnchor="middle"
              fill="white"
              fontSize={9}
              fontWeight={600}
            >
              {currentTemp}°C
            </text>
            {/* Dot on curve at current temp */}
            {currentSpeed !== null && (
              <circle
                cx={tempToX(currentTemp)}
                cy={speedToY(currentSpeed)}
                r={4}
                fill="#ef4444"
                stroke="white"
                strokeWidth={1.5}
              />
            )}
          </>
        )}

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
            {/* Visible point */}
            <circle
              cx={tempToX(p.temp)}
              cy={speedToY(p.speed)}
              r={5}
              fill="#2563eb"
              stroke="white"
              strokeWidth={2}
              className={cn(
                "transition-transform",
                !readonly && "cursor-grab",
                dragging === origIdx && "cursor-grabbing"
              )}
              style={{ pointerEvents: "none" }}
            />
            {/* Tooltip label */}
            {dragging === origIdx && (
              <>
                <rect
                  x={tempToX(p.temp) - 28}
                  y={speedToY(p.speed) - 24}
                  width={56}
                  height={18}
                  rx={4}
                  fill="#18181b"
                  opacity={0.9}
                />
                <text
                  x={tempToX(p.temp)}
                  y={speedToY(p.speed) - 12}
                  textAnchor="middle"
                  fill="white"
                  fontSize={9}
                  fontWeight={500}
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
  const contextServerId = useServerStore((s) => s.contextServerId);
  const sensorReadings = useSensorStore((s) =>
    contextServerId ? s.readings[contextServerId] ?? {} : {}
  );

  // Profiles
  const [profiles, setProfiles] = useState<FanProfile[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editedProfile, setEditedProfile] = useState<FanProfile | null>(null);

  // Fan status
  const [status, setStatus] = useState<FanStatus | null>(null);
  const [manualSpeed, setManualSpeed] = useState(50);
  const [modeLoading, setModeLoading] = useState(false);

  // Loading
  const [loading, setLoading] = useState(true);

  // Creating
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");

  // Derive current CPU temp from sensor store
  const cpuTempReading = sensorReadings["CPU Temp"] ?? sensorReadings["CPU Temperature"] ?? null;
  const currentTemp = cpuTempReading?.value ?? null;

  /* ---------- Fetch profiles ---------- */
  const fetchProfiles = useCallback(async () => {
    try {
      const data = await get<FanProfile[]>("/api/modules/fanpilot/profiles");
      setProfiles(data);
      if (data.length > 0 && !selectedId) {
        setSelectedId(data[0].id);
      }
    } catch {
      // API may not be ready yet
    }
  }, [selectedId]);

  /* ---------- Fetch status ---------- */
  const fetchStatus = useCallback(async () => {
    if (!contextServerId) return;
    try {
      const data = await get<FanStatus>(
        `/api/modules/fanpilot/${contextServerId}/status`
      );
      setStatus(data);
      if (data.current_speed_pct) setManualSpeed(data.current_speed_pct);
    } catch {
      // Server may not support it yet
    }
  }, [contextServerId]);

  useEffect(() => {
    setLoading(true);
    Promise.all([fetchProfiles(), fetchStatus()]).finally(() => setLoading(false));
  }, [fetchProfiles, fetchStatus]);

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
      toast.success("Profile saved");
      fetchProfiles();
    } catch (e: any) {
      toast.error(e.message || "Failed to save profile");
    }
  };

  const handleCreate = async () => {
    if (!newName.trim()) return;
    try {
      const created = await post<FanProfile>("/api/modules/fanpilot/profiles", {
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
      });
      toast.success("Profile created");
      setCreating(false);
      setNewName("");
      await fetchProfiles();
      setSelectedId(created.id);
    } catch (e: any) {
      toast.error(e.message || "Failed to create profile");
    }
  };

  const handleDelete = async () => {
    if (!editedProfile || editedProfile.is_preset) return;
    try {
      await del(`/api/modules/fanpilot/profiles/${editedProfile.id}`);
      toast.success("Profile deleted");
      setSelectedId(null);
      fetchProfiles();
    } catch (e: any) {
      toast.error(e.message || "Failed to delete profile");
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
      toast.success(`Mode set to ${mode === "auto" ? "BMC Auto" : mode === "manual" ? "Manual" : "FanPilot"}`);
      fetchStatus();
    } catch (e: any) {
      toast.error(e.message || "Failed to set mode");
    } finally {
      setModeLoading(false);
    }
  };

  const handleManualSpeedApply = async () => {
    if (!contextServerId) return;
    try {
      await post(`/api/modules/fanpilot/${contextServerId}/mode`, {
        mode: "manual",
        speed: manualSpeed,
      });
      toast.success(`Manual speed set to ${manualSpeed}%`);
      fetchStatus();
    } catch (e: any) {
      toast.error(e.message || "Failed to set speed");
    }
  };

  /* ---------- Render ---------- */

  if (!contextServerId) {
    return (
      <>
        <Header title="FanPilot" />
        <div className="flex-1 overflow-auto p-6">
          <EmptyState
            icon={Fan}
            title="No server selected"
            description="Select a server from the sidebar to manage fan profiles and curves."
          />
        </div>
      </>
    );
  }

  return (
    <>
      <Header title="FanPilot">
        {status && (
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
              Profiles
            </span>
            <button
              onClick={() => setCreating(true)}
              className="flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
              title="Create profile"
            >
              <Plus className="h-3.5 w-3.5" />
            </button>
          </div>

          <div className="flex-1 overflow-y-auto p-2 space-y-0.5">
            {profiles.map((p) => (
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
                  <div className="truncate font-medium text-[13px]">{p.name}</div>
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
            ))}

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
                  placeholder="Profile name..."
                  className="w-full rounded-md border border-input bg-background px-2 py-1 text-xs outline-none focus:ring-1 focus:ring-ring"
                />
                <div className="mt-1.5 flex gap-1">
                  <button
                    onClick={handleCreate}
                    className="flex-1 rounded-md bg-primary px-2 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90"
                  >
                    Create
                  </button>
                  <button
                    onClick={() => {
                      setCreating(false);
                      setNewName("");
                    }}
                    className="flex-1 rounded-md bg-muted px-2 py-1 text-xs font-medium text-muted-foreground hover:text-foreground"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}

            {profiles.length === 0 && !loading && (
              <p className="px-3 py-6 text-center text-xs text-muted-foreground">
                No profiles found. The backend may still be loading.
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
                  <div className="mb-3 flex items-center justify-between">
                    <div>
                      <h2 className="text-sm font-semibold">{editedProfile.name}</h2>
                      <p className="text-xs text-muted-foreground">
                        Click to add points. Drag to move. Right-click to remove.
                      </p>
                    </div>
                    {currentTemp !== null && (
                      <div className="flex items-center gap-1.5 rounded-full bg-red-500/10 px-2.5 py-1 text-xs font-medium text-red-500">
                        <Thermometer className="h-3 w-3" />
                        {currentTemp}°C
                      </div>
                    )}
                  </div>
                  <div className="flex-1 rounded-lg border border-border bg-card p-3 min-h-[300px]">
                    <CurveEditor
                      points={editedProfile.curve_points}
                      onChange={(pts) =>
                        setEditedProfile({ ...editedProfile, curve_points: pts })
                      }
                      currentTemp={currentTemp}
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
                      Profile Settings
                    </h3>

                    {/* Source sensor */}
                    <div>
                      <label className="mb-1 block text-xs font-medium text-muted-foreground">
                        Source Sensor
                      </label>
                      <select
                        value={editedProfile.source_sensor}
                        onChange={(e) =>
                          setEditedProfile({
                            ...editedProfile,
                            source_sensor: e.target.value,
                          })
                        }
                        className="w-full rounded-md border border-input bg-background px-2.5 py-1.5 text-xs outline-none focus:ring-1 focus:ring-ring"
                      >
                        {SENSOR_OPTIONS.map((s) => (
                          <option key={s} value={s}>
                            {s}
                          </option>
                        ))}
                      </select>
                    </div>

                    {/* Hysteresis */}
                    <div>
                      <label className="mb-1 block text-xs font-medium text-muted-foreground">
                        Hysteresis (°C)
                      </label>
                      <input
                        type="number"
                        min={0}
                        max={20}
                        value={editedProfile.hysteresis}
                        onChange={(e) =>
                          setEditedProfile({
                            ...editedProfile,
                            hysteresis: Number(e.target.value),
                          })
                        }
                        className="w-full rounded-md border border-input bg-background px-2.5 py-1.5 text-xs outline-none focus:ring-1 focus:ring-ring"
                      />
                      <p className="mt-0.5 text-[10px] text-muted-foreground">
                        Prevents rapid fan speed oscillation
                      </p>
                    </div>

                    {/* Safety threshold */}
                    <div>
                      <label className="mb-1 flex items-center gap-1 text-xs font-medium text-muted-foreground">
                        <AlertTriangle className="h-3 w-3 text-warning" />
                        Safety Threshold (°C)
                      </label>
                      <input
                        type="number"
                        min={50}
                        max={105}
                        value={editedProfile.safety_threshold}
                        onChange={(e) =>
                          setEditedProfile({
                            ...editedProfile,
                            safety_threshold: Number(e.target.value),
                          })
                        }
                        className="w-full rounded-md border border-input bg-background px-2.5 py-1.5 text-xs outline-none focus:ring-1 focus:ring-ring"
                      />
                      <p className="mt-0.5 text-[10px] text-muted-foreground">
                        Fans go 100% above this temperature
                      </p>
                    </div>

                    {/* Actions */}
                    <div className="flex gap-2 pt-2 border-t border-border">
                      <button
                        onClick={handleSave}
                        className="flex flex-1 items-center justify-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
                      >
                        <Save className="h-3 w-3" />
                        Save
                      </button>
                      {!editedProfile.is_preset && (
                        <button
                          onClick={handleDelete}
                          className="flex items-center justify-center gap-1 rounded-md bg-destructive/10 px-3 py-1.5 text-xs font-medium text-destructive hover:bg-destructive/20 transition-colors"
                        >
                          <Trash2 className="h-3 w-3" />
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            ) : loading ? (
              <EmptyState
                icon={Fan}
                title="Loading profiles..."
                description="Fetching fan profiles from the server."
              />
            ) : profiles.length === 0 ? (
              <EmptyState
                icon={Fan}
                title="No fan profiles yet"
                description="Create a profile to define a custom fan curve for this server."
                action={{ label: "Create Profile", onClick: () => setCreating(true) }}
              />
            ) : (
              <EmptyState
                icon={Fan}
                title="Select a Profile"
                description="Choose a profile from the left panel to view and edit its fan curve."
              />
            )}
          </div>

          {/* ---- Bottom bar: Mode selector ---- */}
          <div className="shrink-0 border-t border-border bg-card px-6 py-3">
            <div className="flex items-center gap-4">
              <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Fan Mode
              </span>

              <div className="flex items-center gap-1 rounded-lg bg-muted p-0.5">
                {(
                  [
                    { mode: "auto" as FanMode, label: "BMC Auto" },
                    { mode: "manual" as FanMode, label: "Manual" },
                    { mode: "fanpilot" as FanMode, label: "FanPilot" },
                  ] as const
                ).map(({ mode, label }) => (
                  <button
                    key={mode}
                    disabled={modeLoading}
                    onClick={() => handleModeChange(mode)}
                    className={cn(
                      "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                      status?.mode === mode
                        ? "bg-background text-foreground shadow-sm"
                        : "text-muted-foreground hover:text-foreground"
                    )}
                  >
                    {label}
                  </button>
                ))}
              </div>

              {/* Manual speed slider */}
              {status?.mode === "manual" && (
                <div className="flex items-center gap-3 ml-4">
                  <span className="text-xs text-muted-foreground">Speed:</span>
                  <input
                    type="range"
                    min={0}
                    max={100}
                    value={manualSpeed}
                    onChange={(e) => setManualSpeed(Number(e.target.value))}
                    className="h-1.5 w-40 cursor-pointer appearance-none rounded-full bg-muted [&::-webkit-slider-thumb]:h-3.5 [&::-webkit-slider-thumb]:w-3.5 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-primary [&::-webkit-slider-thumb]:cursor-grab"
                  />
                  <span className="w-8 text-right text-xs font-mono font-medium">
                    {manualSpeed}%
                  </span>
                  <button
                    onClick={handleManualSpeedApply}
                    className="rounded-md bg-primary px-2.5 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
                  >
                    Apply
                  </button>
                </div>
              )}

              {/* Active profile indicator */}
              {status?.mode === "fanpilot" && status.profile && (
                <div className="ml-4 flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Fan className="h-3.5 w-3.5 text-blue-500 animate-spin" style={{ animationDuration: "3s" }} />
                  <span>
                    Active profile: <span className="font-medium text-foreground">{status.profile}</span>
                  </span>
                </div>
              )}
            </div>
          </div>
        </main>
      </div>
    </>
  );
}
