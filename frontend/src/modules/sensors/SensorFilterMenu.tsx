import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Multi-select "which sensors to show" menu, portalled to <body> so it escapes the widget
 * card's overflow-hidden and the react-grid-layout stacking context. Fixed positioning anchored
 * to the trigger; closes on outside-click / Escape. Toggling a row persists immediately and the
 * menu stays open so the user can flip several at once. Drag-safe: onMouseDown stops propagation
 * so the grid drag handler doesn't hijack clicks (same pattern as the MetricWidget sensor picker).
 *
 * Shared by SensorChart (series visibility) and VoltagesWidget (voltage/current visibility).
 */
export function SensorFilterMenu({
  anchorRef,
  allSensors,
  hiddenSet,
  readings,
  onToggle,
  onAll,
  onClose,
}: {
  anchorRef: React.RefObject<HTMLButtonElement | null>;
  allSensors: string[];
  hiddenSet: Set<string>;
  readings: Record<string, { value: number | null; unit: string } | undefined> | undefined;
  onToggle: (name: string) => void;
  onAll: (show: boolean) => void;
  onClose: () => void;
}) {
  const menuRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number; width: number } | null>(null);

  const reposition = useCallback(() => {
    const el = anchorRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const width = Math.max(rect.width, 200);
    let left = rect.right - width;
    if (left < 8) left = 8;
    if (left + width > window.innerWidth - 8) left = window.innerWidth - 8 - width;
    setPos({ top: rect.bottom + 4, left, width });
  }, [anchorRef]);

  useLayoutEffect(() => {
    reposition();
  }, [reposition]);

  useEffect(() => {
    const onMove = () => reposition();
    window.addEventListener("scroll", onMove, true);
    window.addEventListener("resize", onMove);
    return () => {
      window.removeEventListener("scroll", onMove, true);
      window.removeEventListener("resize", onMove);
    };
  }, [reposition]);

  useEffect(() => {
    function onPointerDown(e: PointerEvent) {
      const t = e.target as Node;
      if (menuRef.current?.contains(t)) return;
      if (anchorRef.current?.contains(t)) return;
      onClose();
    }
    document.addEventListener("pointerdown", onPointerDown, true);
    return () => document.removeEventListener("pointerdown", onPointerDown, true);
  }, [anchorRef, onClose]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (!pos) return null;

  const allHidden = allSensors.every((s) => hiddenSet.has(s));

  return createPortal(
    <div
      ref={menuRef}
      role="group"
      aria-label="Choose which sensors to show"
      style={{ position: "fixed", top: pos.top, left: pos.left, width: pos.width, zIndex: 9999 }}
      className="rounded-lg border border-border bg-popover text-popover-foreground shadow-lg"
      onMouseDown={(e) => e.stopPropagation()}
    >
      <div className="flex items-center justify-between border-b border-border px-2 py-1.5">
        <span className="text-[11px] font-medium text-muted-foreground">Show sensors</span>
        <button
          type="button"
          onMouseDown={(e) => e.stopPropagation()}
          onClick={() => onAll(allHidden)}
          className="rounded px-1.5 py-0.5 text-[10px] text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          {allHidden ? "Show all" : "Hide all"}
        </button>
      </div>
      <div className="max-h-60 overflow-y-auto py-1">
        {allSensors.map((name) => {
          const visible = !hiddenSet.has(name);
          const r = readings?.[name];
          return (
            <button
              key={name}
              type="button"
              role="checkbox"
              aria-checked={visible}
              onMouseDown={(e) => e.stopPropagation()}
              onClick={() => onToggle(name)}
              className="flex w-full items-center gap-2 px-2 py-1.5 text-left text-[12px] hover:bg-muted"
            >
              <span
                className={cn(
                  "flex h-4 w-4 shrink-0 items-center justify-center rounded border",
                  visible ? "border-primary bg-primary text-primary-foreground" : "border-muted-foreground/40"
                )}
              >
                {visible && <Check className="h-3 w-3" />}
              </span>
              <span className="flex-1 truncate">{name}</span>
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
