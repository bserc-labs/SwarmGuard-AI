/**
 * Operations overview.
 *
 * Counts come from GET /system/health, which is a server-side query, rather than
 * being derived in the browser from a partial telemetry page. When that request
 * fails the tiles show "not reported" instead of zeros.
 */

import { useMemo } from "react";
import { Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/services/api";
import { POLL_INTERVALS } from "@/config";
import { useWebSocketContext } from "@/contexts/WebSocketContext";
import {
  DataState,
  EmptyState,
  ErrorState,
  LoadingState,
  PermissionDeniedState,
} from "@/components/ui/DataState";
import { FeedStatus } from "@/components/ui/FeedStatus";
import { feedStateDescription } from "@/lib/feedState";
import { StatTile } from "@/components/shared/StatTile";
import { DroneMap } from "@/components/shared/DroneMap";
import { mergePositions } from "@/lib/telemetry";
import { Chip, Mono, Panel, PanelBody, PanelHeader, PageHeader } from "@/components/ui/primitives";
import { humanizeEnum, relativeTime } from "@/lib/format";
import { severityTone, SEVERITY_RANK } from "@/lib/constants";
import { hasPermission, Permissions } from "@/lib/rbac";
import { useAuth } from "@/hooks/useAuth";

export default function DashboardPage() {
  const { user, role } = useAuth();
  const effectiveRole = user?.role ?? role;
  const { feedState, latestTelemetry } = useWebSocketContext();

  const canReadTelemetry = hasPermission(effectiveRole, Permissions.TELEMETRY_READ);
  const canReadIncidents = hasPermission(effectiveRole, Permissions.INCIDENT_READ);

  const healthQuery = useQuery({
    queryKey: ["system-health"],
    queryFn: () => api.getSystemHealth(),
    refetchInterval: POLL_INTERVALS.health,
  });

  const incidentsQuery = useQuery({
    queryKey: ["incidents", "dashboard"],
    queryFn: () => api.getIncidents(undefined, 50),
    refetchInterval: POLL_INTERVALS.incidents,
    enabled: canReadIncidents,
  });

  const telemetryQuery = useQuery({
    queryKey: ["telemetry", "latest"],
    queryFn: () => api.getLatestTelemetry(),
    refetchInterval: POLL_INTERVALS.fleet,
    enabled: canReadTelemetry,
  });

  const health = healthQuery.data;
  const healthUnavailable = healthQuery.isError || health?.db_connected === false;

  // Socket frames supersede the polled snapshot per drone.
  const mapDrones = useMemo(
    () => mergePositions(telemetryQuery.data ?? [], latestTelemetry),
    [telemetryQuery.data, latestTelemetry],
  );

  const recentIncidents = useMemo(() => {
    return [...(incidentsQuery.data ?? [])]
      .sort((a, b) => {
        const rank = (SEVERITY_RANK[b.severity] ?? 0) - (SEVERITY_RANK[a.severity] ?? 0);
        if (rank !== 0) return rank;
        return (
          new Date(b.detection_time ?? b.created_at).getTime() -
          new Date(a.detection_time ?? a.created_at).getTime()
        );
      })
      .slice(0, 6);
  }, [incidentsQuery.data]);

  return (
    <>
      <PageHeader
        title="Operations overview"
        description="Fleet status, active incidents, and current positions for your organization."
        actions={<FeedStatus state={feedState} />}
      />

      {/* Counters */}
      <section aria-label="Fleet summary" className="grid grid-cols-2 gap-2.5 lg:grid-cols-4">
        <StatTile
          label="Active drones"
          icon="drone"
          value={healthUnavailable ? null : health?.active_drones}
          tone="accent"
          detail={
            healthUnavailable
              ? undefined
              : health?.total_drones !== undefined
                ? `of ${health.total_drones} registered`
                : undefined
          }
        />
        <StatTile
          label="Silent drones"
          icon="signal"
          value={healthUnavailable ? null : health?.silent_drones}
          tone={health?.silent_drones ? "critical" : "neutral"}
          detail={
            healthUnavailable
              ? undefined
              : health?.silent_drones
                ? "No heartbeat within the timeout"
                : "All drones reporting"
          }
        />
        <StatTile
          label="Critical incidents"
          icon="alert"
          value={healthUnavailable ? null : health?.critical_incidents}
          tone={health?.critical_incidents ? "critical" : "nominal"}
          detail={
            healthUnavailable
              ? undefined
              : health?.total_incidents !== undefined
                ? `of ${health.total_incidents} total`
                : undefined
          }
        />
        <StatTile
          label="Telemetry feed"
          icon="activity"
          value={
            feedState === "live"
              ? "Live"
              : feedState === "stale"
                ? "Stale"
                : feedState === "connecting"
                  ? "Connecting"
                  : "Offline"
          }
          tone={feedState === "live" ? "nominal" : feedState === "stale" ? "warning" : "critical"}
          detail={feedStateDescription(feedState)}
        />
      </section>

      {healthUnavailable ? (
        <p className="mt-2.5 rounded-control border border-warning/35 bg-warning-wash px-3 py-2 text-[12px] text-warning">
          System health could not be read, so fleet counters are unavailable. Values shown elsewhere
          on this page come from separate requests and may still be current.
        </p>
      ) : null}

      <div className="mt-4 grid gap-4 xl:grid-cols-[1fr_360px]">
        {/* Map */}
        <Panel className="overflow-hidden">
          <PanelHeader
            title="Fleet positions"
            description={
              canReadTelemetry
                ? "Latest reported position per drone. Restricted zones are evaluated in the browser."
                : undefined
            }
          />
          {!canReadTelemetry ? (
            <PermissionDeniedState compact />
          ) : telemetryQuery.isLoading ? (
            <LoadingState rows={6} />
          ) : telemetryQuery.isError ? (
            <ErrorState error={telemetryQuery.error} onRetry={() => telemetryQuery.refetch()} />
          ) : (
            <DroneMap drones={mapDrones} className="h-[420px] w-full" />
          )}
        </Panel>

        {/* Incidents */}
        <Panel className="flex flex-col">
          <PanelHeader
            title="Recent incidents"
            description="Highest severity first."
            actions={
              <Link
                to="/incidents"
                className="text-[12px] text-accent-bright hover:underline"
              >
                All
              </Link>
            }
          />
          {!canReadIncidents ? (
            <PermissionDeniedState compact />
          ) : (
            <DataState
              isLoading={incidentsQuery.isLoading}
              isError={incidentsQuery.isError}
              error={incidentsQuery.error}
              data={recentIncidents}
              onRetry={() => incidentsQuery.refetch()}
              compact
              empty={
                <EmptyState
                  compact
                  icon="check"
                  title="No incidents recorded"
                  detail="Nothing has been flagged for this organization."
                />
              }
            >
              {(incidents) => (
                <ul className="divide-y divide-line-subtle">
                  {incidents.map((incident) => (
                    <li key={incident.id}>
                      <Link
                        to="/incidents/$id"
                        params={{ id: String(incident.id) }}
                        className="block px-4 py-2.5 transition-colors hover:bg-surface-overlay"
                      >
                        <div className="flex items-start justify-between gap-2">
                          <p className="min-w-0 flex-1 truncate text-[13px] font-medium text-content">
                            {humanizeEnum(incident.attack_type)}
                          </p>
                          <Chip tone={severityTone(incident.severity)}>
                            {humanizeEnum(incident.severity)}
                          </Chip>
                        </div>
                        <p className="mt-1 flex flex-wrap items-center gap-x-2.5 gap-y-0.5 text-[11px] text-content-dim">
                          <Mono>{incident.drone_id}</Mono>
                          <span>{relativeTime(incident.detection_time ?? incident.created_at)}</span>
                          <span>{humanizeEnum(incident.status)}</span>
                        </p>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </DataState>
          )}
        </Panel>
      </div>

      {/* Detection pipeline transparency */}
      <Panel className="mt-4">
        <PanelBody className="flex flex-wrap items-start gap-x-3 gap-y-2">
          <div className="min-w-0 flex-1">
            <h2 className="text-[13px] font-semibold text-content">About these incidents</h2>
            <p className="mt-1 max-w-[80ch] text-[12px] leading-relaxed text-content-muted">
              Incidents shown here are records the backend has stored. This console reports what the
              API returns and does not label a finding as model-detected, verified, or explained
              unless the incident payload carries that provenance.
            </p>
          </div>
        </PanelBody>
      </Panel>
    </>
  );
}
