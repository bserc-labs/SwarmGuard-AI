import { useMemo } from "react";
import { GlassCard } from "@/components/shared/GlassCard";
import { SeverityBadge } from "@/components/shared/SeverityBadge";
import type { Incident } from "@/services/api";

interface IncidentTimelineProps {
  incidents?: Incident[];
}

function getStatusMeta(incident: Incident) {
  const explanation = incident.explanation?.toLowerCase() ?? "";
  const severity = incident.severity?.toUpperCase() ?? "";

  if (explanation.includes("false") || explanation.includes("no anomaly") || explanation.includes("false positive")) {
    return {
      label: "False Positive",
      icon: "radio_button_unchecked",
      badgeClass: "border-slate-500/30 bg-slate-500/10 text-slate-300",
      iconClass: "text-slate-400",
    };
  }

  if (severity === "CRITICAL" || severity === "HIGH") {
    return {
      label: "Active",
      icon: "fiber_manual_record",
      badgeClass: "border-red-500/30 bg-red-500/10 text-red-300",
      iconClass: "text-red-400",
    };
  }

  return {
    label: "Resolved",
    icon: "check_circle",
    badgeClass: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
    iconClass: "text-emerald-400",
  };
}

function formatTimestamp(value?: string) {
  if (!value) return "Unknown time";

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "Unknown time";

  return parsed.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function IncidentTimeline({ incidents = [] }: IncidentTimelineProps) {
  const sortedIncidents = useMemo(() => {
    return [...incidents].sort((a, b) => {
      const first = new Date(a.created_at).getTime();
      const second = new Date(b.created_at).getTime();
      return second - first;
    });
  }, [incidents]);

  return (
    <GlassCard className="flex flex-col">
      <div className="flex flex-col gap-2 mb-5">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-sg-primary animate-pulse"></div>
          <h2 className="text-sm uppercase tracking-widest text-sg-text-muted font-semibold">Incident Timeline</h2>
        </div>
        <p className="text-sm text-sg-text-dim">Latest drone security events</p>
      </div>

      {sortedIncidents.length === 0 ? (
        <div className="flex min-h-[180px] items-center justify-center rounded-lg border border-dashed border-white/10 bg-sg-surface-dim/40 px-4 py-8 text-center text-sm text-sg-text-dim">
          No recent incidents
        </div>
      ) : (
        <div className="space-y-3">
          {sortedIncidents.slice(0, 8).map((incident) => {
            const status = getStatusMeta(incident);

            return (
              <div
                key={incident.id}
                className="rounded-lg border border-white/5 bg-sg-surface-dim/70 p-4 transition-colors hover:bg-white/[0.03]"
              >
                <div className="flex gap-3">
                  <span className={`mt-0.5 shrink-0 material-symbols-outlined text-lg ${status.iconClass}`}>
                    {status.icon}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-sm font-semibold text-sg-text">
                        {incident.attack_type || "Security incident"}
                      </h3>
                      <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-[0.2em] ${status.badgeClass}`}>
                        {status.label}
                      </span>
                    </div>

                    <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs font-mono text-sg-text-muted">
                      <span>
                        Drone <span className="text-sg-primary">{incident.drone_id}</span>
                      </span>
                      <span>
                        Threat <span className="text-sg-text">{incident.attack_type || "Unknown"}</span>
                      </span>
                    </div>

                    <div className="mt-3 flex flex-wrap items-center gap-2">
                      <SeverityBadge severity={incident.severity} size="sm" />
                      <span className="text-[11px] text-sg-text-dim">{formatTimestamp(incident.created_at)}</span>
                    </div>

                    {incident.explanation ? (
                      <p className="mt-3 text-sm leading-relaxed text-sg-text-muted">
                        {incident.explanation}
                      </p>
                    ) : null}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </GlassCard>
  );
}
