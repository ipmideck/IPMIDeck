import { create } from "zustand";
import { get, put } from "@/api/client"; // Decision D — named imports, NO apiClient

interface AlertingStore {
  notificationsEnabled: boolean;
  permission: NotificationPermission | "unsupported";
  hydrated: boolean;
  hydrate: () => Promise<void>;
  enable: () => Promise<NotificationPermission | "unsupported">;
  disable: () => Promise<void>;
}

function currentPermission(): NotificationPermission | "unsupported" {
  if (typeof Notification === "undefined") return "unsupported";
  return Notification.permission;
}

export const useAlertingStore = create<AlertingStore>((set, getState) => ({
  notificationsEnabled: false,
  permission: currentPermission(),
  hydrated: false,
  hydrate: async () => {
    if (getState().hydrated) return;
    try {
      // Decision B — /api/system/... K/V app-config endpoint (alerting.notifications_enabled
      // is in the backend ALLOWED set from 04-01).
      const res = await get<{ success: boolean; value: boolean | null }>(
        "/api/system/app-config/alerting.notifications_enabled"
      );
      const enabled = res?.value === true;
      const perm = currentPermission();
      // Only treat notifications as enabled if the browser still grants permission —
      // a stored `true` is meaningless once the user revokes the OS/browser permission.
      set({
        notificationsEnabled: enabled && perm === "granted",
        permission: perm,
        hydrated: true,
      });
    } catch {
      set({ hydrated: true });
    }
  },
  enable: async () => {
    if (typeof Notification === "undefined") return "unsupported";
    let perm: NotificationPermission = Notification.permission;
    // Only request when undecided — requestPermission MUST run inside the toggle click
    // handler (this is called from the Settings toggle onClick) per the Notifications spec.
    if (perm === "default") {
      try {
        perm = await Notification.requestPermission();
      } catch {
        perm = "denied";
      }
    }
    set({ permission: perm });
    if (perm === "granted") {
      set({ notificationsEnabled: true });
      await put("/api/system/app-config/alerting.notifications_enabled", { value: true });
    } else {
      set({ notificationsEnabled: false });
    }
    return perm;
  },
  disable: async () => {
    set({ notificationsEnabled: false });
    await put("/api/system/app-config/alerting.notifications_enabled", { value: false });
  },
}));
