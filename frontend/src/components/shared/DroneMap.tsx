/**
 * Fleet map.
 *
 * Leaflet and react-leaflet are preserved, as are the geofence overlay and DVR
 * playback. Removed: the swarm-formation overlay (GET /telemetry/swarm-formation
 * does not exist on this backend and returned 404), the rotating radar sweep,
 * and the marker glow.
 *
 * Marker colour encodes battery and geofence state, both of which come from the
 * payload. Nothing on this map is inferred beyond the breach test, which is
 * computed here from real coordinates and real zone geometry.
 */

import { Fragment, useMemo, useState, type ReactNode } from "react";
import { Circle, MapContainer, Marker, Polygon, Popup, TileLayer } from "react-leaflet";
import { useQuery } from "@tanstack/react-query";
import L from "leaflet";
import { api, type GeofenceZone } from "@/services/api";
import { Chip, Mono } from "@/components/ui/primitives";
import { UnavailableState } from "@/components/ui/DataState";
import { formatTime, latLon, num } from "@/lib/format";
import { hasPlottablePosition, signalQuality, type MappedDrone } from "@/lib/telemetry";
import { cn } from "@/lib/utils";

/** Fallback view when no drone has reported a position. */
const FALLBACK_CENTER: [number, number] = [34.0522, -118.2437];
const FALLBACK_ZOOM = 11;

/* --------------------------------------------------------------- geometry */

/** Metres between two coordinates. Used for circular geofence containment. */
function haversineMetres(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const R = 6_371_000;
  const toRad = (deg: number) => (deg * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

/** Ray casting. Points are [lat, lng] pairs, matching the stored format. */
function pointInPolygon(lat: number, lng: number, polygon: [number, number][]): boolean {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const [latI, lngI] = polygon[i];
    const [latJ, lngJ] = polygon[j];
    const intersects =
      lngI > lng !== lngJ > lng &&
      lat < ((latJ - latI) * (lng - lngI)) / (lngJ - lngI) + latI;
    if (intersects) inside = !inside;
  }
  return inside;
}

type CircleZone = { kind: "circle"; center: [number, number]; radius: number };
type PolygonZone = { kind: "polygon"; points: [number, number][] };

/**
 * Coordinates are stored as an untyped JSON column, so the shape is validated
 * rather than asserted. A zone that does not parse is skipped, not guessed at.
 */
function parseZoneGeometry(zone: GeofenceZone): CircleZone | PolygonZone | null {
  const coords = zone.coordinates;

  if (zone.zone_type?.toUpperCase() === "CIRCLE") {
    if (typeof coords !== "object" || coords === null) return null;
    const c = coords as { center?: unknown; radius?: unknown };
    if (
      Array.isArray(c.center) &&
      c.center.length === 2 &&
      typeof c.center[0] === "number" &&
      typeof c.center[1] === "number" &&
      typeof c.radius === "number"
    ) {
      return { kind: "circle", center: [c.center[0], c.center[1]], radius: c.radius };
    }
    return null;
  }

  if (Array.isArray(coords)) {
    const points = coords.filter(
      (p): p is [number, number] =>
        Array.isArray(p) && p.length === 2 && typeof p[0] === "number" && typeof p[1] === "number",
    );
    return points.length >= 3 ? { kind: "polygon", points } : null;
  }

  return null;
}

function isBreaching(drone: MappedDrone, geometry: CircleZone | PolygonZone): boolean {
  if (geometry.kind === "circle") {
    return (
      haversineMetres(drone.latitude, drone.longitude, geometry.center[0], geometry.center[1]) <=
      geometry.radius
    );
  }
  return pointInPolygon(drone.latitude, drone.longitude, geometry.points);
}

/* ---------------------------------------------------------------- markers */

const MARKER_COLORS = {
  breach: "#e05a52",
  low: "#d99a3e",
  normal: "#4fa8c5",
  replay: "#7c8794",
} as const;

type MarkerTone = keyof typeof MARKER_COLORS;

/**
 * Aircraft marker.
 *
 * When the payload carries a heading the marker is a directional chevron
 * rotated to that bearing; without one it falls back to a plain dot. The two
 * shapes are visually distinct on purpose — an operator can tell at a glance
 * which aircraft are reporting attitude and which are not, rather than seeing a
 * north-pointing arrow that is actually just a default.
 */
function markerIcon(tone: MarkerTone, heading: number | null | undefined): L.DivIcon {
  const color = MARKER_COLORS[tone];
  const hasHeading =
    heading !== null && heading !== undefined && Number.isFinite(heading);

  if (!hasHeading) {
    return L.divIcon({
      html:
        `<span style="display:block;width:11px;height:11px;border-radius:9999px;` +
        `background:${color};border:2px solid #0f1214;box-shadow:0 0 0 1px ${color}"></span>`,
      className: "",
      iconSize: [11, 11],
      iconAnchor: [5.5, 5.5],
    });
  }

  const bearing = ((heading as number) % 360 + 360) % 360;
  return L.divIcon({
    html:
      `<svg width="22" height="22" viewBox="0 0 22 22" ` +
      `style="transform:rotate(${bearing}deg);transform-origin:50% 50%;display:block">` +
      `<path d="M11 2 L16.5 18 L11 14.4 L5.5 18 Z" fill="${color}" ` +
      `stroke="#0f1214" stroke-width="1.5" stroke-linejoin="round"/>` +
      `</svg>`,
    className: "",
    iconSize: [22, 22],
    iconAnchor: [11, 11],
  });
}

/* ------------------------------------------------------------------- view */

export function DroneMap({
  drones,
  replayMode = false,
  className,
}: {
  drones: MappedDrone[];
  /** True while showing recorded telemetry rather than the live feed. */
  replayMode?: boolean;
  className?: string;
}) {
  const [showZones, setShowZones] = useState(true);

  const zonesQuery = useQuery({
    queryKey: ["geofences"],
    queryFn: () => api.getGeofences(),
    refetchInterval: 30_000,
  });

  const zones = useMemo(
    () =>
      (zonesQuery.data ?? [])
        .filter((z) => z.is_active)
        .map((zone) => ({ zone, geometry: parseZoneGeometry(zone) }))
        .filter((z): z is { zone: GeofenceZone; geometry: CircleZone | PolygonZone } =>
          z.geometry !== null,
        ),
    [zonesQuery.data],
  );

  const positioned = useMemo(() => drones.filter(hasPlottablePosition), [drones]);

  const breaches = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const drone of positioned) {
      const hit = zones
        .filter(({ geometry }) => isBreaching(drone, geometry))
        .map(({ zone }) => zone.name);
      if (hit.length > 0) map.set(drone.drone_id, hit);
    }
    return map;
  }, [positioned, zones]);

  /** Zones that currently contain at least one aircraft. */
  const breachedZoneNames = useMemo(
    () => new Set([...breaches.values()].flat()),
    [breaches],
  );

  const center = useMemo<[number, number]>(() => {
    if (positioned.length === 0) return FALLBACK_CENTER;
    const lat = positioned.reduce((s, d) => s + d.latitude, 0) / positioned.length;
    const lng = positioned.reduce((s, d) => s + d.longitude, 0) / positioned.length;
    return [lat, lng];
  }, [positioned]);

  if (positioned.length === 0) {
    return (
      <div className={cn("flex items-center justify-center", className)}>
        <UnavailableState
          title="No positions to plot"
          detail="No drone in this organization has reported coordinates. The map appears once telemetry arrives."
        />
      </div>
    );
  }

  return (
    <div className={cn("relative", className)}>
      <MapContainer
        center={center}
        zoom={positioned.length === 1 ? 14 : FALLBACK_ZOOM}
        scrollWheelZoom
        className="h-full w-full"
        attributionControl
      >
        <TileLayer
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution="&copy; OpenStreetMap contributors"
        />

        {showZones &&
          zones.map(({ zone, geometry }) => {
            const critical = zone.severity?.toUpperCase() === "CRITICAL";
            const color = critical ? MARKER_COLORS.breach : MARKER_COLORS.low;

            // A zone currently containing an aircraft is emphasised: heavier
            // stroke, denser fill, and a dashed perimeter. Emphasis is earned by
            // a real containment test, never applied decoratively.
            const breached = breachedZoneNames.has(zone.name);
            const style = {
              color,
              weight: breached ? 3 : 1.5,
              fillColor: color,
              fillOpacity: breached ? 0.22 : 0.08,
              dashArray: breached ? "6 4" : undefined,
              className: breached ? "sg-zone-breached" : undefined,
            };

            return geometry.kind === "circle" ? (
              <Circle key={zone.id} center={geometry.center} radius={geometry.radius} pathOptions={style}>
                <Popup>
                  <ZonePopup zone={zone} breached={breached} />
                </Popup>
              </Circle>
            ) : (
              <Polygon key={zone.id} positions={geometry.points} pathOptions={style}>
                <Popup>
                  <ZonePopup zone={zone} breached={breached} />
                </Popup>
              </Polygon>
            );
          })}

        {positioned.map((drone) => {
          const breached = breaches.get(drone.drone_id);
          const tone: keyof typeof MARKER_COLORS = replayMode
            ? "replay"
            : breached
              ? "breach"
              : typeof drone.battery === "number" && drone.battery < 25
                ? "low"
                : "normal";

          return (
            <Marker
              key={drone.drone_id}
              position={[drone.latitude, drone.longitude]}
              icon={markerIcon(tone, drone.heading)}
            >
              <Popup>
                <DronePopup drone={drone} breachedZones={breached ?? null} />
              </Popup>
            </Marker>
          );
        })}
      </MapContainer>

      {/* Overlay controls sit above the Leaflet pane (z-index 400+). */}
      <div className="pointer-events-none absolute right-2.5 top-2.5 z-[500] flex flex-col items-end gap-1.5">
        <button
          type="button"
          onClick={() => setShowZones((v) => !v)}
          aria-pressed={showZones}
          className="pointer-events-auto rounded-control border border-line-strong bg-surface-overlay/95 px-2.5 py-1.5 text-[12px] text-content hover:bg-surface-hover"
        >
          {showZones ? "Hide zones" : "Show zones"}
          {zones.length > 0 ? (
            <span className="ml-1.5 tabular text-content-dim">{zones.length}</span>
          ) : null}
        </button>

        {replayMode ? (
          <span className="pointer-events-auto rounded-control border border-line-strong bg-surface-overlay/95 px-2.5 py-1.5 text-[12px] text-content-muted">
            Showing recorded telemetry
          </span>
        ) : null}

        {breaches.size > 0 ? (
          <span className="pointer-events-auto rounded-control border border-critical/40 bg-critical-wash/95 px-2.5 py-1.5 text-[12px] text-critical">
            {breaches.size} in restricted {breaches.size === 1 ? "zone" : "zones"}
          </span>
        ) : null}
      </div>
    </div>
  );
}

function ZonePopup({ zone, breached }: { zone: GeofenceZone; breached: boolean }) {
  return (
    <div className="flex flex-col gap-1 text-[12px]">
      <p className="font-semibold">{zone.name}</p>
      <div className="flex items-center gap-1.5">
        <Chip tone={zone.severity?.toUpperCase() === "CRITICAL" ? "critical" : "warning"}>
          {zone.severity?.toLowerCase() ?? "unspecified"}
        </Chip>
        <Mono className="text-content-dim">{zone.zone_type?.toLowerCase()}</Mono>
      </div>
      {breached ? (
        <p className="text-[11px] text-critical">One or more aircraft are inside this zone.</p>
      ) : null}
    </div>
  );
}

/** Telemetry card. Every field renders an em dash when the payload omits it. */
function DronePopup({
  drone,
  breachedZones,
}: {
  drone: MappedDrone;
  breachedZones: string[] | null;
}) {
  const quality = signalQuality(drone.satellites);
  const rows: Array<[string, ReactNode]> = [
    ["Position", <Mono key="p">{latLon(drone.latitude, drone.longitude)}</Mono>],
    [
      "Altitude",
      <Mono key="a">
        {drone.altitude === null || drone.altitude === undefined ? "—" : `${num(drone.altitude)} m`}
      </Mono>,
    ],
    [
      "Speed",
      <Mono key="s">
        {drone.speed === null || drone.speed === undefined ? "—" : `${num(drone.speed)} m/s`}
      </Mono>,
    ],
    [
      "Heading",
      <Mono key="h">
        {drone.heading === null || drone.heading === undefined
          ? "—"
          : `${num(drone.heading, 0)}°`}
      </Mono>,
    ],
    [
      "Battery",
      <Mono key="b" className={typeof drone.battery === "number" && drone.battery < 25 ? "text-warning" : undefined}>
        {drone.battery === null || drone.battery === undefined
          ? "—"
          : `${num(drone.battery, 0)}%`}
      </Mono>,
    ],
    [
      "Signal",
      quality === null ? (
        <span key="q" className="text-content-dim">Not reported</span>
      ) : (
        <span key="q" className="flex items-center gap-1.5">
          <Mono>{drone.satellites} sats</Mono>
          <Chip tone={quality === "good" ? "nominal" : quality === "fair" ? "accent" : "warning"}>
            {quality}
          </Chip>
        </span>
      ),
    ],
    ["Mode", <Mono key="m">{drone.flight_mode ?? "—"}</Mono>],
    [
      "Armed",
      <span key="ar">
        {drone.armed_status === null || drone.armed_status === undefined
          ? "—"
          : drone.armed_status
            ? "Yes"
            : "No"}
      </span>,
    ],
  ];

  if (drone.created_at) {
    rows.push(["Reported", <Mono key="t">{formatTime(drone.created_at)}</Mono>]);
  }

  return (
    <div className="flex min-w-[210px] flex-col gap-1.5 text-[12px]">
      <p className="font-mono text-[13px] font-semibold">{drone.drone_id}</p>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
        {rows.map(([label, value]) => (
          <Fragment key={label}>
            <dt className="text-content-dim">{label}</dt>
            <dd>{value}</dd>
          </Fragment>
        ))}
      </dl>
      {breachedZones ? (
        <p className="border-t border-line-subtle pt-1.5 text-[11px] text-critical">
          Inside restricted {breachedZones.length === 1 ? "zone" : "zones"}:{" "}
          {breachedZones.join(", ")}
        </p>
      ) : null}
    </div>
  );
}
