/**
 * Fleet roster and positions.
 *
 * Combines GET /drones (registry and status) with GET /telemetry/latest
 * (positions). A drone that is registered but has never reported telemetry
 * appears in the table with no position rather than being omitted.
 */

import { useCallback, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type Drone, type TelemetryRecord } from "@/services/api";
import { POLL_INTERVALS } from "@/config";
import { useWebSocketContext } from "@/contexts/WebSocketContext";
import { DroneMap } from "@/components/shared/DroneMap";
import { mergePositions, toMappedDrone, type MappedDrone } from "@/lib/telemetry";
import { DvrPlayback } from "@/components/shared/DvrPlayback";
import { GeofenceControlPanel } from "@/components/shared/GeofenceControlPanel";
import {
  DataState,
  EmptyState,
  ErrorState,
  LoadingState,
  PermissionDeniedState,
} from "@/components/ui/DataState";
import { FeedStatus } from "@/components/ui/FeedStatus";
import {
  Chip,
  Input,
  Mono,
  PageHeader,
  Panel,
  PanelHeader,
  Table,
  Td,
  Th,
} from "@/components/ui/primitives";
import { droneStatusTone } from "@/lib/constants";
import { humanizeEnum, latLon, num, relativeTime } from "@/lib/format";
import { hasPermission, Permissions } from "@/lib/rbac";
import { useAuth } from "@/hooks/useAuth";

export default function FleetPage() {
  const { user, role } = useAuth();
  const effectiveRole = user?.role ?? role;
  const { feedState, latestTelemetry } = useWebSocketContext();

  const canReadDrones = hasPermission(effectiveRole, Permissions.DRONE_READ);
  const canReadTelemetry = hasPermission(effectiveRole, Permissions.TELEMETRY_READ);

  const [filter, setFilter] = useState("");
  const [replayFrame, setReplayFrame] = useState<TelemetryRecord[] | null>(null);

  const dronesQuery = useQuery({
    queryKey: ["drones"],
    queryFn: () => api.getDrones(),
    refetchInterval: POLL_INTERVALS.fleet,
    enabled: canReadDrones,
  });

  const telemetryQuery = useQuery({
    queryKey: ["telemetry", "latest"],
    queryFn: () => api.getLatestTelemetry(),
    refetchInterval: POLL_INTERVALS.fleet,
    enabled: canReadTelemetry,
  });

  const handleFrameChange = useCallback((records: TelemetryRecord[] | null) => {
    setReplayFrame(records);
  }, []);

  /** Live positions: polled snapshot overlaid with socket frames, keyed by drone. */
  const livePositions = useMemo(
    () =>
      new Map<string, MappedDrone>(
        mergePositions(telemetryQuery.data ?? [], latestTelemetry).map((d) => [d.drone_id, d]),
      ),
    [telemetryQuery.data, latestTelemetry],
  );

  const replaying = replayFrame !== null;

  const mapDrones = useMemo<MappedDrone[]>(
    () => (replaying ? replayFrame.map(toMappedDrone) : [...livePositions.values()]),
    [replaying, replayFrame, livePositions],
  );

  const rows = useMemo(() => {
    const term = filter.trim().toLowerCase();
    return (dronesQuery.data ?? [])
      .filter(
        (d) =>
          !term ||
          d.drone_id.toLowerCase().includes(term) ||
          d.status.toLowerCase().includes(term),
      )
      .map((drone) => ({ drone, position: livePositions.get(drone.drone_id) ?? null }))
      .sort((a, b) => a.drone.drone_id.localeCompare(b.drone.drone_id));
  }, [dronesQuery.data, filter, livePositions]);

  if (!canReadDrones) {
    return (
      <>
        <PageHeader title="Fleet" />
        <Panel>
          <PermissionDeniedState />
        </Panel>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Fleet"
        description="Registered drones, their reported status, and current positions."
        actions={<FeedStatus state={feedState} />}
      />

      <div className="grid gap-4 xl:grid-cols-[1fr_340px]">
        <div className="flex flex-col gap-4">
          <Panel className="overflow-hidden">
            <PanelHeader
              title="Positions"
              description={
                replaying
                  ? "Showing recorded telemetry. Return the slider to Now for the live feed."
                  : "Latest reported position per drone."
              }
            />
            {!canReadTelemetry ? (
              <PermissionDeniedState compact />
            ) : telemetryQuery.isLoading ? (
              <LoadingState rows={6} />
            ) : telemetryQuery.isError ? (
              <ErrorState error={telemetryQuery.error} onRetry={() => telemetryQuery.refetch()} />
            ) : (
              <DroneMap
                drones={mapDrones}
                replayMode={replaying}
                className="h-[380px] w-full sm:h-[440px]"
              />
            )}
          </Panel>

          {canReadTelemetry ? <DvrPlayback onFrameChange={handleFrameChange} /> : null}

          <Panel>
            <PanelHeader
              title="Roster"
              description={`${rows.length} ${rows.length === 1 ? "drone" : "drones"}`}
              actions={
                <div className="w-full max-w-[200px]">
                  <label htmlFor="fleet-filter" className="sr-only">
                    Filter drones
                  </label>
                  <Input
                    id="fleet-filter"
                    type="search"
                    value={filter}
                    onChange={(e) => setFilter(e.target.value)}
                    placeholder="Filter"
                    className="h-7 py-1 text-[12px]"
                  />
                </div>
              }
            />

            <DataState
              isLoading={dronesQuery.isLoading}
              isError={dronesQuery.isError}
              error={dronesQuery.error}
              data={rows}
              onRetry={() => dronesQuery.refetch()}
              compact
              empty={
                <EmptyState
                  compact
                  icon="drone"
                  title={filter ? "No drones match that filter" : "No drones registered"}
                  detail={
                    filter
                      ? undefined
                      : "A drone is registered the first time it successfully sends telemetry."
                  }
                />
              }
            >
              {(list) => (
                <>
                  {/* Table on wide viewports */}
                  <div className="hidden md:block">
                    <Table>
                      <thead>
                        <tr>
                          <Th>Drone</Th>
                          <Th>Status</Th>
                          <Th>Position</Th>
                          <Th className="text-right">Battery</Th>
                          <Th className="text-right">Altitude</Th>
                          <Th>Last seen</Th>
                        </tr>
                      </thead>
                      <tbody>
                        {list.map(({ drone, position }) => (
                          <tr key={drone.id} className="transition-colors hover:bg-surface-overlay">
                            <Td>
                              <Mono className="text-content">{drone.drone_id}</Mono>
                            </Td>
                            <Td>
                              <Chip tone={droneStatusTone(drone.status)}>
                                {humanizeEnum(drone.status)}
                              </Chip>
                            </Td>
                            <Td>
                              <Mono className="text-content-muted">
                                {position ? latLon(position.latitude, position.longitude) : "—"}
                              </Mono>
                            </Td>
                            <Td className="text-right">
                              <Mono
                                className={
                                  typeof position?.battery === "number" && position.battery < 25
                                    ? "text-warning"
                                    : "text-content-muted"
                                }
                              >
                                {position?.battery === null || position?.battery === undefined
                                  ? "—"
                                  : `${num(position.battery, 0)}%`}
                              </Mono>
                            </Td>
                            <Td className="text-right">
                              <Mono className="text-content-muted">
                                {position?.altitude === null || position?.altitude === undefined
                                  ? "—"
                                  : `${num(position.altitude)} m`}
                              </Mono>
                            </Td>
                            <Td>
                              <span className="text-[12px] text-content-muted">
                                {relativeTime(drone.last_seen)}
                              </span>
                            </Td>
                          </tr>
                        ))}
                      </tbody>
                    </Table>
                  </div>

                  {/* Cards on narrow viewports */}
                  <ul className="divide-y divide-line-subtle md:hidden">
                    {list.map(({ drone, position }) => (
                      <li key={drone.id} className="px-4 py-3">
                        <div className="flex items-center justify-between gap-2">
                          <Mono className="text-[13px] text-content">{drone.drone_id}</Mono>
                          <Chip tone={droneStatusTone(drone.status)}>
                            {humanizeEnum(drone.status)}
                          </Chip>
                        </div>
                        <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1.5 text-[12px]">
                          <div className="col-span-2">
                            <dt className="text-content-dim">Position</dt>
                            <dd>
                              <Mono className="text-content-muted">
                                {position ? latLon(position.latitude, position.longitude) : "—"}
                              </Mono>
                            </dd>
                          </div>
                          <div>
                            <dt className="text-content-dim">Battery</dt>
                            <dd>
                              <Mono className="text-content-muted">
                                {position?.battery === null || position?.battery === undefined
                                  ? "—"
                                  : `${num(position.battery, 0)}%`}
                              </Mono>
                            </dd>
                          </div>
                          <div>
                            <dt className="text-content-dim">Last seen</dt>
                            <dd className="text-content-muted">{relativeTime(drone.last_seen)}</dd>
                          </div>
                        </dl>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </DataState>
          </Panel>
        </div>

        <div className="flex flex-col gap-4">
          <GeofenceControlPanel />
          <FleetStatusSummary drones={dronesQuery.data ?? []} />
        </div>
      </div>
    </>
  );
}

function FleetStatusSummary({ drones }: { drones: Drone[] }) {
  const counts = useMemo(() => {
    const map = new Map<string, number>();
    for (const drone of drones) {
      map.set(drone.status, (map.get(drone.status) ?? 0) + 1);
    }
    return [...map.entries()].sort((a, b) => b[1] - a[1]);
  }, [drones]);

  return (
    <Panel>
      <PanelHeader title="Status breakdown" />
      {counts.length === 0 ? (
        <EmptyState compact title="Nothing to summarise" />
      ) : (
        <ul className="divide-y divide-line-subtle">
          {counts.map(([status, count]) => (
            <li key={status} className="flex items-center justify-between gap-3 px-4 py-2.5">
              <Chip tone={droneStatusTone(status)}>{humanizeEnum(status)}</Chip>
              <Mono className="text-[13px] text-content">{count}</Mono>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
