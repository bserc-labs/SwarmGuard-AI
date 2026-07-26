import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Incident } from "@/services/api";
import { GlassCard } from "@/components/shared/GlassCard";
import { SeverityBadge } from "@/components/shared/SeverityBadge";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { Link } from "@tanstack/react-router";

export default function IncidentsPage() {
  const [activeSeverity, setActiveSeverity] = useState<string>("All");
  const [incidentStatuses, setIncidentStatuses] = useState<Record<number, string>>({});
  const [actionLoading, setActionLoading] = useState<Record<number, boolean>>({});
  const [actionError, setActionError] = useState<Record<number, string>>({});
  const queryClient = useQueryClient();

  const { data: incidents = [], isLoading } = useQuery({
    queryKey: ['incidents', activeSeverity],
    queryFn: () => api.getIncidents(activeSeverity !== "All" ? activeSeverity : undefined),
    refetchInterval: 30000,
  });

  const severities = ["All", "CRITICAL", "HIGH", "MEDIUM", "LOW"];

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <LoadingSpinner />
      </div>
    );
  }

  const criticalCount = incidents.filter(i => i.severity === "CRITICAL").length;
  const avgThreat = incidents.length > 0 
    ? (incidents.reduce((sum, i) => sum + i.threat_level, 0) / incidents.length).toFixed(1)
    : "0";

  const handleIncidentAction = async (incident: Incident, status: string) => {
    setActionLoading((prev) => ({ ...prev, [incident.id]: true }));
    setActionError((prev) => ({ ...prev, [incident.id]: "" }));

    try {
      setIncidentStatuses((prev) => ({ ...prev, [incident.id]: status }));
      await queryClient.invalidateQueries({ queryKey: ["incidents"] });
    } catch (error) {
      setActionError((prev) => ({
        ...prev,
        [incident.id]: error instanceof Error ? error.message : "Unable to update incident status.",
      }));
    } finally {
      setActionLoading((prev) => ({ ...prev, [incident.id]: false }));
    }
  };

  const handleExportReport = () => {
    const rows = [
      ["ID", "Drone", "Attack Type", "Severity", "Threat Level", "Time", "Status"],
      ...incidents.map((incident) => [
        `#SG-${incident.id.toString().padStart(4, "0")}`,
        incident.drone_id,
        incident.attack_type,
        incident.severity,
        String(incident.threat_level),
        new Date(incident.created_at).toISOString(),
        incidentStatuses[incident.id] || "Pending",
      ]),
    ];

    const csv = rows
      .map((row) => row.map((value) => `"${String(value).replace(/"/g, '""')}"`).join(","))
      .join("\n");

    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `swarmguard-incidents-${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="flex flex-col gap-6 p-6">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-sg-text font-inter">Incident Command Center</h1>
        <button
          onClick={handleExportReport}
          disabled={incidents.length === 0}
          className="flex items-center gap-2 px-4 py-2 rounded bg-sg-surface border border-white/10 hover:bg-white/10 transition-colors text-sg-text-muted text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <span className="material-symbols-outlined text-[18px]">download</span>
          Export Report
        </button>
      </div>

      {/* Filter Bar */}
      <div className="flex gap-2">
        {severities.map(sev => (
          <button
            key={sev}
            onClick={() => setActiveSeverity(sev)}
            className={`px-4 py-1.5 rounded-full text-xs font-medium tracking-wide transition-colors border ${
              activeSeverity === sev
                ? 'bg-sg-primary/20 text-sg-primary border-sg-primary/30'
                : 'bg-white/5 text-sg-text-muted border-transparent hover:bg-white/10'
            }`}
          >
            {sev}
          </button>
        ))}
      </div>

      {/* Incident Table */}
      <GlassCard className="p-0 overflow-hidden">
        {incidents.length === 0 ? (
          <div className="p-16 flex flex-col items-center justify-center gap-4 text-sg-text-muted">
            <span className="material-symbols-outlined text-4xl opacity-50">shield</span>
            <p className="font-mono text-sm">No incidents match the selected criteria.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-white/5 bg-white/[0.02]">
                  <th className="p-4 text-[10px] font-medium text-sg-text-dim uppercase tracking-wider">ID</th>
                  <th className="p-4 text-[10px] font-medium text-sg-text-dim uppercase tracking-wider">Drone</th>
                  <th className="p-4 text-[10px] font-medium text-sg-text-dim uppercase tracking-wider">Attack Type</th>
                  <th className="p-4 text-[10px] font-medium text-sg-text-dim uppercase tracking-wider">Severity</th>
                  <th className="p-4 text-[10px] font-medium text-sg-text-dim uppercase tracking-wider">Threat Level</th>
                  <th className="p-4 text-[10px] font-medium text-sg-text-dim uppercase tracking-wider">Status</th>
                  <th className="p-4 text-[10px] font-medium text-sg-text-dim uppercase tracking-wider">Time</th>
                  <th className="p-4 text-[10px] font-medium text-sg-text-dim uppercase tracking-wider">Actions</th>
                </tr>
              </thead>
              <tbody>
                {incidents.map((incident) => (
                  <tr key={incident.id} className="border-b border-white/5 hover:bg-white/5 transition-colors">
                    <td className="p-4 font-mono text-xs text-sg-text-muted">#SG-{incident.id.toString().padStart(4, '0')}</td>
                    <td className="p-4 font-mono text-sm text-sg-primary">{incident.drone_id}</td>
                    <td className="p-4 text-sm text-sg-text">{incident.attack_type}</td>
                    <td className="p-4"><SeverityBadge severity={incident.severity} /></td>
                    <td className="p-4">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-xs text-sg-text-muted w-6">{incident.threat_level}</span>
                        <div className="h-1.5 w-16 bg-white/10 rounded-full overflow-hidden">
                          <div 
                            className="h-full bg-sg-error"
                            style={{ width: `${Math.min(100, incident.threat_level)}%` }}
                          />
                        </div>
                      </div>
                    </td>
                    <td className="p-4 font-mono text-xs text-sg-text-dim">
                      {incidentStatuses[incident.id] || "Pending"}
                    </td>
                    <td className="p-4 font-mono text-xs text-sg-text-dim">
                      {new Date(incident.created_at).toLocaleString()}
                    </td>
                    <td className="p-4">
                      <div className="flex flex-col gap-2">
                        <div className="flex gap-2">
                          <button
                            onClick={() => handleIncidentAction(incident, "ACKNOWLEDGED")}
                            disabled={Boolean(actionLoading[incident.id])}
                            className="rounded border border-sg-primary/30 bg-sg-primary/10 px-2 py-1 text-[10px] font-medium uppercase tracking-wide text-sg-primary transition-colors hover:bg-sg-primary/20 disabled:opacity-50"
                          >
                            {actionLoading[incident.id] ? "Working..." : "Acknowledge"}
                          </button>
                          <button
                            onClick={() => handleIncidentAction(incident, "RESOLVED")}
                            disabled={Boolean(actionLoading[incident.id])}
                            className="rounded border border-emerald-500/30 bg-emerald-500/10 px-2 py-1 text-[10px] font-medium uppercase tracking-wide text-emerald-300 transition-colors hover:bg-emerald-500/20 disabled:opacity-50"
                          >
                            {actionLoading[incident.id] ? "Working..." : "Resolve"}
                          </button>
                        </div>
                        <Link
                          to="/incidents/$id"
                          params={{ id: incident.id.toString() }}
                          className="text-xs font-medium text-sg-primary hover:text-sg-primary-soft transition-colors hover:underline"
                        >
                          View
                        </Link>
                        {actionError[incident.id] ? (
                          <p className="text-[10px] text-sg-error">{actionError[incident.id]}</p>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="border-t border-white/5 p-4 flex items-center justify-between bg-white/[0.01]">
          <div className="flex gap-6 text-sm">
            <span className="text-sg-text-muted">Total: <span className="text-sg-text font-mono ml-1">{incidents.length}</span></span>
            <span className="text-sg-text-muted">Critical: <span className="text-sg-error font-mono ml-1">{criticalCount}</span></span>
            <span className="text-sg-text-muted">Avg Threat: <span className="text-sg-text font-mono ml-1">{avgThreat}</span></span>
          </div>
        </div>
      </GlassCard>
    </div>
  );
}
