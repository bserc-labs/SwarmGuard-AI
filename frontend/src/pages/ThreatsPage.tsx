/**
 * Threat intelligence.
 *
 * Aggregations come from GET /incidents/stats, which the backend computes. The
 * page presents them as historical counts of stored incidents, not as a threat
 * assessment or model output — the backend does not produce either.
 */

import { useMemo } from "react";
import { Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { api, type IncidentStats } from "@/services/api";
import { POLL_INTERVALS } from "@/config";
import { StatTile } from "@/components/shared/StatTile";
import {
  DataState,
  EmptyState,
  LoadingState,
  PermissionDeniedState,
  UnavailableState,
} from "@/components/ui/DataState";
import {
  Chip,
  Mono,
  PageHeader,
  Panel,
  PanelBody,
  PanelHeader,
} from "@/components/ui/primitives";
import { incidentStatusTone, severityTone } from "@/lib/constants";
import { formatDuration, humanizeEnum, relativeTime } from "@/lib/format";
import { hasPermission, Permissions } from "@/lib/rbac";
import { useAuth } from "@/hooks/useAuth";

/** Horizontal bar list. Shares are computed against the largest bucket. */
function DistributionList({
  entries,
  tone,
  emptyLabel,
}: {
  entries: [string, number][];
  tone?: (key: string) => "critical" | "warning" | "accent" | "neutral";
  emptyLabel: string;
}) {
  if (entries.length === 0) {
    return <EmptyState compact title={emptyLabel} />;
  }

  const max = Math.max(...entries.map(([, count]) => count), 1);

  return (
    <ul className="flex flex-col gap-2 p-4">
      {entries.map(([key, count]) => (
        <li key={key}>
          <div className="flex items-baseline justify-between gap-3">
            <span className="min-w-0 truncate text-[12px] text-content-muted">
              {humanizeEnum(key)}
            </span>
            <Mono className="shrink-0 text-content">{count}</Mono>
          </div>
          <div
            className="mt-1 h-1 w-full overflow-hidden rounded-full bg-surface-active"
            role="presentation"
          >
            <div
              className={
                tone?.(key) === "critical"
                  ? "h-full bg-critical"
                  : tone?.(key) === "warning"
                    ? "h-full bg-warning"
                    : "h-full bg-accent"
              }
              style={{ width: `${(count / max) * 100}%` }}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}

function sortedEntries(record: Record<string, number> | undefined): [string, number][] {
  if (!record) return [];
  return Object.entries(record)
    .filter(([, count]) => count > 0)
    .sort((a, b) => b[1] - a[1]);
}

export default function ThreatsPage() {
  const { user, role } = useAuth();
  const canRead = hasPermission(user?.role ?? role, Permissions.INCIDENT_READ);

  const statsQuery = useQuery({
    queryKey: ["incident-stats"],
    queryFn: () => api.getIncidentStats(),
    refetchInterval: POLL_INTERVALS.stats,
    enabled: canRead,
  });

  const incidentsQuery = useQuery({
    queryKey: ["incidents", "threats"],
    queryFn: () => api.getIncidents(undefined, 200),
    refetchInterval: POLL_INTERVALS.incidents,
    enabled: canRead,
  });

  const stats: IncidentStats | undefined = statsQuery.data;

  const severityEntries = useMemo(() => sortedEntries(stats?.by_severity), [stats]);
  const attackEntries = useMemo(() => sortedEntries(stats?.by_threat_type), [stats]);
  const droneEntries = useMemo(() => sortedEntries(stats?.by_drone).slice(0, 10), [stats]);
  const statusEntries = useMemo(() => sortedEntries(stats?.by_status), [stats]);

  const mostAffected = droneEntries[0] ?? null;

  const recent = useMemo(
    () =>
      [...(incidentsQuery.data ?? [])]
        .sort(
          (a, b) =>
            new Date(b.detection_time ?? b.created_at).getTime() -
            new Date(a.detection_time ?? a.created_at).getTime(),
        )
        .slice(0, 10),
    [incidentsQuery.data],
  );

  if (!canRead) {
    return (
      <>
        <PageHeader title="Threat intelligence" />
        <Panel>
          <PermissionDeniedState />
        </Panel>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Threat intelligence"
        description="Aggregated counts across incidents stored for your organization."
      />

      {statsQuery.isLoading ? (
        <Panel>
          <LoadingState rows={5} />
        </Panel>
      ) : statsQuery.isError ? (
        <Panel>
          <UnavailableState
            title="Statistics unavailable"
            detail="The incident statistics endpoint could not be read, so no aggregates can be shown."
          />
        </Panel>
      ) : (
        <>
          <section aria-label="Totals" className="grid grid-cols-2 gap-2.5 lg:grid-cols-4">
            <StatTile label="Total incidents" icon="shield" value={stats?.total ?? null} />
            <StatTile
              label="Critical"
              icon="alert"
              value={stats?.by_severity?.CRITICAL ?? 0}
              tone={stats?.by_severity?.CRITICAL ? "critical" : "nominal"}
            />
            <StatTile
              label="Mean time to resolve"
              icon="clock"
              value={
                stats?.avg_resolution_time_seconds
                  ? formatDuration(stats.avg_resolution_time_seconds)
                  : null
              }
              detail={
                stats?.avg_resolution_time_seconds
                  ? "Across resolved incidents"
                  : "No incidents resolved yet"
              }
            />
            <StatTile
              label="Most affected drone"
              icon="drone"
              value={mostAffected ? mostAffected[0] : null}
              detail={
                mostAffected
                  ? `${mostAffected[1]} ${mostAffected[1] === 1 ? "incident" : "incidents"}`
                  : undefined
              }
            />
          </section>

          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <Panel>
              <PanelHeader title="By severity" />
              <DistributionList
                entries={severityEntries}
                tone={(key) => severityTone(key)}
                emptyLabel="No incidents recorded"
              />
            </Panel>

            <Panel>
              <PanelHeader title="By attack type" />
              <DistributionList entries={attackEntries} emptyLabel="No attack types recorded" />
            </Panel>

            <Panel>
              <PanelHeader title="By status" />
              <DistributionList
                entries={statusEntries}
                tone={(key) => incidentStatusTone(key)}
                emptyLabel="No incidents recorded"
              />
            </Panel>

            <Panel>
              <PanelHeader title="By drone" description="Top 10 by incident count." />
              <DistributionList entries={droneEntries} emptyLabel="No incidents recorded" />
            </Panel>
          </div>

          <Panel className="mt-4">
            <PanelHeader title="Most recent" description="Newest first." />
            <DataState
              isLoading={incidentsQuery.isLoading}
              isError={incidentsQuery.isError}
              error={incidentsQuery.error}
              data={recent}
              onRetry={() => incidentsQuery.refetch()}
              compact
              empty={<EmptyState compact title="No incidents recorded" />}
            >
              {(items) => (
                <ul className="divide-y divide-line-subtle">
                  {items.map((incident) => (
                    <li key={incident.id}>
                      <Link
                        to="/incidents/$id"
                        params={{ id: String(incident.id) }}
                        className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 hover:bg-surface-overlay"
                      >
                        <Chip tone={severityTone(incident.severity)}>
                          {humanizeEnum(incident.severity)}
                        </Chip>
                        <span className="min-w-0 flex-1 truncate text-[13px] text-content">
                          {humanizeEnum(incident.attack_type)}
                        </span>
                        <Mono className="text-content-muted">{incident.drone_id}</Mono>
                        <span className="text-[11px] text-content-dim">
                          {relativeTime(incident.detection_time ?? incident.created_at)}
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </DataState>
          </Panel>

          <Panel className="mt-4">
            <PanelBody>
              <h2 className="text-[13px] font-semibold text-content">Scope of these figures</h2>
              <p className="mt-1 max-w-[80ch] text-[12px] leading-relaxed text-content-muted">
                These are counts of incident records, not a threat assessment. The backend prunes
                telemetry older than three days, so incidents may outlive the readings that produced
                them.
              </p>
            </PanelBody>
          </Panel>
        </>
      )}
    </>
  );
}
