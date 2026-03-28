import { Header } from "@/components/layout/Header";

export default function FanPilotPage() {
  return (
    <>
      <Header title="FanPilot" />
      <div className="flex-1 overflow-auto p-6">
        <div className="flex flex-col items-center justify-center py-24 text-center">
          <h2 className="text-lg font-semibold">Fan Curve Editor</h2>
          <p className="mt-1 max-w-sm text-sm text-muted-foreground">
            Create and manage fan speed profiles for your servers. Select a server from the sidebar to get started.
          </p>
        </div>
      </div>
    </>
  );
}
