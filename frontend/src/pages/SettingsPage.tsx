import { Header } from "@/components/layout/Header";

export default function SettingsPage() {
  return (
    <>
      <Header title="Settings" />
      <div className="flex-1 overflow-auto p-6">
        <div className="flex flex-col items-center justify-center py-24 text-center">
          <h2 className="text-lg font-semibold">Settings</h2>
          <p className="mt-1 max-w-sm text-sm text-muted-foreground">
            Manage servers, authentication, and application configuration.
          </p>
        </div>
      </div>
    </>
  );
}
