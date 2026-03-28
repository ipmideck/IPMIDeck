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

interface WidgetProps {
  serverId: string;
  config?: Record<string, unknown>;
}

type WidgetComponent = React.ComponentType<WidgetProps>;

const WIDGET_MAP: Record<string, (props: WidgetProps & { layout: WidgetLayout }) => React.ReactNode> = {
  "sensors-metric": ({ serverId, config }) => (
    <MetricWidget
      serverId={serverId}
      sensorName={(config?.sensor as string) || "CPU Temp"}
      label={(config?.label as string) || undefined}
    />
  ),
  "sensors-chart": ({ serverId, config }) => (
    <SensorChart
      serverId={serverId}
      chartType={(config?.type as "temperature" | "fan" | "power") || "temperature"}
    />
  ),
  "sensors-voltages": ({ serverId }) => (
    <VoltagesWidget serverId={serverId} />
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

export function renderWidget(layout: WidgetLayout, defaultServerId: string): React.ReactNode {
  const renderer = WIDGET_MAP[layout.widget_id];
  if (!renderer) {
    return <div className="flex h-full items-center justify-center text-xs text-muted-foreground">Unknown widget: {layout.widget_id}</div>;
  }
  const serverId = layout.server_id || defaultServerId;
  return renderer({ serverId, config: layout.config, layout });
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
