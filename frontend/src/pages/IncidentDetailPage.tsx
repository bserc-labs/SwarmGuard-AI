import { useParams, Link } from '@tanstack/react-router';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/services/api';
import { GlassCard } from '@/components/shared/GlassCard';
import { SeverityBadge } from '@/components/shared/SeverityBadge';
import { SHAPBarChart } from '@/components/shared/SHAPBarChart';
import { LoadingSpinner } from '@/components/shared/LoadingSpinner';
import { toast } from 'sonner';

export default function IncidentDetailPage() {
  const { id } = useParams({ from: '/incidents/$id' });
  const queryClient = useQueryClient();

  const { data: incident, isLoading, error } = useQuery({
    queryKey: ['incident', id],
    queryFn: () => api.getIncident(Number(id)),
  });

  const { mutate: updateStatus, isPending } = useMutation({
    mutationFn: (status: string) => api.updateIncidentStatus(Number(id), status),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['incident', id] });
      queryClient.invalidateQueries({ queryKey: ['incidents'] });
      toast.success(`Incident status updated to ${variables}`);
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : 'Failed to update status');
    }
  });

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center min-h-[50vh]">
        <LoadingSpinner />
      </div>
    );
  }

  if (error || !incident) {
    return (
      <div className="flex flex-col h-full items-center justify-center gap-4 min-h-[50vh]">
        <p className="text-sg-error font-mono">Error loading incident data.</p>
        <Link to="/incidents" className="text-sg-primary hover:underline font-mono text-sm">
          Return to Incidents
        </Link>
      </div>
    );
  }

  const handleAction = (status: string) => {
    updateStatus(status);
  };

  return (
    <div className="flex flex-col gap-6 p-6 max-w-6xl mx-auto">
      {/* Page Header */}
      <div className="flex items-center gap-4">
        <Link
          to="/incidents"
          className="flex items-center justify-center w-8 h-8 rounded-full bg-white/5 border border-white/10 hover:bg-white/10 text-sg-text-muted transition-colors"
        >
          <span className="material-symbols-outlined text-[18px]">arrow_back</span>
        </Link>
        <h1 className="text-2xl font-bold text-sg-text font-inter flex items-center gap-3">
          Incident <span className="text-sg-primary font-mono">#SG-{incident.id.toString().padStart(4, '0')}</span>
        </h1>
        <SeverityBadge severity={incident.severity} size="md" />
      </div>

      {/* Row 1: Two-column summary cards */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Left: Incident metadata */}
        <GlassCard>
          <h2 className="text-lg font-semibold text-sg-text mb-4">Incident Details</h2>
          <div className="space-y-4">
            <div>
              <span className="text-xs text-sg-text-dim uppercase tracking-wider block mb-1">Drone ID</span>
              <span className="font-mono text-sg-primary text-sm">{incident.drone_id}</span>
            </div>
            <div>
              <span className="text-xs text-sg-text-dim uppercase tracking-wider block mb-1">Attack Type</span>
              <span className="text-sg-text text-sm">{incident.attack_type}</span>
            </div>
            <div>
              <span className="text-xs text-sg-text-dim uppercase tracking-wider block mb-2">Threat Level</span>
              <div className="flex items-center gap-3">
                <span className="font-mono text-sm text-sg-text">{incident.threat_level.toFixed(1)}</span>
                <div className="h-2 w-full max-w-[200px] bg-white/10 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-sg-error transition-all duration-500"
                    style={{ width: `${Math.min(100, incident.threat_level)}%` }}
                  />
                </div>
              </div>
            </div>
            <div>
              <span className="text-xs text-sg-text-dim uppercase tracking-wider block mb-1">Status</span>
              {/* Note: getting status from server is preferable, we just show generic here or rely on the toast */}
              <span className="text-sg-text text-sm capitalize">Pending</span>
            </div>
            <div>
              <span className="text-xs text-sg-text-dim uppercase tracking-wider block mb-1">Created At</span>
              <span className="font-mono text-sg-text-muted text-sm">{new Date(incident.created_at).toLocaleString()}</span>
            </div>
          </div>
        </GlassCard>

        {/* Right: AI Explanation text */}
        <GlassCard>
          <h2 className="text-lg font-semibold text-sg-text mb-4">AI Explanation</h2>
          <div className="bg-white/5 border border-white/10 rounded-lg p-4 h-[calc(100%-3rem)] overflow-y-auto">
            <p className="text-sm text-sg-text-muted leading-relaxed font-mono whitespace-pre-wrap">
              {incident.explanation || "No detailed explanation available for this incident."}
            </p>
          </div>
        </GlassCard>
      </div>

      {/* Row 2: SHAP Analysis Section */}
      <GlassCard>
        <h2 className="text-lg font-semibold text-sg-text mb-4">AI Feature Importance &middot; SHAP Analysis</h2>
        <SHAPBarChart values={incident.shap_values} />
      </GlassCard>

      {/* Row 3: Action Buttons */}
      <GlassCard>
        <h2 className="text-lg font-semibold text-sg-text mb-4">Take Action</h2>
        <div className="flex flex-wrap gap-4">
          <button
            onClick={() => handleAction("ACKNOWLEDGED")}
            disabled={isPending}
            className="rounded border border-sg-primary/30 bg-sg-primary/10 px-4 py-2 text-sm font-medium uppercase tracking-wide text-sg-primary transition-colors hover:bg-sg-primary/20 disabled:opacity-50"
          >
            Acknowledge
          </button>
          <button
            onClick={() => handleAction("RESOLVED")}
            disabled={isPending}
            className="rounded border border-emerald-500/30 bg-emerald-500/10 px-4 py-2 text-sm font-medium uppercase tracking-wide text-emerald-300 transition-colors hover:bg-emerald-500/20 disabled:opacity-50"
          >
            Resolve
          </button>
          <button
            onClick={() => handleAction("FALSE_POSITIVE")}
            disabled={isPending}
            className="rounded border border-amber-500/30 bg-amber-500/10 px-4 py-2 text-sm font-medium uppercase tracking-wide text-amber-300 transition-colors hover:bg-amber-500/20 disabled:opacity-50"
          >
            False Positive
          </button>
          <button
            onClick={() => handleAction("ESCALATED")}
            disabled={isPending}
            className="rounded border border-sg-error/30 bg-sg-error/10 px-4 py-2 text-sm font-medium uppercase tracking-wide text-sg-error transition-colors hover:bg-sg-error/20 disabled:opacity-50"
          >
            Escalate
          </button>
        </div>
      </GlassCard>
    </div>
  );
}
