/**
 * Per-drone telemetry inspection.
 *
 * Charts are drawn from GET /telemetry/{drone_id}, which is stored history. The
 * live socket updates the current-reading panel only, so the distinction between
 * "what the database holds" and "what just arrived" stays visible.
 */

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/services/api";
import { POLL_INTERVALS } from "@/config";
import { useWebSocketContext } from "@/contexts/WebSocketContext";
import { TelemetryChart, TELEMETRY_METRICS, type MetricKey } from "@/components/shared/TelemetryChart";
import { StatTile } from "@/components/shared/StatTile";
import {
  DataState,
  EmptyState,
  LoadingState,
  PermissionDeniedState,
  UnavailableState,
} from "@/components/ui/DataState";
import { FeedStatus } from "@/components/ui/FeedStatus";
import {
  Button,
  Mono,
  PageHeader,
  Panel,
  PanelBody,
  PanelHeader,
  Select,
} from "@/components/ui/primitives";
import { formatTime, latLon, num, relativeTime } from "@/lib/format";
import { hasPermission, Permissions } from "@/lib/rbac";
import { useAuth } from "@/hooks/useAuth";

const METRIC_ORDER: MetricKey[] = ["altitude", "speed", "battery", "satellites"];

export default function TelemetryPage() {
  const { user, role } = useAuth();
  const canRead = hasPermission(user?.role ?? role, Permissions.TELEMETRY_READ);
  const { feedState, latestTelemetry } = useWebSocketContext();

  // The operator's explicit choice. Null means "follow the first available",
  // which is derived below rather than written back by an effect.
  const [chosenDrone, setChosenDrone] = useState<string | null>(null);
  const [historyLimit, setHistoryLimit] = useState(200);

  const latestQuery = useQuery({
    queryKey: ["telemetry", "latest"],
    queryFn: () => api.getLatestTelemetry(),
    refetchInterval: POLL_INTERVALS.fleet,
    enabled: canRead,
  });

  const droneIds = useMemo(() => {
    const ids = new Set<string>();
    for (const record of latestQuery.data ?? []) ids.add(record.drone_id);
    for (const id of Object.keys(latestTelemetry)) ids.add(id);
    return [...ids].sort();
  }, [latestQuery.data, latestTelemetry]);

  /**
   * Effective selection: the operator's choice while it is still present in the
   * fleet, otherwise the first available drone. Deriving this means a drone that
   * disappears from the roster falls back cleanly without a render cascade.
   */
  const selectedDrone =
    chosenDrone !== null && droneIds.includes(chosenDrone)
      ? chosenDrone
      : (droneIds[0] ?? null);

  const historyQuery = useQuery({
    queryKey: ["telemetry", "history", selectedDrone, historyLimit],
    queryFn: () => api.getDroneTelemetry(selectedDrone as string, historyLimit),
    enabled: canRead && selectedDrone !== null,
    refetchInterval: POLL_INTERVALS.fleet,
  });

  /** Newest reading: prefer the socket frame, fall back to the stored row. */
  const current = useMemo(() => {
    if (!selectedDrone) return null;
    const live = latestTelemetry[selectedDrone];
    if (live) return { ...live, created_at: undefined, source: "live" as const };
    const stored = (latestQuery.data ?? []).find((r) => r.drone_id === selectedDrone);
    return stored ? { ...stored, source: "stored" as const } : null;
  }, [selectedDrone, latestTelemetry, latestQuery.data]);

  // History is returned newest-first; charts need oldest-first.
  const chronological = useMemo(
    () => [...(historyQuery.data ?? [])].reverse(),
    [historyQuery.data],
  );

  if (!canRead) {
    return (
      <>
        <PageHeader title="Telemetry" />
        <Panel>
          <PermissionDeniedState />
        </Panel>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Telemetry"
        description="Stored readings per drone, with the most recent values from the live feed."
        actions={<FeedStatus state={feedState} />}
      />

      {latestQuery.isLoading ? (
        <Panel>
          <LoadingState rows={5} />
        </Panel>
      ) : droneIds.length === 0 ? (
        <Panel>
          <EmptyState
            icon="activity"
            title="No telemetry available"
            detail="No drone in this organization has reported readings yet."
          />
        </Panel>
      ) : (
        <>
          <div className="mb-4 flex flex-wrap items-end gap-3">
            <div className="w-full max-w-xs">
              <label htmlFor="drone-select" className="mb-1.5 block text-[12px] font-medium text-content-muted">
                Drone
              </label>
              <Select
                id="drone-select"
                value={selectedDrone ?? ""}
                onChange={(e) => setChosenDrone(e.target.value)}
              >
                {droneIds.map((id) => (
                  <option key={id} value={id}>
                    {id}
                  </option>
                ))}
              </Select>
            </div>

            <div className="w-full max-w-[150px]">
              <label htmlFor="history-limit" className="mb-1.5 block text-[12px] font-medium text-content-muted">
                History depth
              </label>
              <Select
                id="history-limit"
                value={historyLimit}
                onChange={(e) => setHistoryLimit(Number(e.target.value))}
              >
                <option value={50}>50 packets</option>
                <option value={200}>200 packets</option>
                <option value={500}>500 packets</option>
              </Select>
            </div>

            <Button
              icon="refresh"
              size="sm"
              onClick={() => historyQuery.refetch()}
              loading={historyQuery.isFetching}
            >
              Refresh
            </Button>
          </div>

          {/* Current reading */}
          <section aria-label="Current reading" className="grid grid-cols-2 gap-2.5 lg:grid-cols-4">
            <StatTile
              label="Altitude"
              icon="gauge"
              value={current ? num(current.altitude) : null}
              unit="m"
            />
            <StatTile
              label="Speed"
              icon="activity"
              value={current ? num(current.speed) : null}
              unit="m/s"
            />
            <StatTile
              label="Battery"
              icon="battery"
              value={current ? num(current.battery, 0) : null}
              unit="%"
              tone={
                typeof current?.battery === "number" && current.battery < 25 ? "warning" : "neutral"
              }
            />
            <StatTile
              label="Satellites"
              icon="satellite"
              value={
                current?.satellites === null || current?.satellites === undefined
                  ? null
                  : current.satellites
              }
              tone={
                typeof current?.satellites === "number" && current.satellites < 6
                  ? "warning"
                  : "neutral"
              }
            />
          </section>

          {current ? (
            <Panel className="mt-2.5">
              <PanelBody className="flex flex-wrap items-center gap-x-5 gap-y-2 py-2.5 text-[12px]">
                <span className="text-content-dim">
                  Position <Mono className="ml-1 text-content-muted">{latLon(current.latitude, current.longitude)}</Mono>
                </span>
                <span className="text-content-dim">
                  Heading{" "}
                  <Mono className="ml-1 text-content-muted">
                    {current.heading === null || current.heading === undefined
                      ? "—"
                      : `${num(current.heading, 0)}°`}
                  </Mono>
                </span>
                <span className="text-content-dim">
                  Mode{" "}
                  <Mono className="ml-1 text-content-muted">{current.flight_mode ?? "—"}</Mono>
                </span>
                <span className="text-content-dim">
                  Armed{" "}
                  <span className="ml-1 text-content-muted">
                    {current.armed_status === null || current.armed_status === undefined
                      ? "—"
                      : current.armed_status
                        ? "Yes"
                        : "No"}
                  </span>
                </span>
                <span className="text-content-dim">
                  Sequence <Mono className="ml-1 text-content-muted">{current.packet_sequence}</Mono>
                </span>
                <span className="ml-auto text-content-dim">
                  {current.source === "live"
                    ? "From the live feed"
                    : `Stored ${relativeTime(current.created_at)}`}
                </span>
              </PanelBody>
            </Panel>
          ) : null}

          {/* Charts */}
          <div className="mt-4 grid gap-4 xl:grid-cols-2">
            {METRIC_ORDER.map((metric) => (
              <Panel key={metric}>
                <PanelHeader
                  title={TELEMETRY_METRICS[metric].label}
                  description={
                    TELEMETRY_METRICS[metric].unit
                      ? `Measured in ${TELEMETRY_METRICS[metric].unit}`
                      : undefined
                  }
                />
                <PanelBody className="px-2 pb-2 pt-3">
                  {historyQuery.isLoading ? (
                    <LoadingState rows={4} compact />
                  ) : historyQuery.isError ? (
                    <UnavailableState
                      compact
                      title="History unavailable"
                      detail="Stored telemetry for this drone could not be read."
                    />
                  ) : (
                    <TelemetryChart records={chronological} metric={metric} />
                  )}
                </PanelBody>
              </Panel>
            ))}
          </div>

          {/* Raw packets */}
          <Panel className="mt-4">
            <PanelHeader
              title="Recent packets"
              description={`Newest first, up to ${historyLimit}.`}
            />
            <DataState
              isLoading={historyQuery.isLoading}
              isError={historyQuery.isError}
              error={historyQuery.error}
              data={historyQuery.data}
              onRetry={() => historyQuery.refetch()}
              compact
              empty={<EmptyState compact title="No stored packets for this drone" />}
            >
              {(records) => (
                <div className="max-h-80 overflow-auto">
                  <table className="w-full border-collapse text-[12px]">
                    <thead className="sticky top-0 bg-surface-raised">
                      <tr>
                        <th scope="col" className="border-b border-line px-3 py-2 text-left text-[11px] font-semibold text-content-dim">
                          Time
                        </th>
                        <th scope="col" className="border-b border-line px-3 py-2 text-left text-[11px] font-semibold text-content-dim">
                          Position
                        </th>
                        <th scope="col" className="border-b border-line px-3 py-2 text-right text-[11px] font-semibold text-content-dim">
                          Alt
                        </th>
                        <th scope="col" className="border-b border-line px-3 py-2 text-right text-[11px] font-semibold text-content-dim">
                          Speed
                        </th>
                        <th scope="col" className="border-b border-line px-3 py-2 text-right text-[11px] font-semibold text-content-dim">
                          Battery
                        </th>
                        <th scope="col" className="border-b border-line px-3 py-2 text-right text-[11px] font-semibold text-content-dim">
                          Seq
                        </th>
                      </tr>
                    </thead>
                    <tbody className="font-mono tabular">
                      {records.slice(0, 100).map((record, index) => (
                        <tr
                          key={`${record.drone_id}-${record.packet_sequence}-${index}`}
                          className="hover:bg-surface-overlay"
                        >
                          <td className="border-b border-line-subtle px-3 py-1.5 text-content-muted">
                            {formatTime(record.created_at)}
                          </td>
                          <td className="border-b border-line-subtle px-3 py-1.5 text-content-muted">
                            {latLon(record.latitude, record.longitude)}
                          </td>
                          <td className="border-b border-line-subtle px-3 py-1.5 text-right text-content-muted">
                            {num(record.altitude)}
                          </td>
                          <td className="border-b border-line-subtle px-3 py-1.5 text-right text-content-muted">
                            {num(record.speed)}
                          </td>
                          <td className="border-b border-line-subtle px-3 py-1.5 text-right text-content-muted">
                            {num(record.battery, 0)}
                          </td>
                          <td className="border-b border-line-subtle px-3 py-1.5 text-right text-content-dim">
                            {record.packet_sequence}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </DataState>
          </Panel>
        </>
      )}
    </>
  );
}
