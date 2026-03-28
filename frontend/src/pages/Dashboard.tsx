import { Header } from "@/components/layout/Header";
import { Plus } from "lucide-react";

export default function Dashboard() {
  return (
    <>
      <Header title="Dashboard">
        <div className="flex items-center gap-1 rounded-md bg-muted p-0.5">
          <button className="rounded-sm bg-background px-2.5 py-1 text-xs font-medium shadow-sm">
            Live
          </button>
          <button className="rounded-sm px-2.5 py-1 text-xs font-medium text-muted-foreground hover:text-foreground">
            1H
          </button>
          <button className="rounded-sm px-2.5 py-1 text-xs font-medium text-muted-foreground hover:text-foreground">
            24H
          </button>
          <button className="rounded-sm px-2.5 py-1 text-xs font-medium text-muted-foreground hover:text-foreground">
            7D
          </button>
        </div>
        <button className="flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted">
          <Plus className="h-3 w-3" />
          Add Widget
        </button>
      </Header>
      <div className="flex-1 overflow-auto p-6">
        {/* Empty state */}
        <div className="flex flex-col items-center justify-center py-24 text-center">
          <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-xl bg-muted">
            <Plus className="h-6 w-6 text-muted-foreground" />
          </div>
          <h2 className="text-lg font-semibold">Your dashboard is empty</h2>
          <p className="mt-1 max-w-sm text-sm text-muted-foreground">
            Add widgets to monitor your servers. Click "Add Widget" to get started, or
            configure a server first in Settings.
          </p>
          <button className="mt-4 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:opacity-90">
            Add your first widget
          </button>
        </div>
      </div>
    </>
  );
}
