/**
 * Telemetry shapes shared between the map, the fleet table, and the dashboard.
 *
 * Kept out of the component modules so those stay fast-refresh clean and so the
 * adapter can be unit tested without rendering Leaflet.
 */

import type { TelemetryPacket, TelemetryRecord } from "@/services/api";

/** The minimum a view needs to plot a drone. */
export interface MappedDrone {
  drone_id: string;
  latitude: number;
  longitude: number;
  altitude?: number | null;
  speed?: number | null;
  battery?: number | null;
  /** Degrees clockwise from north. Absent when the source never reported it. */
  heading?: number | null;
  flight_mode?: string | null;
  armed_status?: boolean | null;
  satellites?: number | null;
  created_at?: string;
}

/** Adapts a stored telemetry row. */
export function toMappedDrone(record: TelemetryRecord): MappedDrone {
  return {
    drone_id: record.drone_id,
    latitude: record.latitude,
    longitude: record.longitude,
    altitude: record.altitude,
    speed: record.speed,
    battery: record.battery,
    heading: record.heading,
    flight_mode: record.flight_mode,
    armed_status: record.armed_status,
    satellites: record.satellites,
    created_at: record.created_at,
  };
}

/** Adapts a frame from the socket, which carries no storage metadata. */
export function packetToMappedDrone(packet: TelemetryPacket): MappedDrone {
  return {
    drone_id: packet.drone_id,
    latitude: packet.latitude,
    longitude: packet.longitude,
    altitude: packet.altitude,
    speed: packet.speed,
    battery: packet.battery,
    heading: packet.heading,
    flight_mode: packet.flight_mode,
    armed_status: packet.armed_status,
    satellites: packet.satellites,
  };
}

/**
 * Signal quality inferred from satellite count, per the usual GNSS bands.
 * Returns null when the source did not report satellites — the console must not
 * present an absent reading as a poor one.
 */
export type SignalQuality = "good" | "fair" | "poor" | "none";

export function signalQuality(satellites: number | null | undefined): SignalQuality | null {
  if (satellites === null || satellites === undefined || !Number.isFinite(satellites)) {
    return null;
  }
  if (satellites === 0) return "none";
  if (satellites < 6) return "poor";
  if (satellites < 10) return "fair";
  return "good";
}

/**
 * Merges a polled snapshot with live socket frames, keyed by drone.
 *
 * Socket frames win: they are newer than anything the last poll returned. This
 * is why a live position is never overwritten by a stale stored row.
 */
export function mergePositions(
  stored: TelemetryRecord[],
  live: Record<string, TelemetryPacket>,
): MappedDrone[] {
  const byId = new Map<string, MappedDrone>();
  for (const record of stored) byId.set(record.drone_id, toMappedDrone(record));
  for (const packet of Object.values(live)) {
    byId.set(packet.drone_id, packetToMappedDrone(packet));
  }
  return [...byId.values()];
}

/** True when the coordinates are usable on a map. */
export function hasPlottablePosition(drone: MappedDrone): boolean {
  return (
    Number.isFinite(drone.latitude) &&
    Number.isFinite(drone.longitude) &&
    Math.abs(drone.latitude) <= 90 &&
    Math.abs(drone.longitude) <= 180
  );
}
