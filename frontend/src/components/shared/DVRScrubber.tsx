import { useState, useEffect } from "react";
import { api, type TelemetryPacket } from "@/services/api";

interface DVRScrubberProps {
  onHistoricalDataUpdate: (data: TelemetryPacket[] | null) => void;
}

export function DVRScrubber({ onHistoricalDataUpdate }: DVRScrubberProps) {
  const [dvrActive, setDvrActive] = useState(false);
  const [timeOffsetMinutes, setTimeOffsetMinutes] = useState(0); // 0 means live, -30 means 30 mins ago
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!dvrActive || timeOffsetMinutes === 0) {
      onHistoricalDataUpdate(null); // Return to live
      return;
    }

    const fetchHistory = async () => {
      setLoading(true);
      try {
        const now = new Date();
        // Target time is now - abs(timeOffsetMinutes)
        const targetTime = new Date(now.getTime() - Math.abs(timeOffsetMinutes) * 60000);
        // Window of 10 seconds around target time to show a snapshot
        const startTime = new Date(targetTime.getTime() - 10000);
        const endTime = new Date(targetTime.getTime() + 10000);

        const data = await api.getTelemetryHistory(startTime.toISOString(), endTime.toISOString());
        // Get the latest packet for each drone in this small 20-second window
        const map = new Map<string, TelemetryPacket>();
        data.forEach(d => map.set(d.drone_id, d));
        onHistoricalDataUpdate(Array.from(map.values()));
      } catch (e) {
        console.error("Failed to fetch DVR data", e);
      } finally {
        setLoading(false);
      }
    };

    const timeout = setTimeout(fetchHistory, 500); // Debounce slider changes
    return () => clearTimeout(timeout);
  }, [dvrActive, timeOffsetMinutes, onHistoricalDataUpdate]);

  return (
    <div className="absolute bottom-6 left-1/2 -translate-x-1/2 z-[400] w-[500px] bg-black/80 backdrop-blur-md border border-white/20 rounded-lg p-3 font-mono shadow-2xl">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <button
            onClick={() => {
              setDvrActive(!dvrActive);
              if (dvrActive) setTimeOffsetMinutes(0);
            }}
            className={`px-3 py-1 rounded text-xs font-bold border transition ${
              dvrActive 
                ? "bg-amber-500/20 border-amber-500 text-amber-400 animate-pulse" 
                : "bg-white/10 border-white/20 text-sg-text hover:bg-white/20"
            }`}
          >
            {dvrActive ? "🔴 DVR ACTIVE" : "▶ LIVE"}
          </button>
          {loading && <span className="text-[10px] text-[#00d9ff] animate-pulse">Buffering...</span>}
        </div>
        <div className="text-xs text-sg-text-dim">
          {timeOffsetMinutes === 0 ? "Real-time" : `T - ${Math.abs(timeOffsetMinutes)} min`}
        </div>
      </div>
      
      <div className={`transition-opacity ${dvrActive ? 'opacity-100' : 'opacity-30 pointer-events-none'}`}>
        <input
          type="range"
          min="-60"
          max="0"
          value={timeOffsetMinutes}
          onChange={(e) => setTimeOffsetMinutes(Number(e.target.value))}
          className="w-full accent-amber-500 h-1.5 bg-white/20 rounded-lg appearance-none cursor-pointer"
        />
        <div className="flex justify-between text-[9px] text-sg-text-muted mt-1 uppercase">
          <span>-60 Mins</span>
          <span>-30 Mins</span>
          <span>Live</span>
        </div>
      </div>
    </div>
  );
}
