import { create } from "zustand";

export interface SensorReading {
  value: number | null;
  unit: string;
  status: string;
}

interface SensorState {
  /** Map of server_id -> sensor_name -> latest reading */
  readings: Record<string, Record<string, SensorReading>>;
  /** Map of server_id -> sensor_name -> sparkline buffer (last 60 values) */
  sparklines: Record<string, Record<string, number[]>>;

  updateSensors: (serverId: string, sensors: Record<string, SensorReading>) => void;
}

const MAX_SPARKLINE_POINTS = 60;

export const useSensorStore = create<SensorState>((set) => ({
  readings: {},
  sparklines: {},

  updateSensors: (serverId, sensors) =>
    set((state) => {
      const newSparklines = { ...state.sparklines };
      if (!newSparklines[serverId]) newSparklines[serverId] = {};

      for (const [name, reading] of Object.entries(sensors)) {
        if (reading.value !== null) {
          const buf = newSparklines[serverId][name] || [];
          const updated = [...buf, reading.value].slice(-MAX_SPARKLINE_POINTS);
          newSparklines[serverId] = { ...newSparklines[serverId], [name]: updated };
        }
      }

      return {
        readings: { ...state.readings, [serverId]: sensors },
        sparklines: newSparklines,
      };
    }),
}));
