import { useTranslation } from "react-i18next";
import { Bell, CheckCircle2, XCircle, Clock, MinusCircle } from "lucide-react";
import { toast } from "sonner";
import { useAlertingStore } from "@/stores/alerting-store";
import { cn } from "@/lib/utils";
import { useSettings } from "./SettingsContext";
import { SectionPanel, FieldGroup } from "./primitives";

interface NotificationsSectionProps {
  headingRef: React.Ref<HTMLHeadingElement>;
}

/**
 * Notifications section — browser-notifications opt-in (04-W3-01) + severity
 * filter note. Notification.requestPermission() MUST stay inside the toggle
 * onClick user gesture (medium caveat — store.enable() owns the call; it runs
 * from this click handler, never from an effect).
 *
 * The permission state is triple-encoded (color + icon + text) per the
 * colorblind companion pattern established in 06-02.
 */
export function NotificationsSection({ headingRef }: NotificationsSectionProps) {
  const { t } = useTranslation();
  const notificationsEnabled = useAlertingStore((s) => s.notificationsEnabled);
  const permission = useAlertingStore((s) => s.permission);
  const enableAlerting = useAlertingStore((s) => s.enable);
  const disableAlerting = useAlertingStore((s) => s.disable);
  // online not needed for the local permission gesture; the toggle itself is
  // a browser-permission flow, not a backend mutation (it persists best-effort).
  useSettings();

  const permissionMeta = {
    granted: { icon: CheckCircle2, cls: "text-success", text: t("settings.alerting.permissionGranted") },
    denied: { icon: XCircle, cls: "text-danger", text: t("settings.alerting.permissionDenied") },
    default: { icon: Clock, cls: "text-muted-foreground", text: t("settings.alerting.permissionPending") },
    unsupported: { icon: MinusCircle, cls: "text-muted-foreground", text: t("settings.alerting.permissionUnsupported") },
  }[permission];
  const PermIcon = permissionMeta.icon;

  return (
    <SectionPanel
      ref={headingRef}
      headingId="settings-panel-heading"
      title={t("settings.alerting.title")}
      description={t("settings.sections.notificationsDescription")}
    >
      <FieldGroup title={t("settings.alerting.title")} action={<Bell className="h-4 w-4 text-muted-foreground" aria-hidden="true" />}>
        <div className="flex items-center justify-between gap-3">
          <div className="flex-1">
            <label id="alerting-notif-label" className="text-sm font-medium text-foreground">{t("settings.alerting.enableNotifications")}</label>
            <p className="mt-1 text-xs text-muted-foreground">{t("settings.alerting.enableNotificationsHint")}</p>
          </div>
          {/* requestPermission MUST run inside this click handler (store.enable()). */}
          <button
            type="button"
            role="switch"
            aria-checked={notificationsEnabled}
            aria-labelledby="alerting-notif-label"
            onClick={async () => {
              if (notificationsEnabled) {
                await disableAlerting();
              } else {
                const perm = await enableAlerting();
                if (perm === "denied") toast.error(t("settings.alerting.permissionDenied"));
                else if (perm === "granted") toast.success(t("settings.alerting.permissionGranted"));
              }
            }}
            className={cn(
              "relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent transition-colors min-h-[--control-min] min-w-[--control-min] md:min-h-6 md:min-w-11",
              notificationsEnabled ? "bg-success" : "bg-muted",
            )}
          >
            <span className={cn("pointer-events-none inline-block h-5 w-5 transform rounded-full bg-background shadow ring-0 transition", notificationsEnabled ? "translate-x-5" : "translate-x-0")} />
          </button>
        </div>

        <p className={cn("mt-3 inline-flex items-center gap-1.5 text-xs", permissionMeta.cls)}>
          <PermIcon className="h-3.5 w-3.5" aria-hidden="true" />
          {permissionMeta.text}
        </p>

        <p className="mt-2 text-xs text-muted-foreground">{t("settings.alerting.severityFilter")}</p>
      </FieldGroup>
    </SectionPanel>
  );
}
