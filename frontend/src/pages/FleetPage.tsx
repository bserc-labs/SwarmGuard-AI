import React, { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type TelemetryPacket } from "@/services/api";
import { GlassCard } from "@/components/shared/GlassCard";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";

function StatusPill({ battery, speed }: { battery: number; speed: number }) {
  let status = "Nominal";
  let color = "bg-[#00d9ff]/20 text-[#00d9ff] border-[#00d9ff]/30"; // primary cyan

  if (battery < 20 || speed > 25) {
    status = "Critical";
    color = "bg-[#ffb4ab]/20 text-[#ffb4ab] border-[#ffb4ab]/30"; // error red
  } else if (battery < 40 || speed > 20) {
    status = "Warning";
    color = "bg-[#ffdeaa]/20 text-[#ffdeaa] border-[#ffdeaa]/30"; // amber
  }

  return (
    <span
      className={`px-3 py-1 rounded-full text-xs font-semibold border ${color} uppercase tracking-wider`}
    >
      {status}
    </span>
  );
}

function BatteryBar({ battery }: { battery: number }) {
  let barColor = "bg-[#00d9ff]"; // green/cyan
  if (battery < 30) {
    barColor = "bg-[#ffb4ab]"; // red
  } else if (battery <= 60) {
    barColor = "bg-[#ffdeaa]"; // amber
  }

  return (
    <div className="w-full mt-2">
      <div className="flex justify-between text-xs text-[#bbc9ce] mb-1 font-['Courier_Prime']">
        <span>BATTERY</span>
        <span>{battery.toFixed(1)}%</span>
      </div>
      <div className="w-full h-2 bg-[#080f11] rounded overflow-hidden border border-[#ffffff14]">
        <div
          className={`h-full ${barColor} shadow-[0_0_8px_currentColor]`}
          style={{ width: `${Math.max(0, Math.min(100, battery))}%` }}
        ></div>
      </div>
    </div>
  );
}

export default function FleetPage() {
  const { data: telemetryData, isLoading, isError } = useQuery({
    queryKey: ["telemetry-live"],
    queryFn: () => api.getTelemetryLive(),
    refetchInterval: 10000,
  });

  const latestDrones = useMemo(() => {
    if (!telemetryData) return [];
    const map = new Map<string, TelemetryPacket>();
    // Assume telemetryData is an array of TelemetryPackets or we just take the last reading per drone_id
    // If it's an array:
    const dataArray = Array.isArray(telemetryData) ? telemetryData : [];
    for (const packet of dataArray) {
      map.set(packet.drone_id, packet);
    }
    return Array.from(map.values());
  }, [telemetryData]);

  return (
    <div className="p-8 max-w-7xl mx-auto text-[#dde4e6] font-['Inter'] min-h-screen bg-[#0e1417]">
      <div className="mb-8 flex items-center justify-between border-b border-[#ffffff14] pb-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight bg-clip-text text-transparent bg-gradient-to-r from-[#00d9ff] to-[#afecff]">
            Drone Fleet Overview
          </h1>
          <p className="text-[#859398] mt-1 text-sm font-['Courier_Prime']">
            LIVE TELEMETRY STREAM
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded-full bg-[#00d9ff] animate-pulse shadow-[0_0_10px_#00d9ff]"></div>
          <span className="text-[#00d9ff] text-sm font-semibold tracking-wider font-['Courier_Prime']">
            SYSTEM ONLINE
          </span>
        </div>
      </div>

      {isLoading && (
        <div className="flex justify-center items-center h-64">
          <LoadingSpinner />
        </div>
      )}

      {isError && (
        <div className="p-6 bg-[#ffb4ab]/10 border border-[#ffb4ab]/20 rounded-lg text-[#ffb4ab]">
          <h3 className="font-semibold text-lg flex items-center gap-2">
            <span className="material-symbols-outlined">error</span>
            Connection Lost
          </h3>
          <p className="text-sm mt-1">Unable to fetch live telemetry data. Retrying...</p>
        </div>
      )}

      {!isLoading && !isError && latestDrones.length === 0 && (
        <div className="flex flex-col items-center justify-center h-64 border border-dashed border-[#ffffff14] rounded-xl text-[#859398]">
          <span className="material-symbols-outlined text-4xl mb-2 opacity-50">flight_takeoff</span>
          <p>No drones currently active.</p>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {latestDrones.map((drone) => (
          <GlassCard key={drone.drone_id} className="relative overflow-hidden group">
            <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-transparent via-[#00d9ff] to-transparent opacity-0 group-hover:opacity-100 transition-opacity"></div>
            
            <div className="flex justify-between items-start mb-6">
              <div className="flex items-center gap-3">
                <span className="material-symbols-outlined text-[#afecff] text-2xl">rocket</span>
                <div>
                  <h3 className="font-bold text-lg text-[#dde4e6]">{drone.drone_id}</h3>
                  <p className="text-xs text-[#859398] font-['Courier_Prime']">UNIT ACTIVE</p>
                </div>
              </div>
              <StatusPill battery={drone.battery} speed={drone.speed} />
            </div>

            <div className="grid grid-cols-2 gap-4 mb-6">
              <div className="bg-[#080f11] p-3 rounded border border-[#ffffff0a]">
                <p className="text-[10px] text-[#bbc9ce] mb-1 font-['Courier_Prime']">SPEED</p>
                <div className="flex items-baseline gap-1">
                  <span className="text-xl font-semibold text-[#dde4e6]">{drone.speed.toFixed(1)}</span>
                  <span className="text-xs text-[#859398]">m/s</span>
                </div>
              </div>
              <div className="bg-[#080f11] p-3 rounded border border-[#ffffff0a]">
                <p className="text-[10px] text-[#bbc9ce] mb-1 font-['Courier_Prime']">ALTITUDE</p>
                <div className="flex items-baseline gap-1">
                  <span className="text-xl font-semibold text-[#dde4e6]">{drone.altitude.toFixed(1)}</span>
                  <span className="text-xs text-[#859398]">m</span>
                </div>
              </div>
            </div>

            <BatteryBar battery={drone.battery} />
          </GlassCard>
        ))}
      </div>
    </div>
  );
}
