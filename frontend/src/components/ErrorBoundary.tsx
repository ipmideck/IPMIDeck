import React, { Component, type ReactNode } from "react";

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
          <div className="max-w-md rounded-lg border border-red-500/30 bg-red-500/10 p-6">
            <h2 className="text-lg font-semibold text-red-500">Something went wrong</h2>
            <p className="mt-2 font-mono text-sm text-red-400">
              {this.state.error?.message}
            </p>
            <button
              onClick={() => {
                this.setState({ hasError: false, error: null });
                window.location.reload();
              }}
              className="mt-4 rounded-md bg-red-500 px-4 py-2 text-sm font-medium text-white hover:bg-red-600"
            >
              Reload
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
    <div className="flex h-full flex-col items-center justify-center gap-1 text-xs text-red-400">
      <span>Widget error</span>
      {error?.message && (
        <span className="max-w-full truncate px-2 text-[10px] text-red-400/70">{error.message}</span>
      )}
    </div>
  );
}
