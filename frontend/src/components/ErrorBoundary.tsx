import { Component, type ErrorInfo, type ReactNode } from "react";
import { Icon } from "@/components/ui/Icon";

interface Props {
  children?: ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * Catches render errors below it so one broken panel does not blank the console.
 * The message is shown plainly — an operator needs to know what failed, not be
 * told the system has suffered a catastrophe.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Replace with the error reporter once one is configured.
    console.error("Render error:", error, info.componentStack);
  }

  private reset = () => {
    this.setState({ error: null });
  };

  private reload = () => {
    window.location.reload();
  };

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <div className="flex min-h-[50vh] items-center justify-center p-6">
        <div className="w-full max-w-lg rounded-panel border border-line bg-surface-raised p-5">
          <div className="flex items-start gap-3">
            <Icon name="alert" size={18} className="mt-0.5 shrink-0 text-critical" />
            <div className="min-w-0">
              <h1 className="text-[15px] font-semibold text-content">This view failed to render</h1>
              <p className="mt-1 text-[13px] text-content-muted">
                The rest of the console is unaffected. Retrying re-renders this section; reloading
                restarts the app.
              </p>
            </div>
          </div>

          <pre className="mt-4 max-h-40 overflow-auto rounded-control border border-line bg-surface-sunken p-3 font-mono text-[12px] leading-relaxed text-content-muted">
            {error.message || String(error)}
          </pre>

          <div className="mt-4 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={this.reset}
              className="rounded-control border border-accent/50 bg-accent-dim px-3 py-1.5 text-[13px] text-content hover:bg-accent/25"
            >
              Try again
            </button>
            <button
              type="button"
              onClick={this.reload}
              className="rounded-control border border-line-strong bg-surface-overlay px-3 py-1.5 text-[13px] text-content hover:bg-surface-hover"
            >
              Reload console
            </button>
          </div>
        </div>
      </div>
    );
  }
}
