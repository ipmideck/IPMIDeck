import { Header } from "@/components/layout/Header";

export default function ModulesPage() {
  return (
    <>
      <Header title="Modules" />
      <div className="flex-1 overflow-auto p-6">
        <div className="flex flex-col items-center justify-center py-24 text-center">
          <h2 className="text-lg font-semibold">Module Catalog</h2>
          <p className="mt-1 max-w-sm text-sm text-muted-foreground">
            Enable or disable modules to customize your IPMILink experience.
          </p>
        </div>
      </div>
    </>
  );
}
