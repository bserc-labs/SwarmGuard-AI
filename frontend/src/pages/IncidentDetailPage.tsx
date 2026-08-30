/**
 * Single incident.
 *
 * Everything shown is read from the incident record. Where the record lacks a
 * field — model version, attribution, recommended action — the page says so
 * rather than substituting a default.
 */

import { useState } from "react";
import { Link, useParams } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "@/services/api";
import { AttributionChart } from "@/components/shared/AttributionChart";
import { IncidentTimeline } from "@/components/shared/IncidentTimeline";
import {
  ErrorState,
  LoadingState,
  PermissionDeniedState,
  UnavailableState,
} from "@/components/ui/DataState";
import { Icon } from "@/components/ui/Icon";
import {
  Button,
  Chip,
  Field,
  Input,
  Mono,
  PageHeader,
  Panel,
  PanelBody,
  PanelHeader,
} from "@/components/ui/primitives";
import {
  canAdvanceTo,
  incidentStatusTone,
  severityTone,
  type IncidentStatus,
} from "@/lib/constants";
import {
  buildForensicReport,
  downloadReport,
  forensicFilename,
  forensicReportToCsv,
} from "@/lib/forensicExport";
import { formatDateTime, humanizeEnum, relativeTime } from "@/lib/format";
import { hasPermission, Permissions } from "@/lib/rbac";
import { useAuth } from "@/hooks/useAuth";

/**
 * The lifecycle actions this page offers, each mapped to the state it lands on.
 *
 * Availability is decided by `canAdvanceTo` against that target rather than by
 * ad-hoc status flags. The previous version showed Resolve whenever the
 * incident was not already resolved, which included NEW and ACKNOWLEDGED —
 * states the backend refused, so the button returned 400 from every state a
 * user could actually reach it in.
 */
const TRANSITION_ACTIONS = {
  acknowledge: {
    label: "Acknowledge",
    past: "acknowledged",
    target: "ACKNOWLEDGED",
    run: (id: number, note?: string) => api.acknowledgeIncident(id, note),
  },
  investigate: {
    label: "Investigate",
    past: "moved to investigating",
    target: "INVESTIGATING",
    run: (id: number, note?: string) => api.investigateIncident(id, note),
  },
  contain: {
    label: "Contain",
    past: "marked contained",
    target: "CONTAINED",
    run: (id: number, note?: string) => api.containIncident(id, note),
  },
  resolve: {
    label: "Resolve",
    past: "resolved",
    target: "RESOLVED",
    run: (id: number, note?: string) => api.resolveIncident(id, note),
  },
  close: {
    label: "Close",
    past: "closed",
    target: "CLOSED",
    run: (id: number, note?: string) => api.closeIncident(id, note),
  },
} as const satisfies Record<
  string,
  { label: string; past: string; target: IncidentStatus; run: (id: number, note?: string) => Promise<unknown> }
>;

type TransitionAction = keyof typeof TRANSITION_ACTIONS;

export default function IncidentDetailPage() {
  const { id } = useParams({ from: "/layout/incidents/$id" });
  const incidentId = Number(id);
  const queryClient = useQueryClient();
  const { user, role } = useAuth();
  const effectiveRole = user?.role ?? role;

  const canRead = hasPermission(effectiveRole, Permissions.INCIDENT_READ);
  const canAcknowledge = hasPermission(effectiveRole, Permissions.INCIDENT_ACKNOWLEDGE);
  const canAssign = hasPermission(effectiveRole, Permissions.INCIDENT_ASSIGN);
  const canResolve = hasPermission(effectiveRole, Permissions.INCIDENT_RESOLVE);
  const canClose = hasPermission(effectiveRole, Permissions.INCIDENT_CLOSE);
  const canReadAudit = hasPermission(effectiveRole, Permissions.AUDIT_READ);

  const [reason, setReason] = useState("");
  const [assignee, setAssignee] = useState("");

  const incidentQuery = useQuery({
    queryKey: ["incident", incidentId],
    queryFn: () => api.getIncident(incidentId),
    enabled: canRead && Number.isFinite(incidentId),
  });

  const auditQuery = useQuery({
    queryKey: ["audit-logs"],
    queryFn: () => api.getAuditLogs(),
    enabled: canReadAudit,
  });

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["incident", incidentId] });
    queryClient.invalidateQueries({ queryKey: ["incidents"] });
    queryClient.invalidateQueries({ queryKey: ["audit-logs"] });
  };

  const transition = useMutation({
    mutationFn: ({ action }: { action: TransitionAction }) => {
      const note = reason.trim() || undefined;
      return TRANSITION_ACTIONS[action].run(incidentId, note);
    },
    onSuccess: (_data, { action }) => {
      toast.success(`Incident ${TRANSITION_ACTIONS[action].past}`);
      setReason("");
      refresh();
    },
    onError: (error: unknown) =>
      toast.error(error instanceof Error ? error.message : "The transition failed."),
  });

  const assign = useMutation({
    mutationFn: () => api.assignIncident(incidentId, assignee.trim()),
    onSuccess: () => {
      toast.success(`Assigned to ${assignee.trim()}`);
      setAssignee("");
      refresh();
    },
    onError: (error: unknown) =>
      toast.error(error instanceof Error ? error.message : "Assignment failed."),
  });

  if (!canRead) {
    return (
      <>
        <PageHeader title="Incident" />
        <Panel>
          <PermissionDeniedState />
        </Panel>
      </>
    );
  }

  if (!Number.isFinite(incidentId)) {
    return (
      <>
        <PageHeader title="Incident" />
        <Panel>
          <UnavailableState title="Invalid incident reference" detail={`“${id}” is not an incident number.`} />
        </Panel>
      </>
    );
  }

  if (incidentQuery.isLoading) {
    return (
      <Panel>
        <LoadingState rows={8} />
      </Panel>
    );
  }

  if (incidentQuery.isError || !incidentQuery.data) {
    return (
      <>
        <PageHeader title="Incident" />
        <Panel>
          <ErrorState error={incidentQuery.error} onRetry={() => incidentQuery.refetch()} />
        </Panel>
      </>
    );
  }

  const incident = incidentQuery.data;

  /**
   * Forensic export. Built entirely from what the API returned — absent fields
   * export as null rather than a default, and the report records whether the
   * audit log was readable so a reader can distinguish "no activity" from
   * "activity not visible to the exporter".
   */
  function exportReport(format: "json" | "csv") {
    const at = new Date();
    try {
      const report = buildForensicReport({
        incident,
        auditLogs: auditQuery.data ?? [],
        user,
        auditAccessible: canReadAudit && !auditQuery.isError,
        generatedAt: at,
      });

      downloadReport(
        forensicFilename(incident, format, at),
        format === "json" ? JSON.stringify(report, null, 2) : forensicReportToCsv(report),
        format === "json" ? "application/json" : "text/csv",
      );

      toast.success(
        report.report.notes.length > 0
          ? `Report exported with ${report.report.notes.length} noted omission${report.report.notes.length === 1 ? "" : "s"}.`
          : "Report exported.",
      );
    } catch {
      toast.error("Could not generate the report.");
    }
  }

  const status = incident.status.toUpperCase();
  const isClosed = status === "CLOSED";

  /**
   * An action is offered only when its destination is still ahead of the
   * incident and the role may perform it. Investigate and Contain are gated on
   * the acknowledge permission, matching the backend, which treats them as the
   * same tier of analyst work rather than introducing a permission that would
   * have to be mirrored here to stay in sync.
   */
  const permitted: Record<TransitionAction, boolean> = {
    acknowledge: canAcknowledge,
    investigate: canAcknowledge,
    contain: canAcknowledge,
    resolve: canResolve,
    close: canClose,
  };

  const available = (Object.keys(TRANSITION_ACTIONS) as TransitionAction[]).filter(
    (action) =>
      permitted[action] && canAdvanceTo(status, TRANSITION_ACTIONS[action].target),
  );

  const hasActions = !isClosed && (available.length > 0 || canAssign);

  return (
    <>
      <Link
        to="/incidents"
        className="mb-3 inline-flex items-center gap-1.5 text-[12px] text-content-muted hover:text-content"
      >
        <Icon name="arrow-left" size={13} />
        All incidents
      </Link>

      <PageHeader
        title={humanizeEnum(incident.attack_type)}
        description={`Incident #${incident.id} on ${incident.drone_id}`}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Chip tone={severityTone(incident.severity)}>{humanizeEnum(incident.severity)}</Chip>
            <Chip tone={incidentStatusTone(incident.status)}>{humanizeEnum(incident.status)}</Chip>
            <Button size="sm" icon="download" onClick={() => exportReport("json")}>
              JSON
            </Button>
            <Button size="sm" icon="download" onClick={() => exportReport("csv")}>
              CSV
            </Button>
          </div>
        }
      />

      <div className="grid gap-4 xl:grid-cols-[1fr_340px]">
        <div className="flex flex-col gap-4">
          {/* Summary */}
          <Panel>
            <PanelHeader title="Summary" />
            <PanelBody>
              <p className="max-w-[80ch] text-[13px] leading-relaxed text-content-muted">
                {incident.explanation || "No description was stored with this incident."}
              </p>

              <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3">
                <div>
                  <dt className="text-[11px] text-content-dim">Drone</dt>
                  <dd className="mt-0.5">
                    <Mono className="text-[13px] text-content">{incident.drone_id}</Mono>
                  </dd>
                </div>
                <div>
                  <dt className="text-[11px] text-content-dim">Detected</dt>
                  <dd className="mt-0.5 text-[13px] text-content">
                    {formatDateTime(incident.detection_time ?? incident.created_at)}
                  </dd>
                </div>
                <div>
                  <dt className="text-[11px] text-content-dim">Assignee</dt>
                  <dd className="mt-0.5 text-[13px]">
                    {incident.assigned_analyst ? (
                      <Mono className="text-content">{incident.assigned_analyst}</Mono>
                    ) : (
                      <span className="text-content-dim">Unassigned</span>
                    )}
                  </dd>
                </div>
                <div>
                  <dt className="text-[11px] text-content-dim">Mission</dt>
                  <dd className="mt-0.5 text-[13px]">
                    {incident.mission_id ? (
                      <Mono className="text-content">{incident.mission_id}</Mono>
                    ) : (
                      <span className="text-content-dim">Not recorded</span>
                    )}
                  </dd>
                </div>
                <div>
                  <dt className="text-[11px] text-content-dim">Feature version</dt>
                  <dd className="mt-0.5 text-[13px]">
                    {incident.feature_version ? (
                      <Mono className="text-content">{incident.feature_version}</Mono>
                    ) : (
                      <span className="text-content-dim">Not recorded</span>
                    )}
                  </dd>
                </div>
                <div>
                  <dt className="text-[11px] text-content-dim">Resolved</dt>
                  <dd className="mt-0.5 text-[13px]">
                    {incident.resolution_time ? (
                      <span className="text-content">{formatDateTime(incident.resolution_time)}</span>
                    ) : (
                      <span className="text-content-dim">Not yet</span>
                    )}
                  </dd>
                </div>
              </dl>
            </PanelBody>
          </Panel>

          {/* Attribution */}
          <Panel>
            <PanelHeader
              title="Detection detail"
              description="Values as recorded on this incident by the backend."
            />
            <PanelBody>
              <AttributionChart incident={incident} />
            </PanelBody>
          </Panel>

          {/* Recommended action */}
          <Panel>
            <PanelHeader title="Recommended action" />
            <PanelBody>
              {incident.recommended_action ?? incident.explanation_summary?.recommended_action ? (
                <p className="max-w-[80ch] text-[13px] leading-relaxed text-content-muted">
                  {incident.recommended_action ?? incident.explanation_summary?.recommended_action}
                </p>
              ) : (
                <UnavailableState
                  compact
                  title="None recorded"
                  detail="No recommended action was stored with this incident."
                />
              )}
            </PanelBody>
          </Panel>
        </div>

        <div className="flex flex-col gap-4">
          {/* Actions */}
          {hasActions ? (
            <Panel>
              <PanelHeader title="Actions" description="Recorded in the audit log with your username." />
              <PanelBody className="flex flex-col gap-3">
                <Field label="Note" htmlFor="transition-reason" hint="Optional. Stored with the transition.">
                  <Input
                    id="transition-reason"
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    placeholder="Reason or context"
                  />
                </Field>

                <div className="flex flex-wrap gap-2">
                  {available.map((action, index) => (
                    <Button
                      key={action}
                      // The nearest state ahead is the expected next move.
                      variant={index === 0 ? "primary" : "secondary"}
                      size="sm"
                      disabled={transition.isPending}
                      onClick={() => transition.mutate({ action })}
                    >
                      {TRANSITION_ACTIONS[action].label}
                    </Button>
                  ))}
                </div>

                {available.length > 1 ? (
                  <p className="text-[11px] leading-relaxed text-content-dim">
                    Choosing a later state records every state in between. The activity log below
                    shows the full path, not just the state you selected.
                  </p>
                ) : null}

                {canAssign ? (
                  <div className="border-t border-line-subtle pt-3">
                    <Field label="Assign to" htmlFor="assignee" hint="Username of an analyst in your organization.">
                      <Input
                        id="assignee"
                        value={assignee}
                        onChange={(e) => setAssignee(e.target.value)}
                        placeholder="username"
                        autoComplete="off"
                      />
                    </Field>
                    <Button
                      size="sm"
                      className="mt-2"
                      disabled={!assignee.trim() || assign.isPending}
                      loading={assign.isPending}
                      onClick={() => assign.mutate()}
                    >
                      Assign
                    </Button>
                  </div>
                ) : null}
              </PanelBody>
            </Panel>
          ) : isClosed ? (
            <Panel>
              <PanelBody>
                <p className="text-[13px] text-content-muted">
                  This incident is closed. No further transitions are available.
                </p>
              </PanelBody>
            </Panel>
          ) : null}

          {/* Timeline */}
          <Panel>
            <PanelHeader
              title="Activity"
              description={canReadAudit ? "From the audit log." : undefined}
            />
            <PanelBody>
              {!canReadAudit ? (
                <UnavailableState
                  compact
                  title="Audit log not accessible"
                  detail="Your role does not include permission to read audit records, so activity cannot be shown."
                />
              ) : auditQuery.isLoading ? (
                <LoadingState rows={4} compact />
              ) : auditQuery.isError ? (
                <UnavailableState
                  compact
                  title="Activity unavailable"
                  detail="The audit log could not be read."
                />
              ) : (
                <IncidentTimeline incident={incident} auditLogs={auditQuery.data ?? []} />
              )}
            </PanelBody>
          </Panel>

          <Panel>
            <PanelBody className="py-2.5">
              <p className="text-[11px] text-content-dim">
                Last updated {relativeTime(incident.updated_at)}
              </p>
            </PanelBody>
          </Panel>
        </div>
      </div>
    </>
  );
}
