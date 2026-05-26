import { create } from "zustand";

export interface WidgetLayout {
  i: string;
  widget_id: string;
  module_id: string;
  server_id?: string;
  x: number;
  y: number;
  w: number;
  h: number;
  config?: Record<string, unknown>;
}

interface LayoutState {
  layout: WidgetLayout[];
  setLayout: (layout: WidgetLayout[]) => void;
  addWidget: (widget: WidgetLayout) => void;
  removeWidget: (id: string) => void;
  updateLayout: (layouts: Array<{ i: string; x: number; y: number; w: number; h: number }>) => void;
  setWidgetServer: (id: string, serverId: string) => void;
  updateWidgetConfig: (id: string, config: Record<string, unknown>) => void;
}

export const useLayoutStore = create<LayoutState>((set) => ({
  layout: [],

  setLayout: (layout) => set({ layout }),

  addWidget: (widget) =>
    set((state) => ({ layout: [...state.layout, widget] })),

  removeWidget: (id) =>
    set((state) => ({ layout: state.layout.filter((w) => w.i !== id) })),

  updateLayout: (layouts) =>
    set((state) => ({
      layout: state.layout.map((item) => {
        const updated = layouts.find((l) => l.i === item.i);
        if (updated) {
          return { ...item, x: updated.x, y: updated.y, w: updated.w, h: updated.h };
        }
        return item;
      }),
    })),

  setWidgetServer: (id, serverId) =>
    set((state) => ({
      layout: state.layout.map((w) => (w.i === id ? { ...w, server_id: serverId } : w)),
    })),

  updateWidgetConfig: (id, config) =>
    set((state) => ({
      layout: state.layout.map((w) =>
        w.i === id ? { ...w, config: { ...(w.config ?? {}), ...config } } : w
      ),
    })),
}));
