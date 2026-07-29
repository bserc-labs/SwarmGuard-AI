import { useMemo, useState, useEffect } from "react";
import { MapContainer, Marker, Popup, TileLayer, Circle } from "react-leaflet";
import L from "leaflet";
import { GlassCard } from "./GlassCard";
import type { DroneMapLocation } from "@/lib/demoDroneLocations";
import { playCriticalSiren, toggleAudioAlarms, isAudioEnabled } from "@/utils/audioAlarms";

interface DroneMapProps {
  drones: DroneMapLocation[];
  className?: string;
}

const DEFAULT_CENTER: [number, number] = [34.0522, -118.2437]; // Los Angeles Base Sector
const DEFAULT_ZOOM = 12;

// Haversine formula to compute distance in meters between two points
function getDistanceMeters(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const R = 6371000;
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLon = ((lon2 - lon1) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos((lat1 * Math.PI) / 180) *
      Math.cos((lat2 * Math.PI) / 180) *
      Math.sin(dLon / 2) *
      Math.sin(dLon / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return R * c;
}

function createMarkerIcon(threatStatus?: string, isGeofenceBreach = false) {
  if (isGeofenceBreach || threatStatus === "Critical") {
    return L.divIcon({
      html: `<div style="background:#ef4444;width:18px;height:18px;border-radius:9999px;border:3px solid #ffffff;box-shadow:0 0 15px #ef4444;animation:pulse 1s infinite"></div>`,
      className: "bg-transparent border-none",
      iconSize: [18, 18],
      iconAnchor: [9, 9],
    });
  }

  const color = threatStatus === "Warning" ? "#f59e0b" : "#00d9ff";

  return L.divIcon({
    html: `<div style="background:${color};width:14px;height:14px;border-radius:9999px;border:2px solid white;box-shadow:0 0 10px ${color}"></div>`,
    className: "bg-transparent border-none",
    iconSize: [14, 14],
    iconAnchor: [7, 7],
  });
}

// Tactical Radar Sweep Icon
function createRadarIcon() {
  return L.divIcon({
    html: `<div class="radar-scan" style="width: 800px; height: 800px; border: 1px solid rgba(0, 217, 255, 0.15); border-radius: 50%; box-shadow: inset 0 0 40px rgba(0, 217, 255, 0.05);">
             <div style="position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); width: 6px; height: 6px; background: #00d9ff; border-radius: 50%; box-shadow: 0 0 10px #00d9ff;"></div>
             <div style="position: absolute; top: 50%; left: 0; right: 0; height: 1px; background: rgba(0, 217, 255, 0.1);"></div>
             <div style="position: absolute; top: 0; bottom: 0; left: 50%; width: 1px; background: rgba(0, 217, 255, 0.1);"></div>
             <div style="position: absolute; top: 25%; left: 25%; right: 25%; bottom: 25%; border: 1px solid rgba(0, 217, 255, 0.05); border-radius: 50%;"></div>
           </div>`,
    className: "bg-transparent border-none pointer-events-none",
    iconSize: [800, 800],
    iconAnchor: [400, 400],
  });
}

export function DroneMap({ drones, className = "" }: DroneMapProps) {
  const [audioActive, setAudioActive] = useState(isAudioEnabled());

  const validDrones = useMemo(() => {
    return drones.filter((drone) => {
      const hasLat = Number.isFinite(drone.latitude);
      const hasLng = Number.isFinite(drone.longitude);
      return hasLat && hasLng;
    });
  }, [drones]);

  const center = useMemo(() => {
    if (validDrones.length === 0) {
      return DEFAULT_CENTER;
    }
    const avgLat = validDrones.reduce((sum, drone) => sum + drone.latitude, 0) / validDrones.length;
    const avgLng = validDrones.reduce((sum, drone) => sum + drone.longitude, 0) / validDrones.length;
    return [avgLat, avgLng] as [number, number];
  }, [validDrones]);

  // Check for Geofence Breaches & Play Sirens
  const breaches = useMemo(() => {
    let breachCount = 0;
    validDrones.forEach((drone) => {
      const dist = getDistanceMeters(center[0], center[1], drone.latitude, drone.longitude);
      if (dist <= 800 || drone.threat_status === "Critical") {
        breachCount++;
      }
    });
    return breachCount;
  }, [validDrones, center]);

  useEffect(() => {
    if (breaches > 0 && audioActive) {
      playCriticalSiren();
    }
  }, [breaches, audioActive]);

  const handleToggleAudio = () => {
    const newState = toggleAudioAlarms();
    setAudioActive(newState);
  };

  return (
    <GlassCard className={`overflow-hidden p-0 ${className}`}>
      <div className="flex h-[480px] flex-col">
        <div className="border-b border-white/10 px-5 py-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold uppercase tracking-[0.25em] text-[#00d9ff] flex items-center gap-2">
                <span className="h-2 w-2 rounded-full bg-[#00d9ff] animate-ping" />
                🛰 Tactical Radar & Geofence Perimeter
              </h3>
              <p className="mt-1 text-xs text-sg-text-dim">Real-time Restricted Airspace Monitoring</p>
            </div>
            
            <div className="flex items-center gap-3">
              {breaches > 0 && (
                <span className="rounded-full bg-red-500/20 border border-red-500/40 px-3 py-1 text-[11px] font-mono text-red-400 animate-pulse">
                  🚨 {breaches} NO-FLY ZONE BREACHES
                </span>
              )}
              
              <button
                onClick={handleToggleAudio}
                className={`flex items-center gap-1.5 rounded-md px-3 py-1 text-[11px] font-mono border transition ${
                  audioActive
                    ? "bg-[#00d9ff]/10 border-[#00d9ff]/30 text-[#00d9ff]"
                    : "bg-white/5 border-white/10 text-sg-text-muted hover:bg-white/10"
                }`}
              >
                {audioActive ? "🔊 Sound FX: ON" : "🔇 Sound FX: OFF"}
              </button>

              <div className="rounded-full border border-white/10 bg-black/20 px-3 py-1 text-[11px] font-mono text-sg-text">
                {validDrones.length} active units
              </div>
            </div>
          </div>
        </div>

        {validDrones.length === 0 ? (
          <div className="flex flex-1 items-center justify-center px-6 text-center">
            <div>
              <p className="text-lg font-semibold text-sg-text">No drone telemetry streams active.</p>
              <p className="mt-2 text-sm text-sg-text-dim">Run simulate_attack.py to stream live virtual drones.</p>
            </div>
          </div>
        ) : (
          <div className="flex-1 min-h-0">
            <MapContainer
              center={center}
              zoom={DEFAULT_ZOOM}
              scrollWheelZoom
              className="h-full w-full"
            >
              <TileLayer
                attribution='&copy; <a href="https://carto.com/">CARTO</a> &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
              />

              {/* Radar Sweep Overlay */}
              <Marker position={center} icon={createRadarIcon()} interactive={false} />

              {/* Restricted Geofence Perimeters */}
              {/* Outer Amber Warning Sector (2000m) */}
              <Circle
                center={center}
                radius={2000}
                pathOptions={{ color: "#f59e0b", fillColor: "#f59e0b", fillOpacity: 0.04, dashArray: "4, 8", weight: 1.5 }}
              />

              {/* Inner Red Restricted No-Fly Zone (800m) */}
              <Circle
                center={center}
                radius={800}
                pathOptions={{ color: "#ef4444", fillColor: "#ef4444", fillOpacity: 0.12, dashArray: "6, 6", weight: 2 }}
              />

              {/* Render Drones */}
              {validDrones.map((drone) => {
                const distMeters = getDistanceMeters(center[0], center[1], drone.latitude, drone.longitude);
                const isBreach = distMeters <= 800;

                return (
                  <Marker
                    key={drone.drone_id}
                    position={[drone.latitude, drone.longitude]}
                    icon={createMarkerIcon(drone.threat_status, isBreach)}
                  >
                    <Popup>
                      <div className="min-w-[240px] space-y-2 text-sm text-sg-text font-mono">
                        <div className="border-b border-white/10 pb-2">
                          <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-[#00d9ff]">Unit Telemetry</p>
                          <p className="mt-1 font-bold text-sg-text flex items-center justify-between">
                            {drone.drone_id}
                            {isBreach && (
                              <span className="text-[10px] bg-red-500/20 text-red-400 border border-red-500/40 px-2 py-0.5 rounded">
                                BREACH
                              </span>
                            )}
                          </p>
                        </div>
                        <div className="grid gap-1.5 text-xs text-sg-text-dim">
                          <div className="flex items-center justify-between">
                            <span>Perimeter Range</span>
                            <span className={`font-bold ${isBreach ? "text-red-400" : "text-emerald-400"}`}>
                              {distMeters.toFixed(0)}m {isBreach ? "(RESTRICTED)" : "(CLEAR)"}
                            </span>
                          </div>
                          <div className="flex items-center justify-between">
                            <span>Coordinates</span>
                            <span className="text-sg-text">{drone.latitude.toFixed(4)}, {drone.longitude.toFixed(4)}</span>
                          </div>
                          <div className="flex items-center justify-between">
                            <span>Velocity</span>
                            <span className="text-sg-text">{drone.speed.toFixed(1)} m/s</span>
                          </div>
                          <div className="flex items-center justify-between">
                            <span>Altitude</span>
                            <span className="text-sg-text">{drone.altitude.toFixed(1)} m</span>
                          </div>
                          <div className="flex items-center justify-between">
                            <span>Threat Rating</span>
                            <span className={`font-bold ${drone.threat_status === "Critical" ? "text-red-400" : "text-sg-text"}`}>
                              {drone.threat_status ?? "NOMINAL"}
                            </span>
                          </div>
                        </div>
                      </div>
                    </Popup>
                  </Marker>
                );
              })}
            </MapContainer>
          </div>
        )}
      </div>
    </GlassCard>
  );
}
