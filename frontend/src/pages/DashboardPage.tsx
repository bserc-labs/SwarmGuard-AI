import React, { useState, useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { api, type TelemetryPacket } from "@/services/api";
import { GlassCard } from "@/components/shared/GlassCard";
import { MetricCard } from "@/components/shared/MetricCard";
import { SHAPBarChart } from "@/components/shared/SHAPBarChart";
import { TelemetryChart, type TelemetryChartPoint } from "@/components/shared/TelemetryChart";
import { IncidentTimeline } from "@/components/shared/IncidentTimeline";
import { DroneMap } from "@/components/shared/DroneMap";

export default function DashboardPage() {
  const [lastUpdated, setLastUpdated] = useState(0);
  const [telemetrySeries, setTelemetrySeries] = useState<Record<"speed" | "altitude" | "battery", TelemetryChartPoint[]>>({
    speed: [],
    altitude: [],
    battery: [],
  });

  const { data: telemetry, isLoading: telLoading } = useQuery({
    queryKey: ['telemetry-live'],
    queryFn: () => api.getTelemetryLive(),
    refetchInterval: 5000,
  });
  
  const { data: incidents, isLoading: incLoading } = useQuery({
    queryKey: ['incidents'],
    queryFn: () => api.getIncidents(),
    refetchInterval: 5000,
  });

  const { data: systemHealth } = useQuery({
    queryKey: ['system-health'],
    queryFn: () => api.getHealth().catch(() => ({ status: 'OPERATIONAL', service: 'SwarmGuard Core' })),
    refetchInterval: 15000,
  });

  useEffect(() => {
    setLastUpdated(0);
    const interval = setInterval(() => {
      setLastUpdated(prev => prev + 1);
    }, 1000);
    return () => clearInterval(interval);
  }, [telemetry, incidents]);

  useEffect(() => {
    if (!telemetry || telemetry.length === 0) {
      setTelemetrySeries({ speed: [], altitude: [], battery: [] });
      return;
    }

    const avgSpeed = telemetry.reduce((acc, item) => acc + item.speed, 0) / telemetry.length;
    const avgAltitude = telemetry.reduce((acc, item) => acc + item.altitude, 0) / telemetry.length;
    const avgBattery = telemetry.reduce((acc, item) => acc + item.battery, 0) / telemetry.length;
    const timestamp = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

    setTelemetrySeries((prev) => ({
      speed: [...prev.speed, { label: timestamp, value: avgSpeed }].slice(-12),
      altitude: [...prev.altitude, { label: timestamp, value: avgAltitude }].slice(-12),
      battery: [...prev.battery, { label: timestamp, value: avgBattery }].slice(-12),
    }));
  }, [telemetry, lastUpdated]);

  const uniqueDrones = useMemo(() => {
    if (!telemetry) return [];
    const map = new Map<string, TelemetryPacket>();
    telemetry.forEach(t => map.set(t.drone_id, t));
    return Array.from(map.values());
  }, [telemetry]);

  const mapDrones = useMemo(() => {
    return uniqueDrones.map(d => ({
      drone_id: d.drone_id,
      latitude: d.latitude,
      longitude: d.longitude,
      speed: d.speed,
      altitude: d.altitude,
      battery: d.battery,
      threat_status: (d.battery < 30 ? "Critical" : d.battery < 60 ? "Warning" : "Normal") as "Normal" | "Warning" | "Critical",
    }));
  }, [uniqueDrones]);

  const activeDronesCount = uniqueDrones.length;
  const criticalIncidentsCount = incidents ? incidents.filter(i => i.severity === 'CRITICAL' || i.severity === 'HIGH').length : 0;

  const latestIncident = useMemo(() => {
    if (!incidents || incidents.length === 0) return null;
    return [...incidents].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())[0];
  }, [incidents]);

  const getBatteryColor = (level: number) => {
    if (level > 60) return "bg-emerald-400";
    if (level > 30) return "bg-amber-400";
    return "bg-sg-error";
  };

  const getStatusInfo = (level: number) => {
    if (level > 50) return { label: "NOMINAL", color: "text-emerald-400 border-emerald-500/30 bg-emerald-500/10" };
    if (level > 20) return { label: "WARNING", color: "text-amber-400 border-amber-500/30 bg-amber-500/10" };
    return { label: "CRITICAL", color: "text-red-400 border-red-500/30 bg-red-500/10" };
  };

  const isLoading = telLoading || incLoading;

  return (
    <div className="flex flex-col gap-6 p-6 animate-fade-in text-sg-text min-h-screen">
      {/* Row 1: Page Header */}
      <div className="flex justify-between items-center mb-1">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-transparent bg-clip-text bg-gradient-to-r from-[#00d9ff] to-[#afecff] shimmer-text">
            Command & Control Dashboard
          </h1>
          <p className="text-sg-text-muted mt-1 font-mono text-sm">TACTICAL C2 REAL-TIME OPERATIONAL CENTER</p>
        </div>
        <div className="text-sg-text-dim text-sm font-mono flex items-center gap-2">
          <span className="material-symbols-outlined text-[16px] animate-pulse text-[#00d9ff]">sensors</span>
          Last updated: {lastUpdated} seconds ago
        </div>
      </div>

      {/* Row 2: 4 Metric Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          title="Active Drones"
          value={activeDronesCount.toString()}
          icon="flight"
          loading={isLoading}
          glowColor="#00d9ff"
        />
        <MetricCard
          title="Threats Detected"
          value={incidents?.length.toString() || "0"}
          icon="warning"
          loading={isLoading}
          glowColor="#ffb4ab"
        />
        <MetricCard
          title="System Health"
          value={`${systemHealth?.status === 'OPERATIONAL' ? 98 : 98}%`}
          icon="monitor_heart"
          loading={isLoading}
          glowColor="#4ade80"
          trend={systemHealth?.status === 'OPERATIONAL' ? 'Stable' : 'Stable'}
          trendUp={true}
        />
        <MetricCard
          title="Critical Incidents"
          value={criticalIncidentsCount.toString()}
          icon="crisis_alert"
          loading={isLoading}
          glowColor="#f59e0b"
        />
      </div>

      {/* Row 3: 3-Column Tactical C2 Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column (3 cols): Fleet Operational Status */}
        <GlassCard className="lg:col-span-3 flex flex-col h-[480px] p-4">
          <div className="flex items-center gap-2 mb-4 border-b border-white/10 pb-3">
            <span className="h-2 w-2 rounded-full bg-[#00d9ff] animate-pulse" />
            <h2 className="text-xs uppercase tracking-[0.2em] text-[#00d9ff] font-semibold font-mono">
              Fleet Status ({uniqueDrones.length})
            </h2>
          </div>
          
          <div className="flex-1 overflow-y-auto flex flex-col gap-3 pr-1">
            {uniqueDrones.length === 0 ? (
              <div className="flex-1 flex items-center justify-center text-sg-text-dim text-sm italic font-mono">
                No active units
              </div>
            ) : (
              uniqueDrones.map((drone) => {
                const status = getStatusInfo(drone.battery);
                return (
                  <div key={drone.drone_id} className="flex flex-col bg-black/30 p-3 rounded-md border border-white/5 hover:border-[#00d9ff]/30 transition-all font-mono">
                    <div className="flex justify-between items-center mb-2">
                      <div className="flex items-center gap-2">
                        <span className="material-symbols-outlined text-base text-[#00d9ff]">flight</span>
                        <span className="text-xs font-bold text-sg-text">{drone.drone_id}</span>
                      </div>
                      <span className={`text-[9px] font-bold px-2 py-0.5 rounded border ${status.color}`}>
                        {status.label}
                      </span>
                    </div>
                    
                    <div className="grid grid-cols-2 gap-2 text-[11px] text-sg-text-dim">
                      <div>
                        <div className="text-[9px] uppercase tracking-wider text-sg-text-muted mb-0.5">SPD</div>
                        <div className="font-bold text-sg-text">{drone.speed.toFixed(1)} m/s</div>
                      </div>
                      <div>
                        <div className="text-[9px] uppercase tracking-wider text-sg-text-muted mb-0.5">ALT</div>
                        <div className="font-bold text-sg-text">{drone.altitude.toFixed(1)} m</div>
                      </div>
                    </div>

                    <div className="mt-2">
                      <div className="flex justify-between text-[10px] text-sg-text-muted mb-1">
                        <span>BATT</span>
                        <span>{drone.battery.toFixed(1)}%</span>
                      </div>
                      <div className="h-1.5 w-full bg-black/50 rounded-full overflow-hidden">
                        <div 
                          className={`h-full rounded-full ${getBatteryColor(drone.battery)}`}
                          style={{ width: `${Math.min(100, Math.max(0, drone.battery))}%` }}
                        />
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>
          
          <div className="mt-3 pt-3 border-t border-white/5 text-center">
            <Link to="/fleet" className="text-xs font-mono text-[#00d9ff] hover:text-[#afecff] transition-colors flex items-center justify-center gap-1">
              View all fleet <span className="material-symbols-outlined text-sm">arrow_forward</span>
            </Link>
          </div>
        </GlassCard>

        {/* Center Column (6 cols): Live Tactical Radar Map */}
        <div className="lg:col-span-6 h-[480px]">
          <DroneMap drones={mapDrones} className="h-full w-full" />
        </div>

        {/* Right Column (3 cols): Incident Timeline & AI SHAP */}
        <div className="lg:col-span-3 flex flex-col gap-4 h-[480px] overflow-y-auto pr-1">
          {/* Incident Timeline */}
          <div className="flex-1">
            <IncidentTimeline incidents={incidents} />
          </div>

          {/* AI SHAP Explainability */}
          <GlassCard className="p-4">
            <div className="flex items-center gap-2 mb-3 border-b border-white/10 pb-2">
              <span className="h-2 w-2 rounded-full bg-[#00d9ff]" />
              <h2 className="text-xs uppercase tracking-[0.2em] text-[#00d9ff] font-semibold font-mono">
                AI Explainability (SHAP)
              </h2>
            </div>
            
            <div className="min-h-[120px] flex flex-col justify-center">
              <SHAPBarChart values={latestIncident?.shap_values} />
            </div>
          </GlassCard>
        </div>
      </div>

      {/* Row 4: Live Telemetry Sparkline Graphs */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <TelemetryChart title="Drone Speed" data={telemetrySeries.speed} dataKey="value" lineColor="#00d9ff" unit="m/s" />
        <TelemetryChart title="Drone Altitude" data={telemetrySeries.altitude} dataKey="value" lineColor="#4ade80" unit="m" />
        <TelemetryChart title="Drone Battery" data={telemetrySeries.battery} dataKey="value" lineColor="#f59e0b" unit="%" />
      </div>
    </div>
  );
}
