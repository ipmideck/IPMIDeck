/**
 * Widget registry — maps widget_id to React component.
 * This is the static frontend registry (Phase 1: all built-in).
 */

import { MetricWidget } from "@/modules/sensors/widgets/MetricWidget";
import { SensorChart } from "@/modules/sensors/widgets/SensorChart";
import { VoltagesWidget } from "@/modules/sensors/widgets/VoltagesWidget";
import { PowerStatusWidget } from "@/modules/power/widgets/PowerStatusWidget";
import { PowerControlsWidget } from "@/modules/power/widgets/PowerControlsWidget";
import { FanPilotStatusWidget } from "@/modules/fanpilot/widgets/FanPilotStatusWidget";
import type { WidgetLayout } from "@/stores/layout-store";
import { useModuleStore } from "@/stores/module-store";
import { PowerOff } from "lucide-react";

interface WidgetProps {
  serverId: string;
  config?: Record<string, unknown>;
  /** Persist a widget-config change (e.g. MetricWidget sensor selection). Wired by WidgetGrid. */
  onConfigChange?: (config: Record<string, unknown>) => void;
}

type WidgetComponent = React.ComponentType<WidgetProps>;

const WIDGET_MAP: Record<string, (props: WidgetProps & { layout: WidgetLayout }) => React.ReactNode> = {
  "sensors-metric": ({ serverId, config, onConfigChange }) => (
    <MetricWidget
      serverId={serverId}
      sensorName={(config?.sensor as string) || undefined}
      label={(config?.label as string) || undefined}
      onSelectSensor={
        onConfigChange ? (name) => onConfigChange({ sensor: name }) : undefined
      }
    />
  ),
  "sensors-chart": ({ serverId, config, onConfigChange }) => (
    <SensorChart
      serverId={serverId}
      chartType={(config?.type as "temperature" | "fan" | "power") || "temperature"}
      hiddenSensors={(config?.hiddenSensors as string[]) || undefined}
      onHiddenChange={
        onConfigChange ? (hidden) => onConfigChange({ hiddenSensors: hidden }) : undefined
      }
    />
  ),
  "sensors-voltages": ({ serverId, config, onConfigChange }) => (
    <VoltagesWidget
      serverId={serverId}
      hiddenSensors={(config?.hiddenSensors as string[]) || undefined}
      onHiddenChange={
        onConfigChange ? (hidden) => onConfigChange({ hiddenSensors: hidden }) : undefined
      }
    />
  ),
  "power-status": ({ serverId }) => (
    <PowerStatusWidget serverId={serverId} />
  ),
  "power-controls": ({ serverId }) => (
    <PowerControlsWidget serverId={serverId} />
  ),
  "fanpilot-status": ({ serverId }) => (
    <FanPilotStatusWidget serverId={serverId} />
  ),
};

export const SUPPORTED_WIDGET_IDS = new Set(Object.keys(WIDGET_MAP));

export function isWidgetSupported(widgetId: string): boolean {
  return SUPPORTED_WIDGET_IDS.has(widgetId);
}

export function renderWidget(
  layout: WidgetLayout,
  defaultServerId: string,
  onConfigChange?: (config: Record<string, unknown>) => void
): React.ReactNode {
  const renderer = WIDGET_MAP[layout.widget_id];
  if (!renderer) {
    return <div className="flex h-full items-center justify-center text-xs text-muted-foreground">Unknown widget: {layout.widget_id}</div>;
  }
  const serverId = layout.server_id || defaultServerId;
  return renderer({ serverId, config: layout.config, layout, onConfigChange });
}

/**
 * Hook-component that gates rendering on the owning module's enabled state.
 * Subscribes to the module-enabled store via a real hook so a toggle re-renders
 * reactively (no page reload, no convention-only subscription hack — MEDIUM #8).
 * When the module is disabled, shows a placeholder inside the existing card
 * chrome instead of stale/live data; otherwise delegates to renderWidget.
 */
export function WidgetRenderer({
  layout,
  defaultServerId,
  onConfigChange,
}: {
  layout: WidgetLayout;
  defaultServerId: string;
  onConfigChange?: (config: Record<string, unknown>) => void;
}): React.ReactNode {
  // real hook subscription -> re-renders when the module's enabled state changes
  const enabled = useModuleStore((s) => s.isEnabled(layout.module_id));
  if (!enabled) {
    return (
      <div className="flex h-full flex-col items-center justify-center text-center text-sm text-muted-foreground">
        <PowerOff className="mb-2 h-5 w-5" />
        <p>Module disabled</p>
        <p className="mt-1 text-xs">
          Enable {layout.module_id} in Settings → Modules to restore this widget.
        </p>
      </div>
    );
  }
  return renderWidget(layout, defaultServerId, onConfigChange);
}

export function getWidgetTitle(layout: WidgetLayout): string {
  const titles: Record<string, string> = {
    "sensors-metric": (layout.config?.sensor as string) || "Sensor",
    "sensors-chart": `${(layout.config?.type as string) || "Temperature"} Chart`,
    "sensors-voltages": "Voltages",
    "power-status": "Power",
    "power-controls": "Power Control",
    "fanpilot-status": "FanPilot",
    "fanpilot-curve": "Fan Curve",
  };
  return titles[layout.widget_id] || layout.widget_id;
}
