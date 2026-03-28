import { Header } from "@/components/layout/Header";

export default function SELPage() {
  return (
    <>
      <Header title="Event Log" />
      <div className="flex-1 overflow-auto p-6">
        <div className="flex flex-col items-center justify-center py-24 text-center">
          <h2 className="text-lg font-semibold">System Event Log</h2>
          <p className="mt-1 max-w-sm text-sm text-muted-foreground">
            View hardware events from your server's BMC. Select a server from the sidebar, then refresh to load events.
          </p>
        </div>
      </div>
    </>
  );
}
