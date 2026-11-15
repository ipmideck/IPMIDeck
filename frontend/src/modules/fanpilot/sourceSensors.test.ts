import { describe, expect, it } from "vitest";
import {
  MAX_SOURCE_SENSORS,
  combineTemps,
  profileSavePayload,
  profileSensorMode,
  profileSensors,
  toggleSensor,
} from "@/modules/fanpilot/sourceSensors";

describe("profileSensors", () => {
  it("returns the stored list", () => {
    expect(profileSensors({ source_sensor: "A", source_sensors: ["A", "B"] })).toEqual(["A", "B"]);
  });

  it("falls back to the single sensor", () => {
    expect(profileSensors({ source_sensor: "A" })).toEqual(["A"]);
    expect(profileSensors({ source_sensor: "A", source_sensors: [] })).toEqual(["A"]);
    expect(profileSensors({ source_sensor: "A", source_sensors: "A,B" })).toEqual(["A"]);
    expect(profileSensors({ source_sensor: "A", source_sensors: ["A", 2] })).toEqual(["A"]);
  });

  it("uses the default when nothing is stored", () => {
    expect(profileSensors({ source_sensor: "" })).toEqual(["CPU Temp"]);
    expect(profileSensors({})).toEqual(["CPU Temp"]);
  });
});

describe("profileSensorMode", () => {
  it("is avg only for avg", () => {
    expect(profileSensorMode({ sensor_mode: "avg" })).toBe("avg");
    expect(profileSensorMode({ sensor_mode: "max" })).toBe("max");
    expect(profileSensorMode({ sensor_mode: "AVG" })).toBe("max");
    expect(profileSensorMode({})).toBe("max");
  });
});

describe("combineTemps", () => {
  it("takes the hottest or the mean", () => {
    expect(combineTemps([40, 61], "max")).toBe(61);
    expect(combineTemps([40, 61], "avg")).toBe(50.5);
    expect(combineTemps([47], "avg")).toBe(47);
  });

  it("is null when any reading is missing, or when there are none", () => {
    expect(combineTemps([40, null], "max")).toBeNull();
    expect(combineTemps([40, undefined], "avg")).toBeNull();
    expect(combineTemps([40, Number.NaN], "max")).toBeNull();
    expect(combineTemps([], "max")).toBeNull();
  });
});

describe("toggleSensor", () => {
  it("appends a ticked sensor and removes an unticked one", () => {
    expect(toggleSensor(["A"], "B")).toEqual(["A", "B"]);
    expect(toggleSensor(["A", "B", "C"], "B")).toEqual(["A", "C"]);
  });

  it("never empties the selection", () => {
    expect(toggleSensor(["A"], "A")).toEqual(["A"]);
  });

  it("never goes past the maximum", () => {
    const full = Array.from({ length: MAX_SOURCE_SENSORS }, (_, i) => `T${i}`);
    expect(MAX_SOURCE_SENSORS).toBe(8);
    expect(toggleSensor(full, "extra")).toEqual(full);
  });
});

describe("profileSavePayload", () => {
  it("sends the list and the mode, not the single sensor", () => {
    const payload = profileSavePayload({
      name: "Quiet",
      description: "d",
      curve_points: [{ temp: 30, speed: 20 }],
      hysteresis: 3,
      safety_threshold: 85,
      source_sensors: ["CPU 1", "CPU 2"],
      sensor_mode: "avg",
      source_sensor: "CPU 1",
    } as Parameters<typeof profileSavePayload>[0]);
    expect(payload).toEqual({
      name: "Quiet",
      description: "d",
      curve_points: [{ temp: 30, speed: 20 }],
      hysteresis: 3,
      safety_threshold: 85,
      source_sensors: ["CPU 1", "CPU 2"],
      sensor_mode: "avg",
    });
    expect(payload).not.toHaveProperty("source_sensor");
  });
});
