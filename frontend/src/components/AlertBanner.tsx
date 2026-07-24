import { useEffect, useState } from "react";
import { useWebSocketContext } from "@/contexts/WebSocketContext";
import { Link } from "@tanstack/react-router";

export function AlertBanner() {
  const { lastAlert } = useWebSocketContext();
  const [isVisible, setIsVisible] = useState(false);
  const [currentAlert, setCurrentAlert] = useState<typeof lastAlert | null>(null);

  useEffect(() => {
    if (lastAlert && (lastAlert.severity === "CRITICAL" || lastAlert.severity === "HIGH")) {
      setCurrentAlert(lastAlert);
      setIsVisible(true);

      const timer = setTimeout(() => {
        setIsVisible(false);
      }, 10000); // dismiss after 10 seconds

      return () => clearTimeout(timer);
    }
  }, [lastAlert]);

  if (!isVisible || !currentAlert) return null;

  const topFeature = currentAlert.shap_top3 && currentAlert.shap_top3.length > 0 
    ? currentAlert.shap_top3[0] 
    : null;

  return (
    <div className="fixed top-6 left-1/2 -translate-x-1/2 z-[100] w-full max-w-2xl animate-fade-in pointer-events-auto">
      <div className={`relative overflow-hidden rounded-xl border p-4 shadow-2xl backdrop-blur-xl flex items-center justify-between gap-4
        ${currentAlert.severity === 'CRITICAL' ? 'bg-red-500/20 border-red-500/50 shadow-red-500/20' : 'bg-amber-500/20 border-amber-500/50 shadow-amber-500/20'}
      `}>
        {/* Animated Background Pulse */}
        <div className={`absolute inset-0 opacity-20 ${currentAlert.severity === 'CRITICAL' ? 'animate-pulse-red' : 'animate-pulse'}`} />

        <div className="flex items-center gap-4 relative z-10">
          <div className={`w-12 h-12 rounded-full flex items-center justify-center border
            ${currentAlert.severity === 'CRITICAL' ? 'bg-red-500/20 border-red-500/50 text-red-500' : 'bg-amber-500/20 border-amber-500/50 text-amber-500'}
          `}>
            <span className="material-symbols-outlined filled text-3xl">warning</span>
          </div>

          <div>
            <div className="flex items-center gap-3 mb-1">
              <h3 className="text-lg font-bold text-white tracking-widest uppercase">
                {currentAlert.attack_type || "UNKNOWN ANOMALY"} DETECTED
              </h3>
              <span className={`text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded
                ${currentAlert.severity === 'CRITICAL' ? 'bg-red-500 text-white' : 'bg-amber-500 text-black'}
              `}>
                {currentAlert.severity}
              </span>
            </div>
            
            <p className="text-sm text-sg-text-muted font-mono mb-1">
              Threat Score: <span className="text-white font-bold">{currentAlert.threat_level || 0}/100</span>
            </p>
            
            {topFeature && (
              <p className="text-xs text-sg-text-dim max-w-lg truncate">
                <span className="text-sg-primary font-mono">{topFeature.feature}</span> contributed {Math.round(topFeature.value * 100)}%
              </p>
            )}
          </div>
        </div>

        <div className="flex flex-col gap-2 relative z-10">
          <button 
            onClick={() => setIsVisible(false)}
            className="w-8 h-8 flex items-center justify-center rounded-full hover:bg-white/10 text-sg-text-dim hover:text-white transition-colors"
          >
            <span className="material-symbols-outlined text-sm">close</span>
          </button>
          <Link 
            to="/incidents"
            onClick={() => setIsVisible(false)}
            className="text-[10px] uppercase tracking-wider text-sg-primary hover:text-white font-bold transition-colors whitespace-nowrap"
          >
            View Details
          </Link>
        </div>
      </div>
    </div>
  );
}
