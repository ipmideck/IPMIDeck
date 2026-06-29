import React, { Component, type ReactNode } from "react";
import i18n from "@/i18n";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  renderFallback?: (error: Error | null) => ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error("[ErrorBoundary] Caught error:", error);
    console.error("[ErrorBoundary] Component stack:", errorInfo.componentStack);
  }

  render() {
    if (this.state.hasError) {
      if (this.props.renderFallback) return this.props.renderFallback(this.state.error);
      if (this.props.fallback) return this.props.fallback;
      return (
        <div className="flex min-h-screen items-center justify-center bg-background p-8">
          <div className="max-w-md rounded-lg border border-danger/30 bg-danger/10 p-6">
            <h2 className="text-lg font-semibold text-danger">{i18n.t("error.title")}</h2>
            <p className="mt-2 font-mono text-sm text-danger">
              {this.state.error?.message}
            </p>
            <button
              onClick={() => {
                this.setState({ hasError: false, error: null });
                window.location.reload();
              }}
              className="mt-4 rounded-md bg-danger px-4 py-2 text-sm font-medium text-danger-foreground hover:bg-danger/90"
            >
              {i18n.t("error.reload")}
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

/** Small inline error for widgets — doesn't kill the whole page */
export function WidgetErrorFallback({ error }: { error?: Error | null }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-1 text-xs text-danger">
      <span>{i18n.t("error.widgetError")}</span>
      {error?.message && (
        <span className="max-w-full truncate px-2 text-[10px] text-danger/70">{error.message}</span>
      )}
    </div>
  );
}
