import { useSensorStore } from "@/stores/sensor-store";
import { cn } from "@/lib/utils";

interface VoltagesWidgetProps {
  serverId: string;
}

const VOLTAGE_SENSORS = ["12V", "5V", "3.3V", "Vcore"];
const PSU_SENSORS = ["PSU1 Status", "PSU2 Status"];

export function VoltagesWidget({ serverId }: VoltagesWidgetProps) {
  const readings = useSensorStore((s) => s.readings[serverId]);

  return (
    <div className="flex h-full flex-col gap-2">
      <div className="space-y-1.5">
        {VOLTAGE_SENSORS.map((name) => {
          const r = readings?.[name];
          return (
            <div key={name} className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">{name}</span>
              <span className={cn("font-mono text-xs font-medium", r?.status === "ok" ? "text-emerald-500" : r?.status === "warning" ? "text-yellow-500" : "text-muted-foreground")}>
                {r?.value != null ? `${r.value}V` : "—"}
              </span>
            </div>
          );
        })}
      </div>
      <div className="mt-auto border-t border-border pt-2">
        <div className="flex gap-2">
          {PSU_SENSORS.map((name, i) => {
            const r = readings?.[name];
            const isOk = r?.status === "ok";
            return (
              <div key={name} className="flex flex-1 items-center justify-between rounded-md bg-muted px-2.5 py-1.5">
                <span className="text-[10px] text-muted-foreground">PSU {i + 1}</span>
                <span className={cn("font-mono text-[10px] font-semibold", isOk ? "text-emerald-500" : "text-red-500")}>
                  {isOk ? "OK" : r ? "FAIL" : "—"}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
