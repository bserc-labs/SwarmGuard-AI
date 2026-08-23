/**
 * Incident queue.
 *
 * Lifecycle actions map to the four transition routes the backend exposes:
 * acknowledge, assign, resolve, close. Each is gated on the matching permission,
 * so an operator (incident.read only) sees the queue without action buttons
 * rather than buttons that 403.
 */

import { useMemo, useState } from "react";
import { Link } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, type Incident } from "@/services/api";
import { POLL_INTERVALS } from "@/config";
import { DataState, EmptyState, PermissionDeniedState } from "@/components/ui/DataState";
import {
  Button,
  Chip,
  Input,
  Mono,
  PageHeader,
  Panel,
  PanelHeader,
  Select,
  Table,
  Td,
  Th,
} from "@/components/ui/primitives";
import {
  CLOSED_STATUSES,
  incidentStatusTone,
  severityTone,
  SEVERITY_FILTERS,
  SEVERITY_RANK,
} from "@/lib/constants";
import { humanizeEnum, relativeTime } from "@/lib/format";
import { hasPermission, Permissions } from "@/lib/rbac";
import { useAuth } from "@/hooks/useAuth";

type SeverityFilter = (typeof SEVERITY_FILTERS)[number];
type StatusFilter = "all" | "open" | "closed";

export default function IncidentsPage() {
  const queryClient = useQueryClient();
  const { user, role } = useAuth();
  const effectiveRole = user?.role ?? role;

  const canRead = hasPermission(effectiveRole, Permissions.INCIDENT_READ);
  const canAcknowledge = hasPermission(effectiveRole, Permissions.INCIDENT_ACKNOWLEDGE);
  const canResolve = hasPermission(effectiveRole, Permissions.INCIDENT_RESOLVE);
  const canClose = hasPermission(effectiveRole, Permissions.INCIDENT_CLOSE);
  const hasAnyAction = canAcknowledge || canResolve || canClose;

  const [severity, setSeverity] = useState<SeverityFilter>("All");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("open");
  const [search, setSearch] = useState("");

  const incidentsQuery = useQuery({
    queryKey: ["incidents", "list", severity],
    queryFn: () => api.getIncidents(severity === "All" ? undefined : severity, 200),
    refetchInterval: POLL_INTERVALS.incidents,
    enabled: canRead,
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["incidents"] });

  const transition = useMutation({
    mutationFn: ({
      id,
      action,
    }: {
      id: number;
      action: "acknowledge" | "resolve" | "close";
    }) => {
      if (action === "acknowledge") return api.acknowledgeIncident(id);
      if (action === "resolve") return api.resolveIncident(id);
      return api.closeIncident(id);
    },
    onSuccess: (incident, { action }) => {
      toast.success(`Incident #${incident.id} ${action}d`);
      invalidate();
    },
    onError: (error: unknown) => {
      toast.error(error instanceof Error ? error.message : "The transition failed.");
    },
  });

  const rows = useMemo(() => {
    const term = search.trim().toLowerCase();
    return (incidentsQuery.data ?? [])
      .filter((incident) => {
        const closed = CLOSED_STATUSES.has(incident.status);
        if (statusFilter === "open" && closed) return false;
        if (statusFilter === "closed" && !closed) return false;
        if (!term) return true;
        return (
          incident.drone_id.toLowerCase().includes(term) ||
          incident.attack_type.toLowerCase().includes(term) ||
          String(incident.id) === term
        );
      })
      .sort((a, b) => {
        const rank = (SEVERITY_RANK[b.severity] ?? 0) - (SEVERITY_RANK[a.severity] ?? 0);
        if (rank !== 0) return rank;
        return (
          new Date(b.detection_time ?? b.created_at).getTime() -
          new Date(a.detection_time ?? a.created_at).getTime()
        );
      });
  }, [incidentsQuery.data, statusFilter, search]);

  if (!canRead) {
    return (
      <>
        <PageHeader title="Incidents" />
        <Panel>
          <PermissionDeniedState />
        </Panel>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Incidents"
        description="Records stored for your organization, highest severity first."
      />

      {/* Filters */}
      <div className="mb-4 flex flex-wrap items-end gap-2.5">
        <div className="min-w-[9rem]">
          <label htmlFor="severity-filter" className="mb-1.5 block text-[12px] font-medium text-content-muted">
            Severity
          </label>
          <Select
            id="severity-filter"
            value={severity}
            onChange={(e) => setSeverity(e.target.value as SeverityFilter)}
            className="h-8 py-1"
          >
            {SEVERITY_FILTERS.map((option) => (
              <option key={option} value={option}>
                {option === "All" ? "All severities" : humanizeEnum(option)}
              </option>
            ))}
          </Select>
        </div>

        <div className="min-w-[9rem]">
          <label htmlFor="status-filter" className="mb-1.5 block text-[12px] font-medium text-content-muted">
            State
          </label>
          <Select
            id="status-filter"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
            className="h-8 py-1"
          >
            <option value="open">Open</option>
            <option value="closed">Resolved or closed</option>
            <option value="all">All</option>
          </Select>
        </div>

        <div className="min-w-[12rem] flex-1">
          <label htmlFor="incident-search" className="mb-1.5 block text-[12px] font-medium text-content-muted">
            Search
          </label>
          <Input
            id="incident-search"
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Drone, attack type, or incident number"
            className="h-8 py-1"
          />
        </div>
      </div>

      <Panel>
        <PanelHeader
          title={`${rows.length} ${rows.length === 1 ? "incident" : "incidents"}`}
          actions={
            <Button
              size="sm"
              icon="refresh"
              onClick={() => incidentsQuery.refetch()}
              loading={incidentsQuery.isFetching}
            >
              Refresh
            </Button>
          }
        />

        <DataState
          isLoading={incidentsQuery.isLoading}
          isError={incidentsQuery.isError}
          error={incidentsQuery.error}
          data={rows}
          onRetry={() => incidentsQuery.refetch()}
          empty={
            <EmptyState
              icon={statusFilter === "open" ? "check" : "info"}
              title={
                search || severity !== "All"
                  ? "No incidents match these filters"
                  : statusFilter === "open"
                    ? "No open incidents"
                    : "No incidents recorded"
              }
              detail={
                search || severity !== "All"
                  ? "Adjust the filters to widen the search."
                  : undefined
              }
            />
          }
        >
          {(incidents) => (
            <>
              {/* Table on wide viewports */}
              <div className="hidden lg:block">
                <Table>
                  <thead>
                    <tr>
                      <Th className="w-16">ID</Th>
                      <Th>Attack type</Th>
                      <Th>Drone</Th>
                      <Th>Severity</Th>
                      <Th>Status</Th>
                      <Th className="text-right">Threat</Th>
                      <Th>Detected</Th>
                      <Th>Assignee</Th>
                      {hasAnyAction ? <Th className="text-right">Actions</Th> : null}
                    </tr>
                  </thead>
                  <tbody>
                    {incidents.map((incident) => (
                      <tr key={incident.id} className="transition-colors hover:bg-surface-overlay">
                        <Td>
                          <Link
                            to="/incidents/$id"
                            params={{ id: String(incident.id) }}
                            className="font-mono text-[12px] text-accent-bright hover:underline"
                          >
                            #{incident.id}
                          </Link>
                        </Td>
                        <Td>
                          <Link
                            to="/incidents/$id"
                            params={{ id: String(incident.id) }}
                            className="text-content hover:underline"
                          >
                            {humanizeEnum(incident.attack_type)}
                          </Link>
                        </Td>
                        <Td>
                          <Mono className="text-content-muted">{incident.drone_id}</Mono>
                        </Td>
                        <Td>
                          <Chip tone={severityTone(incident.severity)}>
                            {humanizeEnum(incident.severity)}
                          </Chip>
                        </Td>
                        <Td>
                          <Chip tone={incidentStatusTone(incident.status)}>
                            {humanizeEnum(incident.status)}
                          </Chip>
                        </Td>
                        <Td className="text-right">
                          <Mono className="text-content-muted">
                            {incident.threat_score.toFixed(0)}
                          </Mono>
                        </Td>
                        <Td>
                          <span className="text-[12px] text-content-muted">
                            {relativeTime(incident.detection_time ?? incident.created_at)}
                          </span>
                        </Td>
                        <Td>
                          {incident.assigned_analyst ? (
                            <Mono className="text-content-muted">{incident.assigned_analyst}</Mono>
                          ) : (
                            <span className="text-[12px] text-content-dim">Unassigned</span>
                          )}
                        </Td>
                        {hasAnyAction ? (
                          <Td className="text-right">
                            <IncidentActions
                              incident={incident}
                              canAcknowledge={canAcknowledge}
                              canResolve={canResolve}
                              canClose={canClose}
                              pending={transition.isPending}
                              onAction={(action) =>
                                transition.mutate({ id: incident.id, action })
                              }
                            />
                          </Td>
                        ) : null}
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </div>

              {/* Cards on narrow viewports */}
              <ul className="divide-y divide-line-subtle lg:hidden">
                {incidents.map((incident) => (
                  <li key={incident.id} className="px-4 py-3">
                    <div className="flex items-start justify-between gap-2">
                      <Link
                        to="/incidents/$id"
                        params={{ id: String(incident.id) }}
                        className="min-w-0 flex-1"
                      >
                        <p className="truncate text-[13px] font-medium text-content">
                          {humanizeEnum(incident.attack_type)}
                        </p>
                        <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[11px] text-content-dim">
                          <Mono>#{incident.id}</Mono>
                          <Mono>{incident.drone_id}</Mono>
                          <span>{relativeTime(incident.detection_time ?? incident.created_at)}</span>
                        </p>
                      </Link>
                      <Chip tone={severityTone(incident.severity)}>
                        {humanizeEnum(incident.severity)}
                      </Chip>
                    </div>

                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <Chip tone={incidentStatusTone(incident.status)}>
                        {humanizeEnum(incident.status)}
                      </Chip>
                      <span className="text-[11px] text-content-dim">
                        Threat <Mono className="text-content-muted">{incident.threat_score.toFixed(0)}</Mono>
                      </span>
                      {incident.assigned_analyst ? (
                        <span className="text-[11px] text-content-dim">
                          <Mono className="text-content-muted">{incident.assigned_analyst}</Mono>
                        </span>
                      ) : null}
                    </div>

                    {hasAnyAction ? (
                      <div className="mt-2.5">
                        <IncidentActions
                          incident={incident}
                          canAcknowledge={canAcknowledge}
                          canResolve={canResolve}
                          canClose={canClose}
                          pending={transition.isPending}
                          onAction={(action) => transition.mutate({ id: incident.id, action })}
                        />
                      </div>
                    ) : null}
                  </li>
                ))}
              </ul>
            </>
          )}
        </DataState>
      </Panel>
    </>
  );
}

function IncidentActions({
  incident,
  canAcknowledge,
  canResolve,
  canClose,
  pending,
  onAction,
}: {
  incident: Incident;
  canAcknowledge: boolean;
  canResolve: boolean;
  canClose: boolean;
  pending: boolean;
  onAction: (action: "acknowledge" | "resolve" | "close") => void;
}) {
  const status = incident.status.toUpperCase();
  const isNew = status === "NEW" || status === "OPEN";
  const isClosed = status === "CLOSED";
  const isResolved = status === "RESOLVED";

  if (isClosed) {
    return <span className="text-[12px] text-content-dim">Closed</span>;
  }

  return (
    <div className="flex flex-wrap justify-end gap-1.5">
      {canAcknowledge && isNew ? (
        <Button size="sm" disabled={pending} onClick={() => onAction("acknowledge")}>
          Acknowledge
        </Button>
      ) : null}
      {canResolve && !isResolved ? (
        <Button size="sm" disabled={pending} onClick={() => onAction("resolve")}>
          Resolve
        </Button>
      ) : null}
      {canClose && isResolved ? (
        <Button size="sm" disabled={pending} onClick={() => onAction("close")}>
          Close
        </Button>
      ) : null}
    </div>
  );
}
