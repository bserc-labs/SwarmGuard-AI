import React, { Component, ErrorInfo, ReactNode } from "react";

interface Props {
  children?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("Uncaught error:", error, errorInfo);
  }

  private handleReboot = () => {
    window.location.reload();
  };

  public render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen bg-[#0e1417] flex flex-col items-center justify-center text-[#dde4e6] p-4 font-mono">
          <div className="glass-card p-10 max-w-2xl w-full text-center border-l-4 border-l-[#ffb4ab] relative overflow-hidden bg-[#1a2123]/60 backdrop-blur-md border border-[rgba(255,255,255,0.08)] rounded">
            {/* Sci-fi overlay effects */}
            <div className="absolute inset-0 bg-[#ffb4ab]/5 pointer-events-none"></div>
            
            <h1 className="text-4xl font-bold text-[#ffb4ab] mb-4 animate-pulse flex items-center justify-center gap-3">
              <span className="material-symbols-outlined text-5xl">warning</span>
              SYSTEM FAILURE
            </h1>
            
            <div className="bg-[#080f11] p-4 rounded text-left mb-8 border border-[#ffb4ab]/20 overflow-auto">
              <p className="text-[#ffb4ab] font-bold mb-2">ERROR_TRACE:</p>
              <code className="text-[#ffdeaa] text-sm whitespace-pre-wrap">
                {this.state.error?.toString() || "Unknown critical error occurred in React component tree."}
              </code>
            </div>

            <button
              onClick={this.handleReboot}
              className="bg-transparent border border-[#ffb4ab] text-[#ffb4ab] hover:bg-[#ffb4ab] hover:text-[#0e1417] px-6 py-3 rounded uppercase font-bold tracking-widest transition-all duration-300 flex items-center justify-center gap-2 mx-auto shadow-[0_0_15px_rgba(255,180,171,0.2)] hover:shadow-[0_0_25px_rgba(255,180,171,0.5)]"
            >
              <span className="material-symbols-outlined">restart_alt</span>
              REBOOT SYSTEM
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
