import { useMemo } from "react";
import { MapContainer, Marker, Popup, TileLayer } from "react-leaflet";
import L from "leaflet";
import { GlassCard } from "./GlassCard";
import type { DroneMapLocation } from "@/lib/demoDroneLocations";

interface DroneMapProps {
  drones: DroneMapLocation[];
  className?: string;
}

const DEFAULT_CENTER: [number, number] = [18.5204, 73.8567];
const DEFAULT_ZOOM = 12;

function createMarkerIcon(threatStatus?: string) {
  const color = threatStatus === "Critical"
    ? "#ef4444"
    : threatStatus === "Warning"
      ? "#f59e0b"
      : "#3b82f6";

  return L.divIcon({
    html: `<div style="background:${color};width:14px;height:14px;border-radius:9999px;border:2px solid white;box-shadow:0 0 0 4px rgba(255,255,255,0.12)"></div>`,
    className: "bg-transparent border-none",
    iconSize: [14, 14],
    iconAnchor: [7, 7],
  });
}

export function DroneMap({ drones, className = "" }: DroneMapProps) {
  const validDrones = useMemo(() => {
    return drones.filter((drone) => {
      const hasLat = Number.isFinite(drone.latitude);
      const hasLng = Number.isFinite(drone.longitude);
      return hasLat && hasLng;
    });
  }, [drones]);

  const bounds = useMemo(() => {
    if (validDrones.length === 0) {
      return null;
    }

    const latitudes = validDrones.map((drone) => drone.latitude);
    const longitudes = validDrones.map((drone) => drone.longitude);

    return [
      [Math.min(...latitudes), Math.min(...longitudes)],
      [Math.max(...latitudes), Math.max(...longitudes)],
    ] as [[number, number], [number, number]];
  }, [validDrones]);

  const center = useMemo(() => {
    if (validDrones.length === 0) {
      return DEFAULT_CENTER;
    }

    const avgLat = validDrones.reduce((sum, drone) => sum + drone.latitude, 0) / validDrones.length;
    const avgLng = validDrones.reduce((sum, drone) => sum + drone.longitude, 0) / validDrones.length;
    return [avgLat, avgLng] as [number, number];
  }, [validDrones]);

  return (
    <GlassCard className={`overflow-hidden p-0 ${className}`}>
      <div className="flex h-[450px] flex-col">
        <div className="border-b border-white/10 px-5 py-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold uppercase tracking-[0.25em] text-sg-text-muted">🛰 Live Drone Map</h3>
              <p className="mt-1 text-sm text-sg-text-dim">Current drone locations</p>
            </div>
            <div className="rounded-full border border-white/10 bg-black/20 px-3 py-1 text-[11px] font-mono text-sg-text">
              {validDrones.length} drones
            </div>
          </div>
        </div>

        {validDrones.length === 0 ? (
          <div className="flex flex-1 items-center justify-center px-6 text-center">
            <div>
              <p className="text-lg font-semibold text-sg-text">No drone locations available.</p>
              <p className="mt-2 text-sm text-sg-text-dim">The current view is empty.</p>
            </div>
          </div>
        ) : (
          <div className="flex-1 min-h-0">
            <MapContainer
              center={center}
              zoom={DEFAULT_ZOOM}
              scrollWheelZoom
              className="h-full w-full"
              bounds={bounds ?? undefined}
              boundsOptions={{ padding: [24, 24] }}
            >
              <TileLayer
                attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              />

              {validDrones.map((drone) => (
                <Marker
                  key={drone.drone_id}
                  position={[drone.latitude, drone.longitude]}
                  icon={createMarkerIcon(drone.threat_status)}
                >
                  <Popup>
                    <div className="min-w-[220px] space-y-2 text-sm text-sg-text">
                      <div className="border-b border-white/10 pb-2">
                        <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-sg-text-muted">Drone Details</p>
                        <p className="mt-1 font-semibold text-sg-text">{drone.drone_id}</p>
                      </div>
                      <div className="grid gap-1 text-xs text-sg-text-dim">
                        <div className="flex items-center justify-between gap-3">
                          <span>Latitude</span>
                          <span className="font-mono text-sg-text">{drone.latitude.toFixed(4)}</span>
                        </div>
                        <div className="flex items-center justify-between gap-3">
                          <span>Longitude</span>
                          <span className="font-mono text-sg-text">{drone.longitude.toFixed(4)}</span>
                        </div>
                        <div className="flex items-center justify-between gap-3">
                          <span>Speed</span>
                          <span className="font-mono text-sg-text">{drone.speed.toFixed(1)} m/s</span>
                        </div>
                        <div className="flex items-center justify-between gap-3">
                          <span>Altitude</span>
                          <span className="font-mono text-sg-text">{drone.altitude.toFixed(1)} m</span>
                        </div>
                        <div className="flex items-center justify-between gap-3">
                          <span>Battery</span>
                          <span className="font-mono text-sg-text">{drone.battery.toFixed(1)}%</span>
                        </div>
                        <div className="flex items-center justify-between gap-3">
                          <span>Threat Status</span>
                          <span className="font-mono text-sg-text">{drone.threat_status ?? "Normal"}</span>
                        </div>
                        <div className="flex items-center justify-between gap-3">
                          <span>Last Updated</span>
                          <span className="font-mono text-sg-text">{drone.last_updated ? new Date(drone.last_updated).toLocaleString() : "N/A"}</span>
                        </div>
                      </div>
                    </div>
                  </Popup>
                </Marker>
              ))}
            </MapContainer>
          </div>
        )}
      </div>
    </GlassCard>
  );
}
