/**
 * Widget registry — maps widget_id to React component.
 * This is the static frontend registry (Phase 1: all built-in).
 *
 * Each renderer returns { body, headerActions } so the widget card chrome
 * (view toggles, reset buttons, sensor filters) can live in the card HEADER
 * via WidgetGrid's headerActions slot — keeping the widget body clean and
 * the action buttons out of the way of drag/resize controls.
 */

import { MetricWidget } from "@/modules/sensors/widgets/MetricWidget";
import { SensorChart, SensorChartHeaderActions } from "@/modules/sensors/widgets/SensorChart";
import { VoltagesWidget } from "@/modules/sensors/widgets/VoltagesWidget";
import { PowerStatusWidget } from "@/modules/power/widgets/PowerStatusWidget";
import { PowerControlsWidget, PowerControlsHeaderActions } from "@/modules/power/widgets/PowerControlsWidget";
import { PowerStatsWidget } from "@/modules/power/widgets/PowerStatsWidget";
import { EnergyCostWidget } from "@/modules/power/widgets/EnergyCostWidget";
import { FanPilotStatusWidget } from "@/modules/fanpilot/widgets/FanPilotStatusWidget";
import type { WidgetLayout } from "@/stores/layout-store";
import { useModuleStore } from "@/stores/module-store";
import i18n from "@/i18n";
import type { TFunction } from "i18next";
import type { LucideIcon } from "lucide-react";
import { PowerOff, LayoutGrid as LayoutGridIcon, LineChart as LineChartIcon, Thermometer, Fan, Zap } from "lucide-react";

interface WidgetProps {
  serverId: string;
  config?: Record<string, unknown>;
  /** Persist a widget-config change (e.g. MetricWidget sensor selection). Wired by WidgetGrid. */
  onConfigChange?: (config: Record<string, unknown>) => void;
}

/** Result of rendering a widget: body fills the card content area; optional
 *  headerActions render in the card title bar between the title and the
 *  server-tag/X buttons. */
export interface WidgetRenderResult {
  body: React.ReactNode;
  headerActions?: React.ReactNode;
}

const WIDGET_MAP: Record<
  string,
  (props: WidgetProps & { layout: WidgetLayout }) => WidgetRenderResult
> = {
  "sensors-metric": ({ serverId, config, onConfigChange }) => ({
    body: (
      <MetricWidget
        serverId={serverId}
        sensorName={(config?.sensor as string) || undefined}
        label={(config?.label as string) || undefined}
        onSelectSensor={
          onConfigChange ? (name) => onConfigChange({ sensor: name }) : undefined
        }
      />
    ),
  }),
  "sensors-chart": ({ serverId, config, onConfigChange }) => {
    const chartType = (config?.type as "temperature" | "fan" | "power") || "temperature";
    const hiddenSensors = (config?.hiddenSensors as string[]) || undefined;
    const view = (config?.view as "chart" | "cards") || "chart";
    const onHiddenChange = onConfigChange
      ? (hidden: string[]) => onConfigChange({ hiddenSensors: hidden })
      : undefined;
    const onViewChange = onConfigChange
      ? (v: "chart" | "cards") => onConfigChange({ view: v })
      : undefined;
    return {
      body: (
        <SensorChart
          serverId={serverId}
          chartType={chartType}
          hiddenSensors={hiddenSensors}
          onHiddenChange={onHiddenChange}
          view={view}
          onViewChange={onViewChange}
        />
      ),
      headerActions: (
        <SensorChartHeaderActions
          serverId={serverId}
          chartType={chartType}
          hiddenSensors={hiddenSensors}
          onHiddenChange={onHiddenChange}
          view={view}
          onViewChange={onViewChange}
        />
      ),
    };
  },
  "sensors-voltages": ({ serverId, config, onConfigChange }) => ({
    body: (
      <VoltagesWidget
        serverId={serverId}
        hiddenSensors={(config?.hiddenSensors as string[]) || undefined}
        onHiddenChange={
          onConfigChange ? (hidden) => onConfigChange({ hiddenSensors: hidden }) : undefined
        }
      />
    ),
  }),
  "power-status": ({ serverId }) => ({
    body: <PowerStatusWidget serverId={serverId} />,
  }),
  "power-controls": ({ serverId, config, onConfigChange }) => {
    const view = (config?.view as "compact" | "chart") || "compact";
    const onViewChange = onConfigChange
      ? (v: "compact" | "chart") => onConfigChange({ view: v })
      : undefined;
    return {
      body: (
        <PowerControlsWidget
          serverId={serverId}
          view={view}
          onViewChange={onViewChange}
        />
      ),
      headerActions: (
        <PowerControlsHeaderActions
          serverId={serverId}
          view={view}
          onViewChange={onViewChange}
        />
      ),
    };
  },
  "power-stats": ({ serverId }) => ({
    body: <PowerStatsWidget serverId={serverId} />,
  }),
  // 04-W2-06: Energy Cost — derives w/h from the saved layout so the widget can
  // pick its 2x2 (cost-only) vs 3x2 (chart) layout (Decision N kWh chart inside).
  "power-energy-cost": ({ serverId, layout }) => ({
    body: <EnergyCostWidget serverId={serverId} w={layout.w} h={layout.h} />,
  }),
  "fanpilot-status": ({ serverId }) => ({
    body: <FanPilotStatusWidget serverId={serverId} />,
  }),
};

export const SUPPORTED_WIDGET_IDS = new Set(Object.keys(WIDGET_MAP));

export function isWidgetSupported(widgetId: string): boolean {
  return SUPPORTED_WIDGET_IDS.has(widgetId);
}

export function renderWidget(
  layout: WidgetLayout,
  defaultServerId: string,
  onConfigChange?: (config: Record<string, unknown>) => void
): WidgetRenderResult {
  const renderer = WIDGET_MAP[layout.widget_id];
  if (!renderer) {
    return {
      body: (
        <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
          {i18n.t("widget.unknownWidget", { id: layout.widget_id })}
        </div>
      ),
    };
  }
  const serverId = layout.server_id || defaultServerId;
  return renderer({ serverId, config: layout.config, layout, onConfigChange });
}

/** Placeholder rendered in the widget body when the owning module is disabled. */
function DisabledPlaceholder({ moduleId }: { moduleId: string }) {
  // Module-store gate is reactive; read the active language so the placeholder
  // re-translates on language change without a hook (it's rendered inside the grid).
  return (
    <div className="flex h-full flex-col items-center justify-center text-center text-sm text-muted-foreground">
      <PowerOff className="mb-2 h-5 w-5" />
      <p>{i18n.t("widget.moduleDisabled")}</p>
      <p className="mt-1 text-xs">
        {i18n.t("widget.moduleDisabledHint", { module: moduleId })}
      </p>
    </div>
  );
}

/**
 * Render hook — gates on the owning module's enabled state via a real
 * useModuleStore subscription so a toggle re-renders reactively. Returns the
 * same { body, headerActions } shape as renderWidget; when the module is
 * disabled, headerActions is omitted (no chrome on the placeholder).
 *
 * MUST be called at the top level of a component (React hook rules) — see
 * WidgetGrid's WidgetCard subcomponent.
 */
export function useWidgetRender(
  layout: WidgetLayout,
  defaultServerId: string,
  onConfigChange?: (config: Record<string, unknown>) => void
): WidgetRenderResult {
  const enabled = useModuleStore((s) => s.isEnabled(layout.module_id));
  if (!enabled) {
    return { body: <DisabledPlaceholder moduleId={layout.module_id} /> };
  }
  return renderWidget(layout, defaultServerId, onConfigChange);
}

export function getWidgetTitle(layout: WidgetLayout, t: TFunction): string {
  // sensors-metric title is the (BMC-sourced) sensor name when set, otherwise a
  // translated generic. The chart "type" is an app-defined axis, translated below.
  const titles: Record<string, string> = {
    "sensors-metric": (layout.config?.sensor as string) || t("widget.titleSensor"),
    "sensors-chart": t("widget.titleChart", {
      type: (layout.config?.type as string) || t("widget.titleChartDefault"),
    }),
    "sensors-voltages": t("widget.titleVoltages"),
    "power-status": t("widget.titlePower"),
    "power-controls": t("widget.titlePowerControl"),
    "power-stats": t("widget.titlePowerStats"),
    "power-energy-cost": t("widget.titleEnergyCost"),
    "fanpilot-status": t("widget.titleFanpilot"),
    "fanpilot-curve": t("widget.titleFanCurve"),
  };
  return titles[layout.widget_id] || layout.widget_id;
}

/* ------------------------------------------------------------------ */
/*  Multi-view registry — drives the WidgetCatalog inline view picker  */
/* ------------------------------------------------------------------ */

export interface ViewOption {
  /** Used as React key. Also used as a single-field config patch (`{view: value}`)
   *  when `config` is omitted — preserves backward compatibility with widgets that
   *  only differ on a single `view` axis (e.g. power-controls compact vs chart). */
  value: string;
  /** i18n keys for the picker label/description — resolved via t() at the WidgetCatalog callsite. */
  labelKey: string;
  descKey: string;
  icon?: LucideIcon;
  /** Optional explicit config patch merged into the new widget's config. When set,
   *  replaces the implicit `{view: value}` mapping — used by widgets that need to
   *  pick more than one config field at add time (e.g. sensors-chart needs both
   *  `type` and `view`). */
  config?: Record<string, unknown>;
}

/**
 * Widgets that support more than one view. The catalog uses this to show an
 * inline view-picker CTA when the user clicks the widget to add it. Widgets
 * NOT listed here add immediately with no extra step.
 */
export const WIDGET_VIEWS: Record<string, ViewOption[]> = {
  "power-controls": [
    {
      value: "compact",
      labelKey: "widget.viewCompact",
      descKey: "widget.viewCompactDesc",
      icon: LayoutGridIcon,
    },
    {
      value: "chart",
      labelKey: "widget.viewLiveChart",
      descKey: "widget.viewLiveChartDesc",
      icon: LineChartIcon,
    },
  ],
  // Sensor Chart has TWO axes:
  //   - type: temperature | fan | power (what the chart shows)
  //   - view: chart | cards   (how it's rendered — cards are fan-only animation)
  // We expose the meaningful combinations as four picker options so the user
  // can add a fan chart directly from the catalog (previously the catalog only
  // wrote type=temperature, leaving fan/power charts un-addable from the UI).
  "sensors-chart": [
    {
      value: "temperature",
      labelKey: "widget.viewTemperature",
      descKey: "widget.viewTemperatureDesc",
      icon: Thermometer,
      config: { type: "temperature", view: "chart" },
    },
    {
      value: "fan-chart",
      labelKey: "widget.viewFanChart",
      descKey: "widget.viewFanChartDesc",
      icon: LineChartIcon,
      config: { type: "fan", view: "chart" },
    },
    {
      value: "fan-cards",
      labelKey: "widget.viewFanCards",
      descKey: "widget.viewFanCardsDesc",
      icon: Fan,
      config: { type: "fan", view: "cards" },
    },
    {
      value: "power",
      labelKey: "widget.viewPower",
      descKey: "widget.viewPowerDesc",
      icon: Zap,
      config: { type: "power", view: "chart" },
    },
  ],
};

/** First view = default — what gets written if the user picks "Compact"/etc. */
export function getDefaultView(widgetId: string): string | undefined {
  return WIDGET_VIEWS[widgetId]?.[0]?.value;
}
