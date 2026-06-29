import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Header } from "@/components/layout/Header";
import { EmptyState } from "@/components/common/EmptyState";
import { useBackendOnline } from "@/stores/connection-store";
import { get, put } from "@/api/client";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import {
  Thermometer,
  Fan,
  Power,
  List,
  Cpu,
  CheckCircle2,
  CircleSlash,
  RotateCw,
  AlertTriangle,
  PackageOpen,
} from "lucide-react";

interface Module {
  id: string;
  name: string;
  version: string;
  description: string;
  category: string;
  icon: string;
  enabled: boolean;
  dependencies: string[];
}

const ICONS: Record<string, React.ReactNode> = {
  thermometer: <Thermometer className="h-5 w-5" />,
  fan: <Fan className="h-5 w-5" />,
  power: <Power className="h-5 w-5" />,
  list: <List className="h-5 w-5" />,
  cpu: <Cpu className="h-5 w-5" />,
};

export default function ModulesPage() {
  const { t } = useTranslation();
  const [modules, setModules] = useState<Module[]>([]);
  // load lifecycle so the surface can teach (loading -> empty -> error), instead
  // of silently swallowing a failed fetch (Error Recovery: name the problem + retry).
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  // Modules whose last enable returned restart_required. Tracked client-side
  // (the GET payload has no such field) so the card can carry a persistent
  // "restart required" affordance instead of a one-shot toast. Cleared on a
  // full reload (a real restart re-fetches with the module already active).
  const [restartIds, setRestartIds] = useState<Set<string>>(new Set());
  // R-5: when disabling a module that has ENABLED dependents, we hold a pending
  // confirm so the user sees (and approves) the cascade before it stops those
  // dependents — instead of an after-the-fact toast. Mirrors the app's inline
  // destructive-confirm pattern (PowerControlsWidget): the action arms a confirm,
  // a second action (or the explicit Confirm button) commits it; Cancel disarms.
  const [confirmDisableId, setConfirmDisableId] = useState<string | null>(null);
  const online = useBackendOnline();

  // Enabled modules that DEPEND on `id` (forward dependency search) — these are the
  // ones a cascading disable would stop. Names resolved for the confirm copy.
  const enabledDependentsOf = (id: string) =>
    modules
      .filter((m) => m.enabled && m.id !== id && m.dependencies.includes(id))
      .map((m) => m.name);

  const loadModules = async () => {
    try {
      const data = await get<{ modules: Module[] }>("/api/admin/modules");
      setModules(data.modules);
      setStatus("ready");
    } catch {
      setStatus("error");
    }
  };

  useEffect(() => { loadModules(); }, []);

  // Toggle entry point from the switch. Enabling, or disabling a module with no
  // enabled dependents, runs immediately. Disabling a module WITH enabled dependents
  // arms the inline confirm (naming them) on the first click; the confirm UI commits.
  const onToggle = (id: string, enabled: boolean) => {
    if (!enabled && enabledDependentsOf(id).length > 0) {
      setConfirmDisableId(id);
      return;
    }
    setConfirmDisableId(null);
    toggleModule(id, enabled);
  };

  const toggleModule = async (id: string, enabled: boolean) => {
    setConfirmDisableId(null);
    try {
      const name = modules.find((m) => m.id === id)?.name ?? id;
      const res = await put<{
        enabled: boolean;
        restart_required?: boolean;
        stopped_dependents?: string[];
      }>(`/api/admin/modules/${id}`, { enabled });
      if (enabled) {
        if (res.restart_required) {
          setRestartIds((prev) => new Set(prev).add(id));
          toast.message(t("modules.enabledRestart", { name }));
        } else {
          setRestartIds((prev) => {
            const next = new Set(prev);
            next.delete(id);
            return next;
          });
          toast.success(t("modules.enabled", { name }));
        }
      } else {
        setRestartIds((prev) => {
          const next = new Set(prev);
          next.delete(id);
          return next;
        });
        const deps = res.stopped_dependents ?? [];
        if (deps.length > 0) {
          const depNames = deps
            .map((d) => modules.find((m) => m.id === d)?.name ?? d)
            .join(", ");
          toast.success(t("modules.disabledWithDeps", { name, deps: depNames }));
        } else {
          toast.success(t("modules.disabled", { name }));
        }
      }
      // Refresh so the page reflects the new enabled state (including any
      // cascade-disabled dependents).
      await loadModules();
    } catch {
      toast.error(t("modules.toggleFailed"));
    }
  };

  const enabledCount = modules.filter((m) => m.enabled).length;

  return (
    <>
      <Header title={t("nav.modules")} />
      <div className="flex-1 overflow-auto p-6">
        <div className="mx-auto max-w-3xl">
          {/* Lead element: title + at-a-glance enabled count, earning the top of
              the hierarchy over the warm canvas. */}
          <div className="mb-5">
            <h1 className="text-2xl font-semibold tracking-tight text-foreground">
              {t("modules.title")}
            </h1>
            {modules.length > 0 && (
              <p className="mt-1 text-sm text-muted-foreground">
                {t("modules.summary", {
                  enabled: enabledCount,
                  total: modules.length,
                })}
              </p>
            )}
            <p className="mt-3 max-w-prose text-sm leading-relaxed text-muted-foreground">
              {t("modules.intro")}
            </p>
          </div>
          {status === "loading" && (
            <div className="space-y-3" aria-hidden="true">
              {[0, 1, 2].map((i) => (
                <div
                  key={i}
                  className="h-[88px] animate-pulse rounded-xl border border-border bg-muted"
                />
              ))}
            </div>
          )}
          {status === "error" && (
            <EmptyState
              icon={AlertTriangle}
              title={t("modules.loadErrorTitle")}
              description={t("modules.loadErrorHint")}
              action={{ label: t("modules.retry"), onClick: () => { setStatus("loading"); loadModules(); } }}
            />
          )}
          {status === "ready" && modules.length === 0 && (
            <EmptyState
              icon={PackageOpen}
              title={t("modules.emptyTitle")}
              description={t("modules.emptyHint")}
            />
          )}
          {status === "ready" && modules.length > 0 && (
          <div className="space-y-3">
            {modules.map((mod) => {
              const restartRequired = restartIds.has(mod.id);
              const stateLabel = mod.enabled
                ? t("modules.statusEnabled")
                : t("modules.statusDisabled");
              const confirming = confirmDisableId === mod.id;
              const dependents = confirming ? enabledDependentsOf(mod.id) : [];
              return (
                <div
                  key={mod.id}
                  className={cn(
                    "rounded-xl border bg-card p-4 shadow-sm transition-shadow hover:shadow-md",
                    confirming ? "border-danger/50" : "border-border",
                    !mod.enabled && "opacity-70"
                  )}
                >
                <div className="flex items-center gap-4">
                  <div
                    className={cn(
                      "flex h-11 w-11 shrink-0 items-center justify-center rounded-lg transition-colors",
                      mod.enabled
                        ? "bg-success/10 text-success"
                        : "bg-muted text-muted-foreground"
                    )}
                  >
                    {ICONS[mod.icon] || ICONS.cpu}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                      <span className="text-base font-semibold text-foreground">{mod.name}</span>
                      <span className="font-mono text-[10px] text-muted-foreground">v{mod.version}</span>
                      <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">{mod.category}</span>
                      {/* State companion (D-04): color + a distinct icon shape +
                          a translated text label — never color alone. */}
                      <span
                        className={cn(
                          "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium",
                          mod.enabled
                            ? "bg-success/10 text-success"
                            : "bg-muted text-muted-foreground"
                        )}
                      >
                        {mod.enabled ? (
                          <CheckCircle2 className="h-3 w-3" aria-hidden="true" />
                        ) : (
                          <CircleSlash className="h-3 w-3" aria-hidden="true" />
                        )}
                        {stateLabel}
                      </span>
                      {restartRequired && (
                        <span className="inline-flex items-center gap-1 rounded-full bg-warning/10 px-2 py-0.5 text-[11px] font-medium text-warning">
                          <RotateCw className="h-3 w-3" aria-hidden="true" />
                          {t("modules.restartRequired")}
                        </span>
                      )}
                    </div>
                    <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{mod.description}</p>
                    {mod.dependencies.length > 0 && (
                      <p className="mt-1 text-[10px] text-muted-foreground">{t("modules.dependsOn", { deps: mod.dependencies.join(", ") })}</p>
                    )}
                  </div>
                  <button
                    onClick={() => onToggle(mod.id, !mod.enabled)}
                    disabled={!online}
                    role="switch"
                    aria-checked={mod.enabled}
                    aria-label={t("modules.toggleAria", { name: mod.name, state: stateLabel })}
                    title={!online ? t("header.backendDisconnected") : undefined}
                    className={cn(
                      "relative h-6 w-11 shrink-0 rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-50",
                      mod.enabled ? "bg-success" : "bg-muted"
                    )}
                  >
                    <div className={cn(
                      "absolute top-0.5 h-5 w-5 rounded-full bg-card shadow transition-transform",
                      mod.enabled ? "translate-x-5" : "translate-x-0.5"
                    )} />
                  </button>
                </div>

                {/* R-5: cascading-disable confirm. Armed when disabling a module with
                    enabled dependents — NAMES them up-front so the operator approves the
                    cascade before it happens (not an after-the-fact toast). Same inline
                    confirm UX the rest of the app uses for destructive actions. */}
                {confirming && (
                  <div
                    role="alertdialog"
                    aria-label={t("modules.disableConfirmTitle", { name: mod.name })}
                    className="mt-3 flex flex-col gap-2 rounded-lg border border-danger/40 bg-danger/10 p-3"
                  >
                    <div className="flex items-start gap-2">
                      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-danger" aria-hidden="true" />
                      <p className="text-xs leading-relaxed text-foreground">
                        {t("modules.disableConfirmBody", {
                          name: mod.name,
                          deps: dependents.join(", "),
                        })}
                      </p>
                    </div>
                    <div className="flex justify-end gap-2">
                      <button
                        type="button"
                        onClick={() => setConfirmDisableId(null)}
                        className="rounded-md border border-border px-3 py-1.5 text-xs font-medium text-muted-foreground hover:bg-muted min-h-9 transition-colors"
                      >
                        {t("modules.disableConfirmCancel")}
                      </button>
                      <button
                        type="button"
                        onClick={() => toggleModule(mod.id, false)}
                        disabled={!online}
                        className="rounded-md bg-danger px-3 py-1.5 text-xs font-semibold text-white hover:bg-danger/90 min-h-9 transition-colors disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {t("modules.disableConfirmConfirm")}
                      </button>
                    </div>
                  </div>
                )}
                </div>
              );
            })}
          </div>
          )}
        </div>
      </div>
    </>
  );
}
