/**
 * Fleet control.
 *
 * Exposes the two-person command flow the backend implements but that the UI
 * previously did not surface at all: a request creates a PENDING record, and a
 * second authorised user approves it. That separation is the point of the
 * feature, so the page states it plainly.
 *
 * Also removed: the "check heartbeats" button, which called
 * POST /drones/check-heartbeats. No such route exists — heartbeat evaluation is
 * a server-side background task and cannot be triggered from the client.
 */

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  api,
  COMMAND_TYPES,
  type CommandRequest,
  type CommandType,
  type Drone,
} from "@/services/api";
import { POLL_INTERVALS } from "@/config";
import {
  DataState,
  EmptyState,
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
  Select,
} from "@/components/ui/primitives";
import { droneStatusTone } from "@/lib/constants";
import { formatDateTime, humanizeEnum, relativeTime } from "@/lib/format";
import { hasPermission, Permissions } from "@/lib/rbac";
import { useAuth } from "@/hooks/useAuth";

function commandStatusTone(status: string): "critical" | "warning" | "accent" | "neutral" {
  switch (status.toUpperCase()) {
    case "PENDING":
      return "warning";
    case "APPROVED":
      return "accent";
    case "REJECTED":
      return "critical";
    default:
      return "neutral";
  }
}

export default function AdminPage() {
  const queryClient = useQueryClient();
  const { user, role } = useAuth();
  const effectiveRole = user?.role ?? role;

  const canReadDrones = hasPermission(effectiveRole, Permissions.DRONE_READ);
  const canRequest = hasPermission(effectiveRole, Permissions.DRONE_COMMAND_REQUEST);
  const canApprove = hasPermission(effectiveRole, Permissions.DRONE_COMMAND_APPROVE);

  const [selectedDrone, setSelectedDrone] = useState<string>("");
  const [commandType, setCommandType] = useState<CommandType>("RETURN_TO_HOME");
  const [reason, setReason] = useState("");

  const dronesQuery = useQuery({
    queryKey: ["drones"],
    queryFn: () => api.getDrones(),
    refetchInterval: POLL_INTERVALS.fleet,
    enabled: canReadDrones,
  });

  const commandsQuery = useQuery({
    queryKey: ["commands", selectedDrone],
    queryFn: () => api.getDroneCommands(selectedDrone),
    enabled: canReadDrones && selectedDrone !== "",
    refetchInterval: POLL_INTERVALS.fleet,
  });

  const drones = useMemo(
    () => [...(dronesQuery.data ?? [])].sort((a, b) => a.drone_id.localeCompare(b.drone_id)),
    [dronesQuery.data],
  );

  const invalidateCommands = () =>
    queryClient.invalidateQueries({ queryKey: ["commands"] });

  const requestCommand = useMutation({
    mutationFn: () => api.requestCommand(selectedDrone, commandType, reason.trim() || undefined),
    onSuccess: (command) => {
      toast.success(
        `Request #${command.command_id} recorded as ${command.status.toLowerCase()}. It requires approval before it takes effect.`,
      );
      setReason("");
      invalidateCommands();
    },
    onError: (error: unknown) =>
      toast.error(error instanceof Error ? error.message : "Could not record the request."),
  });

  const decide = useMutation({
    mutationFn: ({ command, approved }: { command: CommandRequest; approved: boolean }) =>
      api.approveCommand(command.drone_id, command.command_id, approved),
    onSuccess: (command) => {
      toast.success(`Request #${command.command_id} ${command.status.toLowerCase()}`);
      invalidateCommands();
    },
    onError: (error: unknown) =>
      toast.error(error instanceof Error ? error.message : "Could not record the decision."),
  });

  if (!canReadDrones) {
    return (
      <>
        <PageHeader title="Fleet control" />
        <Panel>
          <PermissionDeniedState />
        </Panel>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Fleet control"
        description="Request and approve drone commands. Requests are recorded and require a second authorised user to approve."
      />

      <div className="grid gap-4 xl:grid-cols-[340px_1fr]">
        {/* Request form */}
        <div className="flex flex-col gap-4">
          <Panel>
            <PanelHeader
              title="Request a command"
              description={
                canRequest
                  ? "Recorded as pending. It does not actuate until approved."
                  : undefined
              }
            />
            {!canRequest ? (
              <PermissionDeniedState
                compact
                detail="Requesting commands requires the drone.command.request permission."
              />
            ) : (
              <PanelBody className="flex flex-col gap-3">
                <Field label="Drone" htmlFor="command-drone">
                  <Select
                    id="command-drone"
                    value={selectedDrone}
                    onChange={(e) => setSelectedDrone(e.target.value)}
                  >
                    <option value="">Select a drone</option>
                    {drones.map((drone) => (
                      <option key={drone.id} value={drone.drone_id}>
                        {drone.drone_id} — {humanizeEnum(drone.status)}
                      </option>
                    ))}
                  </Select>
                </Field>

                <Field label="Command" htmlFor="command-type">
                  <Select
                    id="command-type"
                    value={commandType}
                    onChange={(e) => setCommandType(e.target.value as CommandType)}
                  >
                    {COMMAND_TYPES.map((type) => (
                      <option key={type} value={type}>
                        {humanizeEnum(type)}
                      </option>
                    ))}
                  </Select>
                </Field>

                <Field
                  label="Reason"
                  htmlFor="command-reason"
                  hint="Recorded in the audit log alongside your username."
                >
                  <Input
                    id="command-reason"
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    placeholder="Why this command is needed"
                  />
                </Field>

                <Button
                  variant="primary"
                  disabled={!selectedDrone || requestCommand.isPending}
                  loading={requestCommand.isPending}
                  onClick={() => requestCommand.mutate()}
                >
                  Submit request
                </Button>

                <p className="flex items-start gap-2 rounded-control border border-line bg-surface-overlay px-2.5 py-2 text-[11px] leading-relaxed text-content-muted">
                  <Icon name="info" size={13} className="mt-0.5 shrink-0 text-content-dim" />
                  <span>
                    The backend records commands but does not transmit them to the aircraft. This is
                    an authorization record, not an uplink.
                  </span>
                </p>
              </PanelBody>
            )}
          </Panel>

          <Panel>
            <PanelHeader title="Fleet" description={`${drones.length} registered`} />
            <DataState
              isLoading={dronesQuery.isLoading}
              isError={dronesQuery.isError}
              error={dronesQuery.error}
              data={drones}
              onRetry={() => dronesQuery.refetch()}
              compact
              empty={<EmptyState compact icon="drone" title="No drones registered" />}
            >
              {(list: Drone[]) => (
                <ul className="divide-y divide-line-subtle">
                  {list.map((drone) => (
                    <li key={drone.id}>
                      <button
                        type="button"
                        onClick={() => setSelectedDrone(drone.drone_id)}
                        aria-pressed={selectedDrone === drone.drone_id}
                        className={`flex w-full items-center justify-between gap-2 px-4 py-2.5 text-left transition-colors hover:bg-surface-overlay ${
                          selectedDrone === drone.drone_id ? "bg-accent-wash" : ""
                        }`}
                      >
                        <div className="min-w-0">
                          <Mono className="text-content">{drone.drone_id}</Mono>
                          <p className="mt-0.5 text-[11px] text-content-dim">
                            Last seen {relativeTime(drone.last_seen)}
                          </p>
                        </div>
                        <Chip tone={droneStatusTone(drone.status)}>
                          {humanizeEnum(drone.status)}
                        </Chip>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </DataState>
          </Panel>
        </div>

        {/* Command history */}
        <Panel>
          <PanelHeader
            title="Command requests"
            description={
              selectedDrone
                ? `For ${selectedDrone}. Pending requests await approval.`
                : "Select a drone to view its command history."
            }
          />

          {!selectedDrone ? (
            <UnavailableState
              title="No drone selected"
              detail="Command history is retrieved per drone. Choose one from the fleet list."
            />
          ) : commandsQuery.isLoading ? (
            <LoadingState rows={4} />
          ) : (
            <DataState
              isLoading={false}
              isError={commandsQuery.isError}
              error={commandsQuery.error}
              data={commandsQuery.data}
              onRetry={() => commandsQuery.refetch()}
              empty={
                <EmptyState
                  title="No commands requested"
                  detail={`Nothing has been requested for ${selectedDrone}.`}
                />
              }
            >
              {(commands) => (
                <ul className="divide-y divide-line-subtle">
                  {[...commands]
                    .sort(
                      (a, b) =>
                        new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
                    )
                    .map((command) => {
                      const pending = command.status.toUpperCase() === "PENDING";
                      const selfRequested = command.requested_by === user?.username;

                      return (
                        <li key={command.command_id} className="px-4 py-3">
                          <div className="flex flex-wrap items-start justify-between gap-2">
                            <div className="min-w-0">
                              <p className="text-[13px] font-medium text-content">
                                {humanizeEnum(command.command_type)}
                              </p>
                              <p className="mt-0.5 flex flex-wrap items-center gap-x-2.5 text-[11px] text-content-dim">
                                <Mono>#{command.command_id}</Mono>
                                <span>
                                  by <Mono className="text-content-muted">{command.requested_by}</Mono>
                                </span>
                                <span title={formatDateTime(command.created_at)}>
                                  {relativeTime(command.created_at)}
                                </span>
                              </p>
                            </div>
                            <Chip tone={commandStatusTone(command.status)}>
                              {humanizeEnum(command.status)}
                            </Chip>
                          </div>

                          {command.reason ? (
                            <p className="mt-1.5 text-[12px] text-content-muted">{command.reason}</p>
                          ) : null}

                          {command.approved_by ? (
                            <p className="mt-1.5 text-[11px] text-content-dim">
                              Decided by{" "}
                              <Mono className="text-content-muted">{command.approved_by}</Mono>
                              {command.approved_at ? ` ${relativeTime(command.approved_at)}` : ""}
                            </p>
                          ) : null}

                          {pending && canApprove ? (
                            selfRequested ? (
                              <p className="mt-2 text-[11px] text-warning">
                                You requested this command. A different authorised user must approve
                                it.
                              </p>
                            ) : (
                              <div className="mt-2.5 flex gap-2">
                                <Button
                                  size="sm"
                                  variant="primary"
                                  disabled={decide.isPending}
                                  onClick={() => decide.mutate({ command, approved: true })}
                                >
                                  Approve
                                </Button>
                                <Button
                                  size="sm"
                                  variant="danger"
                                  disabled={decide.isPending}
                                  onClick={() => decide.mutate({ command, approved: false })}
                                >
                                  Reject
                                </Button>
                              </div>
                            )
                          ) : pending ? (
                            <p className="mt-2 text-[11px] text-content-dim">
                              Awaiting approval from a user with the approval permission.
                            </p>
                          ) : null}
                        </li>
                      );
                    })}
                </ul>
              )}
            </DataState>
          )}
        </Panel>
      </div>
    </>
  );
}
