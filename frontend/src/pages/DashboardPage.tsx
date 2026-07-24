import React, { useState, useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { api, type TelemetryPacket, type Incident } from "@/services/api";
import { GlassCard } from "@/components/shared/GlassCard";
import { MetricCard } from "@/components/shared/MetricCard";
import { SeverityBadge } from "@/components/shared/SeverityBadge";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";

export default function DashboardPage() {
  const [lastUpdated, setLastUpdated] = useState(0);

  const { data: telemetry, isLoading: telLoading } = useQuery({
    queryKey: ['telemetry-live'],
    queryFn: () => api.getTelemetryLive(),
    refetchInterval: 30000,
  });
  
  const { data: incidents, isLoading: incLoading } = useQuery({
    queryKey: ['incidents'],
    queryFn: () => api.getIncidents(),
    refetchInterval: 30000,
  });

  useEffect(() => {
    setLastUpdated(0);
    const interval = setInterval(() => {
      setLastUpdated(prev => prev + 1);
    }, 1000);
    return () => clearInterval(interval);
  }, [telemetry, incidents]);

  const uniqueDrones = useMemo(() => {
    if (!telemetry) return [];
    const map = new Map<string, TelemetryPacket>();
    telemetry.forEach(t => map.set(t.drone_id, t));
    return Array.from(map.values());
  }, [telemetry]);

  const activeDronesCount = uniqueDrones.length;
  const criticalIncidentsCount = incidents ? incidents.filter(i => i.severity === 'CRITICAL' || i.severity === 'HIGH').length : 0;
  const avgBattery = uniqueDrones.length > 0 ? uniqueDrones.reduce((acc, d) => acc + d.battery, 0) / uniqueDrones.length : 0;

  const chartData = useMemo(() => {
    if (!incidents || incidents.length === 0) return [];
    const hourly = new Array(24).fill(0);
    incidents.forEach(inc => {
      const date = new Date(inc.created_at);
      const hour = date.getHours();
      hourly[hour]++;
    });
    return hourly.map((count, hour) => ({
      time: `${hour.toString().padStart(2, '0')}:00`,
      count
    }));
  }, [incidents]);

  const latestIncident = useMemo(() => {
    if (!incidents || incidents.length === 0) return null;
    return [...incidents].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())[0];
  }, [incidents]);

  const getBatteryColor = (level: number) => {
    if (level > 60) return "bg-green-400";
    if (level > 30) return "bg-amber-400";
    return "bg-sg-error";
  };

  const getStatusInfo = (level: number) => {
    if (level > 50) return { label: "NOMINAL", color: "text-green-400 border-green-400" };
    if (level > 20) return { label: "WARNING", color: "text-amber-400 border-amber-400" };
    return { label: "CRITICAL", color: "text-sg-error border-sg-error" };
  };

  const isLoading = telLoading || incLoading;

  return (
    <div className="flex flex-col gap-6 p-6 animate-fade-in text-sg-text min-h-screen">
      {/* Row 1: Page Header */}
      <div className="flex justify-between items-center mb-2">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-transparent bg-clip-text bg-gradient-to-r from-sg-primary to-sg-primary-soft shimmer-text">
            Command Dashboard
          </h1>
          <p className="text-sg-text-muted mt-1 font-mono text-sm">Real-time operational overview</p>
        </div>
        <div className="text-sg-text-dim text-sm font-mono flex items-center gap-2">
          <span className="material-symbols-outlined text-[16px] animate-pulse text-sg-primary">sensors</span>
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
          value="98%"
          icon="monitor_heart"
          loading={isLoading}
          glowColor="#4ade80"
          trend="Stable"
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

      {/* Row 3: Two-column layout */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column: Threat Analysis Timeline */}
        <GlassCard className="col-span-1 lg:col-span-2 flex flex-col">
          <div className="flex items-center gap-2 mb-6">
            <div className="w-2 h-2 rounded-full bg-sg-primary animate-pulse"></div>
            <h2 className="text-sm uppercase tracking-widest text-sg-text-muted font-semibold">Threat Analysis · Last 24 Hours</h2>
          </div>
          
          <div className="flex-1 min-h-[250px] relative">
            {chartData.length > 0 && chartData.some(d => d.count > 0) ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <XAxis dataKey="time" stroke="#859398" fontSize={12} tickLine={false} axisLine={false} />
                  <YAxis stroke="#859398" fontSize={12} tickLine={false} axisLine={false} allowDecimals={false} />
                  <Tooltip 
                    cursor={{ fill: 'rgba(255,255,255,0.05)' }}
                    contentStyle={{ backgroundColor: 'rgba(14,20,23,0.9)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', color: '#dde4e6' }}
                  />
                  <Bar dataKey="count" fill="#00d9ff" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="absolute inset-0 flex flex-col items-center justify-center text-sg-text-dim">
                <span className="material-symbols-outlined text-4xl mb-2 opacity-50">security</span>
                <p>No threats detected in the last 24 hours</p>
              </div>
            )}
          </div>
        </GlassCard>

        {/* Right Column: Fleet Status */}
        <GlassCard className="flex flex-col">
          <div className="flex items-center gap-2 mb-4">
            <div className="w-2 h-2 rounded-full bg-sg-primary"></div>
            <h2 className="text-sm uppercase tracking-widest text-sg-text-muted font-semibold">Fleet Operational Status</h2>
          </div>
          
          <div className="flex-1 flex flex-col gap-3">
            {uniqueDrones.length === 0 ? (
               <div className="flex-1 flex items-center justify-center text-sg-text-dim text-sm italic">
                 No drones active
               </div>
            ) : (
              uniqueDrones.slice(0, 6).map((drone) => {
                const status = getStatusInfo(drone.battery);
                return (
                  <div key={drone.drone_id} className="flex flex-col bg-sg-surface-dim p-3 rounded-md border border-white/5">
                    <div className="flex justify-between items-center mb-2">
                      <div className="flex items-center gap-2">
                        <span className="material-symbols-outlined text-lg text-sg-text-muted">flight</span>
                        <span className="font-mono text-sm font-semibold">{drone.drone_id}</span>
                      </div>
                      <span className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded-full border ${status.color}`}>
                        {status.label}
                      </span>
                    </div>
                    <div className="flex items-center gap-3">
                      <div className="flex-1">
                        <div className="flex justify-between text-[11px] text-sg-text-muted mb-1 font-mono">
                          <span>BATTERY</span>
                          <span>{drone.battery.toFixed(1)}%</span>
                        </div>
                        <div className="h-1.5 w-full bg-black/50 rounded-full overflow-hidden">
                          <div 
                            className={`h-full rounded-full ${getBatteryColor(drone.battery)}`}
                            style={{ width: `${Math.min(100, Math.max(0, drone.battery))}%` }}
                          ></div>
                        </div>
                      </div>
                      <div className="w-16 text-right">
                        <div className="text-[10px] text-sg-text-dim font-mono mb-0.5">SPD (m/s)</div>
                        <div className="text-sm font-mono text-sg-primary">{drone.speed.toFixed(1)}</div>
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>
          <div className="mt-4 pt-3 border-t border-white/5 text-center">
            <Link to="/fleet" className="text-xs font-mono text-sg-primary hover:text-sg-primary-soft transition-colors flex items-center justify-center gap-1">
              View all fleet <span className="material-symbols-outlined text-sm">arrow_forward</span>
            </Link>
          </div>
        </GlassCard>
      </div>

      {/* Row 4: Two-column layout */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Left: AI Explainability (SHAP) */}
        <GlassCard>
          <div className="flex items-center gap-2 mb-6">
            <div className="w-2 h-2 rounded-full bg-sg-primary"></div>
            <h2 className="text-sm uppercase tracking-widest text-sg-text-muted font-semibold">AI Explainability · SHAP Analysis</h2>
          </div>
          
          <div className="min-h-[160px] flex flex-col justify-center">
            {latestIncident?.shap_values && latestIncident.shap_values.length > 0 ? (
              <div className="flex flex-col gap-4">
                <div className="text-sm text-sg-text-muted mb-2 font-mono border-b border-white/5 pb-2">
                  Model explanation for latest incident: <span className="text-sg-primary">#{latestIncident.id}</span>
                </div>
                {latestIncident.shap_values.map((shap: any, idx: number) => (
                  <div key={idx} className="flex flex-col gap-1.5">
                    <div className="flex justify-between text-xs font-mono">
                      <span className="text-sg-text-dim uppercase">{shap.feature}</span>
                      <span className="text-sg-primary-soft">+{shap.value.toFixed(4)}</span>
                    </div>
                    <div className="h-1.5 w-full bg-black/50 rounded-full overflow-hidden">
                      <div 
                        className="h-full rounded-full bg-sg-primary opacity-80"
                        style={{ width: `${Math.min(100, Math.max(5, (shap.value / 0.5) * 100))}%` }}
                      ></div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="flex flex-col items-center text-sg-text-dim">
                <span className="material-symbols-outlined text-4xl mb-3 opacity-30">psychology</span>
                <p className="font-mono text-sm">Awaiting anomaly detection data...</p>
              </div>
            )}
          </div>
        </GlassCard>

        {/* Right: System Gauges */}
        <GlassCard>
          <div className="flex items-center gap-2 mb-6">
            <div className="w-2 h-2 rounded-full bg-sg-primary"></div>
            <h2 className="text-sm uppercase tracking-widest text-sg-text-muted font-semibold">System Telemetry</h2>
          </div>
          
          <div className="flex items-center justify-around py-4">
            {/* Battery Gauge */}
            <div className="flex flex-col items-center gap-3">
              <div className="relative w-32 h-32 flex items-center justify-center">
                <svg className="w-full h-full -rotate-90 transform" viewBox="0 0 100 100">
                  <circle cx="50" cy="50" r="40" fill="none" stroke="rgba(255,255,255,0.05)" strokeWidth="8" />
                  <circle 
                    cx="50" cy="50" r="40" fill="none" stroke="#00d9ff" strokeWidth="8"
                    strokeDasharray={`${2 * Math.PI * 40}`}
                    strokeDashoffset={`${2 * Math.PI * 40 * (1 - (avgBattery / 100))}`}
                    strokeLinecap="round"
                    className="transition-all duration-1000 ease-in-out"
                  />
                </svg>
                <div className="absolute inset-0 flex flex-col items-center justify-center">
                  <span className="text-2xl font-bold font-mono text-sg-text">{avgBattery.toFixed(0)}%</span>
                  <span className="text-[10px] text-sg-text-dim uppercase tracking-wider">Avg Batt</span>
                </div>
              </div>
            </div>
            
            {/* Signal Gauge */}
            <div className="flex flex-col items-center gap-3">
              <div className="relative w-32 h-32 flex items-center justify-center">
                <svg className="w-full h-full -rotate-90 transform" viewBox="0 0 100 100">
                  <circle cx="50" cy="50" r="40" fill="none" stroke="rgba(255,255,255,0.05)" strokeWidth="8" />
                  <circle 
                    cx="50" cy="50" r="40" fill="none" stroke="#4ade80" strokeWidth="8"
                    strokeDasharray={`${2 * Math.PI * 40}`}
                    strokeDashoffset={`${2 * Math.PI * 40 * (1 - 0.94)}`}
                    strokeLinecap="round"
                    className="transition-all duration-1000 ease-in-out"
                  />
                </svg>
                <div className="absolute inset-0 flex flex-col items-center justify-center">
                  <span className="text-2xl font-bold font-mono text-sg-text">94%</span>
                  <span className="text-[10px] text-sg-text-dim uppercase tracking-wider">Signal Str</span>
                </div>
              </div>
            </div>
          </div>
        </GlassCard>
      </div>
    </div>
  );
}
