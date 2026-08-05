import { useQuery } from "@tanstack/react-query";
import { api, type Incident } from "@/services/api";
import { GlassCard } from "@/components/shared/GlassCard";
import { SeverityBadge } from "@/components/shared/SeverityBadge";
import { MetricCard } from "@/components/shared/MetricCard";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { PieChart, Pie, Cell, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import { SEVERITY_COLORS } from "@/lib/constants";

export default function ThreatsPage() {
  const { data: incidents = [], isLoading } = useQuery({
    queryKey: ['incidents-threats'],
    queryFn: () => api.getIncidents(),
    refetchInterval: 30000,
  });

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <LoadingSpinner />
      </div>
    );
  }

  // Calculate stats
  const totalEvents = incidents.length;
  const criticalThreats = incidents.filter(i => i.severity === 'CRITICAL').length;
  
  // Most common attack
  const attackCounts: Record<string, number> = {};
  incidents.forEach(i => {
    attackCounts[i.attack_type] = (attackCounts[i.attack_type] || 0) + 1;
  });
  let mostCommonAttack = "None";
  let maxCount = 0;
  Object.entries(attackCounts).forEach(([attack, count]) => {
    if (count > maxCount) {
      mostCommonAttack = attack;
      maxCount = count;
    }
  });

  const avgThreatScore = totalEvents > 0
    ? (incidents.reduce((sum, i) => sum + i.threat_level, 0) / totalEvents).toFixed(2)
    : "0";

  // Chart Data: Threat Distribution
  const pieData = Object.entries(attackCounts).map(([name, value]) => ({ name, value }));
  const PIE_COLORS = ['#00d9ff', '#ffb4ab', '#ffdeaa', '#b4c5ff', '#4ade80'];

  // Chart Data: Weekly Trend (Filtered to last 7 days)
  const now = new Date();
  const sevenDaysAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
  const recentIncidents = incidents.filter(i => new Date(i.created_at) >= sevenDaysAgo);
  
  const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const dayCounts = Array(7).fill(0);
  recentIncidents.forEach(i => {
    const d = new Date(i.created_at).getDay();
    dayCounts[d]++;
  });
  const barData = days.map((day, i) => ({ name: day, count: dayCounts[i] }));

  return (
    <div className="flex flex-col gap-6 p-6">
      {/* Page Header */}
      <div>
        <h1 className="text-2xl font-bold text-sg-text font-inter">Threat Intelligence Hub</h1>
        <p className="text-sm text-sg-text-muted mt-1">AI-powered threat analysis and correlation</p>
      </div>

      {/* Row 1: Stat Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <MetricCard title="Total Events" value={totalEvents.toString()} icon="security" />
        <MetricCard title="Critical Threats" value={criticalThreats.toString()} icon="warning" />
        <MetricCard title="Most Common Attack" value={mostCommonAttack} icon="troubleshoot" />
        <MetricCard title="Avg Threat Score" value={avgThreatScore} icon="monitoring" />
      </div>

      {/* Row 2: Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <GlassCard title="Threat Distribution" className="h-[300px] flex flex-col">
          {totalEvents === 0 ? (
            <div className="flex-1 flex items-center justify-center text-sg-text-muted text-sm">No data available</div>
          ) : (
            <div className="flex-1 min-h-0 relative">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={pieData}
                    cx="50%"
                    cy="50%"
                    innerRadius={60}
                    outerRadius={80}
                    paddingAngle={2}
                    dataKey="value"
                  >
                    {pieData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={PIE_COLORS[index % PIE_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip 
                    contentStyle={{ backgroundColor: '#1a2123', borderColor: 'rgba(255,255,255,0.1)', borderRadius: '4px' }}
                    itemStyle={{ color: '#dde4e6' }}
                  />
                </PieChart>
              </ResponsiveContainer>
              <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                <span className="text-2xl font-bold font-mono text-sg-text">{totalEvents}</span>
                <span className="text-[10px] uppercase text-sg-text-muted tracking-wider">Total</span>
              </div>
            </div>
          )}
        </GlassCard>

        <GlassCard title="Weekly Trend" className="h-[300px] flex flex-col">
           {totalEvents === 0 ? (
            <div className="flex-1 flex items-center justify-center text-sg-text-muted text-sm">No data available</div>
          ) : (
            <div className="flex-1 min-h-0">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={barData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <XAxis dataKey="name" stroke="#859398" fontSize={10} tickLine={false} axisLine={false} />
                  <YAxis stroke="#859398" fontSize={10} tickLine={false} axisLine={false} />
                  <Tooltip 
                    cursor={{ fill: 'rgba(255,255,255,0.05)' }}
                    contentStyle={{ backgroundColor: '#1a2123', borderColor: 'rgba(255,255,255,0.1)', borderRadius: '4px' }}
                  />
                  <Bar dataKey="count" radius={[2, 2, 0, 0]}>
                    {barData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill="url(#colorCyan)" />
                    ))}
                  </Bar>
                  <defs>
                    <linearGradient id="colorCyan" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#00d9ff" stopOpacity={1}/>
                      <stop offset="100%" stopColor="#005b6c" stopOpacity={1}/>
                    </linearGradient>
                  </defs>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </GlassCard>
      </div>

      {/* Row 3: Active Intelligence Feed */}
      <GlassCard title="Active Intelligence Feed">
        <div className="flex flex-col gap-3">
          {incidents.length === 0 ? (
            <div className="p-6 text-center text-sg-text-muted text-sm font-mono flex items-center justify-center gap-2">
              <span className="material-symbols-outlined text-green-400">shield</span>
              No active threats. Perimeter secure.
            </div>
          ) : (
            incidents.slice(0, 8).map(incident => {
               // Determine border color based on severity
               let borderColorClass = 'border-l-sg-text-dim';
               if (incident.severity === 'CRITICAL') borderColorClass = 'border-l-sg-error';
               else if (incident.severity === 'HIGH') borderColorClass = 'border-l-sg-amber';
               else if (incident.severity === 'MEDIUM') borderColorClass = 'border-l-blue-400';
               else if (incident.severity === 'LOW') borderColorClass = 'border-l-green-400';

               return (
                <div key={incident.id} className={`flex items-start gap-4 p-4 rounded bg-white/[0.02] border border-white/5 border-l-4 ${borderColorClass} hover:bg-white/5 transition-colors`}>
                  <div className="mt-1">
                    <SeverityBadge severity={incident.severity} />
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center justify-between mb-1">
                      <h4 className="text-sm font-medium text-sg-text">{incident.attack_type}</h4>
                      <span className="text-xs font-mono text-sg-text-dim">{new Date(incident.created_at).toLocaleString()}</span>
                    </div>
                    <div className="text-xs text-sg-text-muted mb-2">Target: <span className="font-mono text-sg-primary">{incident.drone_id}</span></div>
                    <p className="text-xs text-sg-text-muted leading-relaxed">
                      {incident.explanation || "No explanation provided for this event."}
                    </p>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </GlassCard>
    </div>
  );
}
