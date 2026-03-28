import { Header } from "@/components/layout/Header";

export default function FRUPage() {
  return (
    <>
      <Header title="Hardware" />
      <div className="flex-1 overflow-auto p-6">
        <div className="flex flex-col items-center justify-center py-24 text-center">
          <h2 className="text-lg font-semibold">Hardware Inventory</h2>
          <p className="mt-1 max-w-sm text-sm text-muted-foreground">
            View serial numbers, part numbers, and manufacturer information from your server's FRU data.
          </p>
        </div>
      </div>
    </>
  );
}
