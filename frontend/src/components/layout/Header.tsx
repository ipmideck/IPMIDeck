import { useServerStore } from "@/stores/server-store";
import { useWebSocket, type WSStatus } from "@/hooks/useWebSocket";
import { cn } from "@/lib/utils";

interface HeaderProps {
  title: string;
  children?: React.ReactNode;
}

function ConnectionBadge({ status }: { status: WSStatus }) {
  return (
    <div
      className={cn(
        "flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium",
        status === "connected" && "bg-emerald-500/10 text-emerald-500",
        status === "connecting" && "bg-yellow-500/10 text-yellow-500",
        status === "disconnected" && "bg-red-500/10 text-red-500"
      )}
    >
      <div
        className={cn(
          "h-1.5 w-1.5 rounded-full",
          status === "connected" && "bg-emerald-500",
          status === "connecting" && "bg-yellow-500",
          status === "disconnected" && "bg-red-500"
        )}
      />
      {status === "connected" ? "Live" : status === "connecting" ? "Connecting" : "Offline"}
    </div>
  );
}

export function Header({ title, children }: HeaderProps) {
  const { status } = useWebSocket();
  const contextServer = useServerStore((s) =>
    s.servers.find((srv) => srv.id === s.contextServerId)
  );

  return (
    <header className="flex h-[52px] items-center justify-between border-b border-border bg-card px-6">
      <div className="flex items-center gap-2 text-[13px]">
        {contextServer && (
          <>
            <span className="text-muted-foreground">{contextServer.name}</span>
            <span className="text-muted-foreground">/</span>
          </>
        )}
        <span className="font-medium">{title}</span>
        <ConnectionBadge status={status} />
      </div>
      <div className="flex items-center gap-2">{children}</div>
    </header>
  );
}
