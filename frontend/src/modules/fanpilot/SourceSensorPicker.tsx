import { useId } from "react";
import { useTranslation } from "react-i18next";
import { Thermometer } from "lucide-react";
import type { SensorReading } from "@/stores/sensor-store";
import { cn } from "@/lib/utils";
import { MAX_SOURCE_SENSORS, toggleSensor, type SensorMode } from "@/modules/fanpilot/sourceSensors";

interface SourceSensorPickerProps {
  /** Temperature sensors present on the selected server. */
  available: string[];
  readings: Record<string, SensorReading>;
  /** Backend reachable: live values are shown only then, like the curve indicator. */
  online: boolean;
  selected: string[];
  mode: SensorMode;
  /** The value the curve follows (hottest or average), or null when it cannot be computed. */
  combinedTemp: number | null;
  onChange: (next: { sensors: string[]; mode: SensorMode }) => void;
}

const MODES: { mode: SensorMode; labelKey: string }[] = [
  { mode: "max", labelKey: "fanpilot.sensorModeMax" },
  { mode: "avg", labelKey: "fanpilot.sensorModeAvg" },
];

/**
 * Pick the temperature sensors a fan profile follows (1 to 8) and, with two or more, whether
 * the curve follows the hottest or their average. Sensor names are shown exactly as the BMC
 * reports them. A stored sensor this server does not have stays listed and ticked so the
 * operator can see it and untick it; nothing is removed behind their back.
 */
export function SourceSensorPicker({
  available,
  readings,
  online,
  selected,
  mode,
  combinedTemp,
  onChange,
}: SourceSensorPickerProps) {
  const { t } = useTranslation();
  const baseId = useId();
  const absent = selected.filter((name) => !available.includes(name));
  const rows = [...available, ...absent];
  const multi = selected.length >= 2;
  const full = selected.length >= MAX_SOURCE_SENSORS;
  const modeLabel = t(MODES.find((m) => m.mode === mode)?.labelKey ?? "fanpilot.sensorModeMax");

  return (
    <div>
      <fieldset aria-labelledby={`${baseId}-label`}>
        <div className="mb-1 flex items-center justify-between gap-2">
          <span id={`${baseId}-label`} className="text-xs font-medium text-muted-foreground">
            {t("fanpilot.sourceSensors")}
          </span>
          {/* Hidden when offline so it never contradicts the curve editor, which drops its
              live indicator too. */}
          {online && combinedTemp !== null && (
            <span className="inline-flex shrink-0 items-center gap-1 font-mono text-[11px] font-semibold text-foreground">
              {/* Live value driving the curve — cyan cooling cue plus a non-color
                  thermometer companion. */}
              <Thermometer className="h-3 w-3 text-[var(--color-cyan-ink)]" aria-hidden />
              {multi && (
                <span className="font-sans font-medium text-muted-foreground">{modeLabel}</span>
              )}
              {combinedTemp}°C
            </span>
          )}
        </div>

        {rows.length === 0 ? (
          <p className="rounded-md border border-input bg-background px-2.5 py-1.5 text-xs text-muted-foreground">
            {t("fanpilot.noTempSensors")}
          </p>
        ) : (
          <ul className="max-h-44 overflow-y-auto rounded-md border border-input bg-background py-1">
            {rows.map((name, i) => {
              const checked = selected.includes(name);
              const onServer = available.includes(name);
              const disabled = checked ? selected.length <= 1 : full;
              const value = readings[name]?.value;
              const id = `${baseId}-s${i}`;
              return (
                <li
                  key={name}
                  className={cn(
                    "flex items-center gap-2 px-2.5 py-1 text-xs",
                    disabled && "opacity-50"
                  )}
                >
                  <input
                    id={id}
                    type="checkbox"
                    checked={checked}
                    disabled={disabled}
                    onChange={() => onChange({ sensors: toggleSensor(selected, name), mode })}
                    className="h-3.5 w-3.5 shrink-0 accent-[var(--color-cyan-ink)] outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed"
                  />
                  <label
                    htmlFor={id}
                    className={cn(
                      "min-w-0 flex-1 truncate",
                      disabled ? "cursor-not-allowed" : "cursor-pointer",
                      !onServer && "text-muted-foreground"
                    )}
                    title={name}
                  >
                    {onServer ? name : t("fanpilot.notOnThisServer", { name })}
                  </label>
                  {online && onServer && value != null && (
                    <span className="shrink-0 font-mono text-[11px] tabular-nums text-muted-foreground">
                      {value}°C
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </fieldset>

      {multi && (
        <fieldset className="mt-2">
          <legend className="mb-1 text-[11px] font-medium text-muted-foreground">
            {t("fanpilot.sensorMode")}
          </legend>
          <div className="grid grid-cols-2 gap-0.5 rounded-md border border-input bg-background p-0.5">
            {MODES.map((m) => (
              <label
                key={m.mode}
                className={cn(
                  "cursor-pointer rounded px-2 py-1 text-center text-xs text-muted-foreground transition-colors",
                  "has-[:checked]:bg-muted has-[:checked]:font-medium has-[:checked]:text-foreground",
                  "has-[:focus-visible]:ring-1 has-[:focus-visible]:ring-ring hover:text-foreground"
                )}
              >
                <input
                  type="radio"
                  name={`${baseId}-mode`}
                  value={m.mode}
                  checked={mode === m.mode}
                  onChange={() => onChange({ sensors: selected, mode: m.mode })}
                  className="sr-only"
                />
                {t(m.labelKey)}
              </label>
            ))}
          </div>
        </fieldset>
      )}

      <p className="mt-0.5 text-[10px] text-muted-foreground">
        {t("fanpilot.sourceSensorsHint", { max: MAX_SOURCE_SENSORS })}
      </p>
    </div>
  );
}
