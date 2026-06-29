import { useState } from "react";
import { useTranslation } from "react-i18next";
import { ShieldCheck, ShieldOff } from "lucide-react";
import { useAuthStore } from "@/stores/auth-store";
import { post } from "@/api/client";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { useSettings } from "./SettingsContext";
import { SectionPanel, FieldGroup, inputClass, primaryBtnClass, secondaryBtnClass } from "./primitives";

interface SecuritySectionProps {
  headingRef: React.Ref<HTMLHeadingElement>;
}

/**
 * Security section — enable/disable local auth (D-08..D-10). Enabling requires
 * fresh creds + confirm (typo lock-out guard). Disabling requires the CURRENT
 * password (destructive 2-step confirm — preserved verbatim).
 */
export function SecuritySection({ headingRef }: SecuritySectionProps) {
  const { t } = useTranslation();
  const { online, offlineTip } = useSettings();
  const authEnabled = useAuthStore((s) => s.authEnabled);

  const [secUsername, setSecUsername] = useState("");
  const [secPassword, setSecPassword] = useState("");
  const [secPasswordConfirm, setSecPasswordConfirm] = useState("");
  const [secBusy, setSecBusy] = useState(false);
  const [secDisableConfirm, setSecDisableConfirm] = useState(false);
  const [secCurrentPassword, setSecCurrentPassword] = useState("");

  const enableAuth = async () => {
    if (!secUsername.trim() || !secPassword.trim()) {
      toast.error(t("settings.usernamePasswordRequired"));
      return;
    }
    if (secPassword !== secPasswordConfirm) {
      toast.error(t("settings.passwordsDoNotMatch"));
      return;
    }
    setSecBusy(true);
    try {
      await post("/api/auth/configure", { username: secUsername, password: secPassword });
      useAuthStore.setState({ authEnabled: true, authenticated: true, hasUser: true, username: secUsername });
      setSecUsername("");
      setSecPassword("");
      setSecPasswordConfirm("");
      toast.success(t("settings.authEnabledToast"));
    } catch {
      toast.error(t("settings.authEnableFailed"));
    } finally {
      setSecBusy(false);
    }
  };

  const disableAuth = async () => {
    if (!secCurrentPassword.trim()) {
      toast.error(t("settings.currentPasswordRequired"));
      return;
    }
    setSecBusy(true);
    try {
      const res = await post<{ success: boolean; error?: string }>(
        "/api/auth/toggle",
        { enabled: false, current_password: secCurrentPassword }
      );
      if (!res.success) {
        toast.error(res.error || t("settings.authDisableFailed"));
        return;
      }
      useAuthStore.setState({ authEnabled: false });
      setSecDisableConfirm(false);
      setSecCurrentPassword("");
      toast.success(t("settings.authDisabledToast"));
    } catch {
      toast.error(t("settings.authDisableFailed"));
    } finally {
      setSecBusy(false);
    }
  };

  const cancelDisable = () => {
    setSecDisableConfirm(false);
    setSecCurrentPassword("");
  };

  return (
    <SectionPanel
      ref={headingRef}
      headingId="settings-panel-heading"
      title={t("settings.security")}
      description={t("settings.sections.securityDescription")}
    >
      <FieldGroup
        title={t("settings.security")}
        action={
          authEnabled
            ? <span className="inline-flex items-center gap-1.5 rounded-full bg-success/10 px-2.5 py-0.5 text-xs font-medium text-success"><ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" /> {t("settings.sections.securityOn")}</span>
            : <span className="inline-flex items-center gap-1.5 rounded-full bg-muted px-2.5 py-0.5 text-xs font-medium text-muted-foreground"><ShieldOff className="h-3.5 w-3.5" aria-hidden="true" /> {t("settings.sections.securityOff")}</span>
        }
      >
        {authEnabled ? (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">{t("settings.authEnabledLabel")}</p>
            {!secDisableConfirm ? (
              <button onClick={() => setSecDisableConfirm(true)} disabled={secBusy || !online} title={offlineTip} className={secondaryBtnClass}>
                {t("settings.disableAuth")}
              </button>
            ) : (
              <div className="space-y-3 rounded-md border border-danger/30 bg-danger/5 p-3">
                <p className="text-xs text-muted-foreground">{t("settings.disableConfirmText")}</p>
                <input
                  type="password"
                  placeholder={t("settings.currentPasswordPlaceholder")}
                  value={secCurrentPassword}
                  onChange={(e) => setSecCurrentPassword(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") disableAuth(); }}
                  autoFocus
                  className={cn(inputClass, "font-mono")}
                />
                <div className="flex gap-2">
                  <button onClick={cancelDisable} disabled={secBusy} className={cn(secondaryBtnClass, "flex-1")}>{t("settings.cancel")}</button>
                  <button
                    onClick={disableAuth}
                    disabled={secBusy || !online || !secCurrentPassword.trim()}
                    title={offlineTip}
                    className="flex-1 rounded-md bg-danger px-3 py-2 text-sm font-semibold text-danger-foreground hover:bg-danger/90 min-h-[--control-min] md:min-h-9 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {secBusy ? t("settings.disabling") : t("settings.confirmDisable")}
                  </button>
                </div>
              </div>
            )}
            <p className="text-xs text-muted-foreground">{t("settings.reEnableNote")}</p>
          </div>
        ) : (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">{t("settings.authDisabledLabel")}</p>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <input placeholder={t("settings.secUsernamePlaceholder")} value={secUsername} onChange={(e) => setSecUsername(e.target.value)} className={inputClass} />
              <input type="password" placeholder={t("settings.secPasswordPlaceholder")} value={secPassword} onChange={(e) => setSecPassword(e.target.value)} className={cn(inputClass, "font-mono")} />
            </div>
            <input
              type="password"
              placeholder={t("settings.confirmPasswordPlaceholder")}
              value={secPasswordConfirm}
              onChange={(e) => setSecPasswordConfirm(e.target.value)}
              className={cn(
                "w-full rounded-md border bg-background px-3 py-2 text-sm font-mono min-h-[--control-min] md:min-h-9",
                secPassword && secPasswordConfirm && secPassword !== secPasswordConfirm ? "border-danger/60" : "border-border",
              )}
            />
            {secPassword && secPasswordConfirm && secPassword !== secPasswordConfirm && (
              <p className="text-xs text-danger">{t("settings.passwordsDoNotMatch")}</p>
            )}
            <button onClick={enableAuth} disabled={secBusy || !online} title={offlineTip} className={primaryBtnClass}>
              {t("settings.enableAuth")}
            </button>
          </div>
        )}
      </FieldGroup>
    </SectionPanel>
  );
}
