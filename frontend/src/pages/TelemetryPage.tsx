import { useQuery } from "@tanstack/react-query";
import { api, type TelemetryPacket } from "@/services/api";
import { useWebSocketContext } from "@/contexts/WebSocketContext";
import { GlassCard } from "@/components/shared/GlassCard";
import { MetricCard } from "@/components/shared/MetricCard";
import { SeverityBadge } from "@/components/shared/SeverityBadge";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { SEVERITY_COLORS } from "@/lib/constants";

export default function TelemetryPage() {
  const { isConnected, alerts } = useWebSocketContext();
  const { data: telemetry = [], isLoading } = useQuery({
    queryKey: ['telemetry-live'],
    queryFn: api.getTelemetryLive,
    refetchInterval: 10000,
  });

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <LoadingSpinner />
      </div>
    );
  }

  // Calculate summary metrics
  const avgAltitude = telemetry.length > 0
    ? (telemetry.reduce((sum, t) => sum + t.altitude, 0) / telemetry.length).toFixed(1)
    : "0";
  const avgSpeed = telemetry.length > 0
    ? (telemetry.reduce((sum, t) => sum + t.speed, 0) / telemetry.length).toFixed(1)
    : "0";

  // Group by drone_id to get latest packet
  const latestByDrone: Record<string, TelemetryPacket> = {};
  telemetry.forEach(t => {
    // Assuming higher timestamp comes later or we just keep replacing since backend usually orders it
    latestByDrone[t.drone_id] = t;
  });
  const activeDrones = Object.values(latestByDrone);

  return (
    <div className="flex flex-col gap-6 p-6">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-sg-text font-inter">Live Telemetry Monitoring</h1>
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-sg-surface border border-white/5">
          {isConnected ? (
            <>
              <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse-cyan shadow-[0_0_8px_#4ade80]"></div>
              <span className="text-xs font-medium text-green-400 tracking-wider">LIVE DATA STREAM</span>
            </>
          ) : (
            <>
              <div className="w-2 h-2 rounded-full bg-sg-error shadow-[0_0_8px_#ffb4ab]"></div>
              <span className="text-xs font-medium text-sg-error tracking-wider">DISCONNECTED</span>
            </>
          )}
        </div>
      </div>

      {/* Row 1: Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <MetricCard 
          title="Avg Altitude" 
          value={avgAltitude} 
          suffix="m" 
          icon="altitude" 
        />
        <MetricCard 
          title="Avg Speed" 
          value={avgSpeed} 
          suffix="m/s" 
          icon="speed" 
        />
        <MetricCard 
          title="Total Packets" 
          value={telemetry.length.toString()} 
          icon="inventory_2" 
        />
      </div>

      {/* Row 2: Active Swarm Data Table */}
      <GlassCard title="Active Swarm · Real-Time Feed" className="overflow-hidden">
        {activeDrones.length === 0 ? (
          <div className="p-8 text-center text-sg-text-muted font-mono text-sm">
            Awaiting telemetry stream... Ensure Dataset Replayer is running.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-white/5 bg-white/[0.02]">
                  <th className="p-3 text-xs font-medium text-sg-text-dim uppercase tracking-wider">Drone ID</th>
                  <th className="p-3 text-xs font-medium text-sg-text-dim uppercase tracking-wider">Altitude (m)</th>
                  <th className="p-3 text-xs font-medium text-sg-text-dim uppercase tracking-wider">Speed (m/s)</th>
                  <th className="p-3 text-xs font-medium text-sg-text-dim uppercase tracking-wider">Lat / Lng</th>
                  <th className="p-3 text-xs font-medium text-sg-text-dim uppercase tracking-wider">Battery (%)</th>
                  <th className="p-3 text-xs font-medium text-sg-text-dim uppercase tracking-wider">Status</th>
                </tr>
              </thead>
              <tbody>
                {activeDrones.map((drone, idx) => (
                  <tr key={drone.drone_id} className={`border-b border-white/5 hover:bg-white/5 transition-colors ${idx % 2 === 0 ? 'bg-transparent' : 'bg-white/[0.01]'}`}>
                    <td className="p-3 font-mono text-sm text-sg-primary">{drone.drone_id}</td>
                    <td className="p-3 font-mono text-sm text-sg-text">{drone.altitude.toFixed(1)}</td>
                    <td className="p-3 font-mono text-sm text-sg-text">{drone.speed.toFixed(1)}</td>
                    <td className="p-3 font-mono text-sm text-sg-text-muted">{drone.latitude.toFixed(4)}, {drone.longitude.toFixed(4)}</td>
                    <td className="p-3">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-sm text-sg-text w-8">{drone.battery_level}%</span>
                        <div className="h-1.5 w-16 bg-white/10 rounded-full overflow-hidden">
                          <div 
                            className={`h-full ${drone.battery_level > 60 ? 'bg-green-500' : drone.battery_level > 30 ? 'bg-sg-amber' : 'bg-sg-error'}`}
                            style={{ width: `${drone.battery_level}%` }}
                          />
                        </div>
                      </div>
                    </td>
                    <td className="p-3">
                      <span className={`px-2 py-0.5 rounded text-xs font-mono font-medium ${drone.battery_level > 50 ? 'bg-green-500/20 text-green-400' : drone.battery_level > 20 ? 'bg-sg-amber/20 text-sg-amber' : 'bg-sg-error/20 text-sg-error'}`}>
                        {drone.battery_level > 50 ? 'NOMINAL' : drone.battery_level > 20 ? 'WARNING' : 'CRITICAL'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>

      {/* Row 3: WebSocket Alert Feed */}
      <GlassCard title="Anomaly Alert Feed">
        <div className="flex flex-col gap-2 max-h-64 overflow-y-auto pr-2 custom-scrollbar">
          {alerts.length === 0 ? (
            <div className="p-4 text-center text-sg-text-muted text-sm font-mono flex items-center justify-center gap-2">
              <span className="material-symbols-outlined text-green-400">check_circle</span>
              No anomalies detected. System operating normally.
            </div>
          ) : (
            alerts.slice(-10).reverse().map((alert, i) => (
              <div key={i} className="flex items-center gap-4 p-3 rounded bg-white/5 border border-white/5 hover:bg-white/10 transition-colors">
                <SeverityBadge severity={alert.severity || "HIGH"} />
                <div className="flex-1 font-inter text-sm text-sg-text">
                  <span className="text-sg-primary font-medium">{alert.attack_type || alert.type}</span> detected
                  <span className="text-sg-text-muted ml-2 font-mono text-xs">Score: {(alert.anomaly_score * 100).toFixed(0)}%</span>
                </div>
                <div className="text-xs text-sg-text-dim font-mono">
                  {new Date(alert.timestamp).toLocaleTimeString()}
                </div>
              </div>
            ))
          )}
        </div>
      </GlassCard>
    </div>
  );
}
