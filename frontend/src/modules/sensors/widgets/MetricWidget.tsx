import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useSensorStore } from "@/stores/sensor-store";
import { cn } from "@/lib/utils";
import { naturalCompare } from "@/modules/sensors/sensorUtils";
import { ChevronDown } from "lucide-react";

// Stable empty-array reference for the sparkline selector. Returning a fresh `[]`
// on every render trips Zustand v5's Object.is equality check, triggering an
// infinite re-render loop (React #185). A single module-level constant keeps the
// reference stable across renders.
const EMPTY: number[] = [];

// Preference order for the smart default when the stored sensor doesn't exist on this server.
const TYPE_PRIORITY = ["temperature", "power", "fan", "voltage", "current"];

interface MetricWidgetProps {
  serverId: string;
  /** Stored sensor name from widget config (may not exist on a non-demo BMC). */
  sensorName?: string;
  label?: string;
  /** Persist a new sensor selection into the widget config (wired by WidgetGrid). */
  onSelectSensor?: (name: string) => void;
}

function Sparkline({ data, color }: { data: number[]; color: string }) {
  // Need at least 2 distinct points for a meaningful line; otherwise render nothing
  // (a single value would draw a stray dot/mark near the badge).
  if (data.length < 2) return null;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const w = 80;
  const h = 24;
  const points = data
    .map((v, i) => {
      const x = (i / (data.length - 1)) * w;
      const y = h - ((v - min) / range) * h;
      return `${x},${y}`;
    })
    .join(" ");

  return (
    <svg width={w} height={h} className="mt-1 opacity-60" aria-hidden="true">
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/**
 * Sensor picker rendered in a PORTAL to document.body so it escapes the widget card's
 * `overflow-hidden` clipping and the react-grid-layout stacking context. Positioned `fixed`
 * and anchored to the trigger button via getBoundingClientRect, so it floats ABOVE neighbouring
 * widgets regardless of grid order. Closes on outside-click, Escape, and item selection; the
 * options list is keyboard-navigable (Arrow keys / Enter). Drag-safe: onMouseDown stops
 * propagation so the grid drag handler doesn't hijack clicks (same pattern as the sidebar
 * server picker and the WidgetGrid server tag).
 */
function SensorPickerMenu({
  anchorRef,
  options,
  active,
  readings,
  onSelect,
  onClose,
}: {
  anchorRef: React.RefObject<HTMLButtonElement | null>;
  options: string[];
  active: string | undefined;
  readings: Record<string, { value: number | null; unit: string } | undefined> | undefined;
  onSelect: (name: string) => void;
  onClose: () => void;
}) {
  const menuRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number; width: number } | null>(null);
  const [highlight, setHighlight] = useState(() =>
    active ? Math.max(0, options.indexOf(active)) : 0
  );

  // Position the menu under the trigger. Recomputed on mount and on scroll/resize so it
  // stays anchored if the page moves while open.
  const reposition = useCallback(() => {
    const el = anchorRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const width = Math.max(rect.width, 176); // min-w-44
    // Right-align the menu to the trigger; clamp into the viewport.
    let left = rect.right - width;
    if (left < 8) left = 8;
    if (left + width > window.innerWidth - 8) left = window.innerWidth - 8 - width;
    setPos({ top: rect.bottom + 4, left, width });
  }, [anchorRef]);

  useLayoutEffect(() => {
    reposition();
  }, [reposition]);

  useEffect(() => {
    function onScrollOrResize() {
      reposition();
    }
    // capture:true catches scrolls on inner scroll containers (the grid).
    window.addEventListener("scroll", onScrollOrResize, true);
    window.addEventListener("resize", onScrollOrResize);
    return () => {
      window.removeEventListener("scroll", onScrollOrResize, true);
      window.removeEventListener("resize", onScrollOrResize);
    };
  }, [reposition]);

  // Close on outside-click (pointerdown so it fires before the grid's drag handlers).
  useEffect(() => {
    function onPointerDown(e: PointerEvent) {
      const t = e.target as Node;
      if (menuRef.current?.contains(t)) return;
      if (anchorRef.current?.contains(t)) return; // toggle handled by the button itself
      onClose();
    }
    document.addEventListener("pointerdown", onPointerDown, true);
    return () => document.removeEventListener("pointerdown", onPointerDown, true);
  }, [anchorRef, onClose]);

  // Keyboard: Escape closes, Arrow keys move highlight, Enter selects.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      } else if (e.key === "ArrowDown") {
        e.preventDefault();
        setHighlight((h) => Math.min(options.length - 1, h + 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setHighlight((h) => Math.max(0, h - 1));
      } else if (e.key === "Enter") {
        e.preventDefault();
        const name = options[highlight];
        if (name) onSelect(name);
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [options, highlight, onSelect, onClose]);

  if (!pos) return null;

  return createPortal(
    <div
      ref={menuRef}
      role="listbox"
      // z above the grid (grid items create stacking contexts; body-level portal + high z wins).
      style={{ position: "fixed", top: pos.top, left: pos.left, width: pos.width, zIndex: 9999 }}
      className="rounded-lg border border-border bg-popover text-popover-foreground shadow-lg"
      onMouseDown={(e) => e.stopPropagation()}
    >
      <div className="max-h-60 overflow-y-auto py-1">
        {options.map((name, i) => {
          const r = readings?.[name];
          const isActive = name === active;
          const isHi = i === highlight;
          return (
            <button
              key={name}
              type="button"
              role="option"
              aria-selected={isActive}
              onMouseDown={(e) => e.stopPropagation()}
              onMouseEnter={() => setHighlight(i)}
              onClick={() => onSelect(name)}
              className={cn(
                "flex w-full items-center justify-between gap-3 px-2 py-1.5 text-left text-[12px]",
                isHi ? "bg-muted" : "hover:bg-muted",
                isActive && "font-medium"
              )}
            >
              <span className="truncate">{name}</span>
              <span className="shrink-0 font-mono text-[10px] text-muted-foreground">
                {r?.value != null ? `${r.value}${r.unit}` : "—"}
              </span>
            </button>
          );
        })}
      </div>
    </div>,
    document.body
  );
}

export function MetricWidget({ serverId, sensorName, label, onSelectSensor }: MetricWidgetProps) {
  // Subscribe to the readings map for this server (stable ref per server — no React #185).
  const readings = useSensorStore((s) => s.readings[serverId]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);

  // All numeric sensors available on this server, sorted by (type, natural name).
  const available = useMemo(() => {
    if (!readings) return [] as string[];
    return Object.entries(readings)
      .filter(([, r]) => r?.value != null) // numeric sensors only
      .sort(([an, a], [bn, b]) => {
        const ta = TYPE_PRIORITY.indexOf(a?.type ?? "");
        const tb = TYPE_PRIORITY.indexOf(b?.type ?? "");
        const ra = ta === -1 ? TYPE_PRIORITY.length : ta;
        const rb = tb === -1 ? TYPE_PRIORITY.length : tb;
        if (ra !== rb) return ra - rb;
        return naturalCompare(an, bn);
      })
      .map(([name]) => name);
  }, [readings]);

  // Smart default: keep the stored sensor if it still resolves to a reading; otherwise
  // auto-pick the highest-priority available sensor so a fresh dashboard on real hardware
  // shows a real value instead of "unknown".
  const storedExists = sensorName != null && readings?.[sensorName] != null;
  const effectiveName = storedExists ? (sensorName as string) : available[0];

  // Persist the auto-picked default ONCE, so the choice survives reloads and the config
  // stops referencing a non-existent demo name. Guarded so we never loop or re-persist.
  const persistedRef = useRef(false);
  useEffect(() => {
    if (!onSelectSensor) return;
    if (storedExists) {
      persistedRef.current = false; // stored name is valid again; allow future auto-fix
      return;
    }
    if (persistedRef.current) return;
    if (effectiveName) {
      persistedRef.current = true;
      onSelectSensor(effectiveName);
    }
  }, [storedExists, effectiveName, onSelectSensor]);

  const handleSelect = useCallback(
    (name: string) => {
      onSelectSensor?.(name);
      setPickerOpen(false);
    },
    [onSelectSensor]
  );

  const reading = effectiveName ? readings?.[effectiveName] : undefined;
  const sparkline = useSensorStore((s) =>
    effectiveName ? (s.sparklines[serverId]?.[effectiveName] ?? EMPTY) : EMPTY
  );

  if (!serverId) {
    return <div className="flex h-full items-center justify-center text-muted-foreground">—</div>;
  }

  try {
    const value = reading?.value;
    const unit = reading?.unit || "";
    const status = reading?.status || "unknown";
    const displayLabel = label || effectiveName || "Sensor";

    const badgeBg =
      status === "ok" ? "bg-emerald-500/10 text-emerald-500" :
      status === "warning" ? "bg-yellow-500/10 text-yellow-500" :
      status === "critical" ? "bg-red-500/10 text-red-500" : "bg-muted text-muted-foreground";

    const chartColor =
      unit === "C" ? "#2563eb" :
      unit === "RPM" ? "#f59e0b" :
      unit === "W" ? "#8b5cf6" :
      unit === "V" ? "#10b981" :
      unit === "A" ? "#06b6d4" : "#a1a1aa";

    return (
      <div className="relative flex h-full flex-col justify-center">
        {/* Sensor picker — lets the user choose which sensor this card shows, from the
            server's actual sensor list. The menu is portalled to <body> so it isn't clipped
            by the card's overflow-hidden or the grid stacking context. */}
        {onSelectSensor && available.length > 0 && (
          <div className="absolute right-0 top-0 z-20">
            <button
              ref={triggerRef}
              type="button"
              aria-label="Select sensor"
              aria-haspopup="listbox"
              aria-expanded={pickerOpen}
              onMouseDown={(e) => e.stopPropagation()}
              onClick={() => setPickerOpen((p) => !p)}
              className="flex max-w-[140px] items-center gap-1 rounded px-1 py-0.5 text-[10px] text-muted-foreground hover:bg-muted"
            >
              <span className="truncate">{effectiveName ?? "Select"}</span>
              <ChevronDown className="h-3 w-3 shrink-0" />
            </button>
            {pickerOpen && (
              <SensorPickerMenu
                anchorRef={triggerRef}
                options={available}
                active={effectiveName}
                readings={readings}
                onSelect={handleSelect}
                onClose={() => setPickerOpen(false)}
              />
            )}
          </div>
        )}

        <div className="font-mono text-2xl font-semibold leading-none tracking-tight">
          {value !== null && value !== undefined ? (
            <>
              {typeof value === "number" ? (Number.isInteger(value) ? value : value.toFixed(1)) : value}
              <span className="ml-0.5 text-sm font-normal text-muted-foreground">{unit}</span>
            </>
          ) : (
            <span className="text-muted-foreground">—</span>
          )}
        </div>
        <div className="mt-0.5 truncate text-[10px] text-muted-foreground">{displayLabel}</div>
        <div className="mt-1 flex items-center gap-2">
          <span className={cn("inline-flex rounded-full px-1.5 py-0.5 text-[10px] font-semibold", badgeBg)}>
            {status === "ok" ? "Normal" : status}
          </span>
        </div>
        <Sparkline data={Array.isArray(sparkline) ? sparkline : []} color={chartColor} />
      </div>
    );
  } catch {
    return <div className="flex h-full items-center justify-center text-muted-foreground">—</div>;
  }
}
