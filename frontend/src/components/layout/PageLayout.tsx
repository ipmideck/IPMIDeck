import { Sidebar } from "./Sidebar";
import { CommandPanel } from "./CommandPanel";
import { DemoBanner } from "@/components/DemoBanner";
import { ConnectionBanner } from "@/components/ConnectionBanner";
import { useWebSocket } from "@/hooks/useWebSocket";

interface PageLayoutProps {
  children: React.ReactNode;
}

export function PageLayout({ children }: PageLayoutProps) {
  // Hoisted here so the WebSocket lives for the lifetime of the authenticated app
  // shell instead of being torn down / re-created every time the user navigates
  // between pages (which used to happen because Header called useWebSocket).
  // Status is mirrored into the connection store; Header + widgets read it from there.
  useWebSocket();

  // h-screen + min-h-0 on flex children: pins the chrome (DemoBanner,
  // ConnectionBanner, Header) to the viewport so the document never grows past
  // it. The scroll happens INSIDE the page's own overflow-auto region (e.g.
  // Dashboard's widget area), keeping the top bar always visible. Previously
  // min-h-screen let the page expand and dragged the header off-screen on
  // scroll.
  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <DemoBanner />
      <ConnectionBanner />
      <div className="flex min-h-0 flex-1">
        <Sidebar />
        <main className="flex min-h-0 min-w-0 flex-1 flex-col">{children}</main>
        <CommandPanel />
      </div>
    </div>
  );
}
