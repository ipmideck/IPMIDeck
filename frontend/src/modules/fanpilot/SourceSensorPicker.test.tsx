import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@/i18n";
import { SourceSensorPicker } from "@/modules/fanpilot/SourceSensorPicker";
import type { SensorMode } from "@/modules/fanpilot/sourceSensors";
import type { SensorReading } from "@/stores/sensor-store";

/**
 * The sensor picker in FanPilot profile settings: which boxes are ticked and usable, when the
 * Hottest / Average choice appears, and what it reports back.
 */

const reading = (value: number): SensorReading => ({
  value,
  unit: "degrees C",
  status: "ok",
  type: "temperature",
});

const READINGS = { "CPU 1": reading(40), "CPU 2": reading(61), "Inlet Temp": reading(22) };
const AVAILABLE = ["CPU 1", "CPU 2", "Inlet Temp"];

function renderPicker(
  props: Partial<{
    available: string[];
    selected: string[];
    mode: SensorMode;
    combinedTemp: number | null;
  }> = {}
) {
  const onChange = vi.fn();
  render(
    <SourceSensorPicker
      available={props.available ?? AVAILABLE}
      readings={READINGS}
      online
      selected={props.selected ?? ["CPU 1"]}
      mode={props.mode ?? "max"}
      combinedTemp={props.combinedTemp ?? 40}
      onChange={onChange}
    />
  );
  return onChange;
}

const avgOption = () => screen.queryByRole("radio", { name: /fanpilot\.sensorModeAvg|average/i });

afterEach(() => {
  cleanup();
});

describe("SourceSensorPicker", () => {
  it("offers one checkbox per sensor, labelled with the sensor's own name", () => {
    renderPicker();
    expect(screen.getAllByRole("checkbox")).toHaveLength(3);
    expect(screen.getByRole("checkbox", { name: "CPU 1" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "CPU 2" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Inlet Temp" })).not.toBeChecked();
  });

  it("keeps a stored sensor this server lacks ticked and marked", () => {
    renderPicker({ selected: ["CPU 1", "GPU 0"] });
    const absent = screen.getByRole("checkbox", { name: /GPU 0/ });
    expect(absent).toBeChecked();
    expect(screen.getByText(/GPU 0/).textContent).toMatch(/notOnThisServer|not on this server/i);
  });

  it("with one sensor ticked, that box cannot be unticked and there is no mode choice", () => {
    renderPicker({ selected: ["CPU 1"] });
    expect(screen.getByRole("checkbox", { name: "CPU 1" })).toBeDisabled();
    expect(avgOption()).toBeNull();
  });

  it("with two sensors ticked, choosing Average reports the avg mode", async () => {
    const onChange = renderPicker({ selected: ["CPU 1", "CPU 2"] });
    const user = userEvent.setup();
    const avg = avgOption();
    expect(avg).not.toBeNull();
    await user.click(avg!);
    expect(onChange).toHaveBeenCalledWith({ sensors: ["CPU 1", "CPU 2"], mode: "avg" });
  });

  it("ticking a box appends that sensor", async () => {
    const onChange = renderPicker({ selected: ["CPU 1"] });
    const user = userEvent.setup();
    await user.click(screen.getByRole("checkbox", { name: "Inlet Temp" }));
    expect(onChange).toHaveBeenCalledWith({ sensors: ["CPU 1", "Inlet Temp"], mode: "max" });
  });

  it("at eight ticked, the unticked boxes are disabled", () => {
    const eight = Array.from({ length: 8 }, (_, i) => `Temp ${i}`);
    renderPicker({ available: [...eight, "Temp 8"], selected: eight });
    expect(screen.getByRole("checkbox", { name: "Temp 8" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "Temp 0" })).toBeEnabled();
  });
});
