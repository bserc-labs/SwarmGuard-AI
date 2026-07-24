import React, { useState } from "react";
import { GlassCard } from "@/components/shared/GlassCard";

interface MockDrone {
  id: string;
  firmware: string;
  status: "Online" | "Offline" | "Maintenance";
  uptime: string;
}

const MOCK_DRONES: MockDrone[] = [
  { id: "SGAI-Alpha-1", firmware: "v2.4.1", status: "Online", uptime: "14h 22m" },
  { id: "SGAI-Beta-2", firmware: "v2.4.1", status: "Online", uptime: "5h 10m" },
  { id: "SGAI-Gamma-3", firmware: "v2.3.9", status: "Maintenance", uptime: "-" },
  { id: "SGAI-Delta-4", firmware: "v2.4.1", status: "Offline", uptime: "-" },
  { id: "SGAI-Epsilon-5", firmware: "v2.4.1", status: "Online", uptime: "1h 05m" },
];

export default function AdminPage() {
  const [drones, setDrones] = useState<MockDrone[]>(MOCK_DRONES);

  const handleAction = (droneId: string, actionName: string) => {
    alert(`Initiated ${actionName} sequence for drone ${droneId}`);
  };

  const handleAddDrone = () => {
    alert("Add Drone configuration sequence initiated. Waiting for pairing...");
  };

  return (
    <div className="p-8 max-w-7xl mx-auto text-[#dde4e6] font-['Inter'] min-h-screen bg-[#0e1417]">
      <div className="mb-8 flex items-center justify-between border-b border-[#ffffff14] pb-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight bg-clip-text text-transparent bg-gradient-to-r from-[#00d9ff] to-[#afecff]">
            Drone Management & Control
          </h1>
          <p className="text-[#859398] mt-1 text-sm font-['Courier_Prime']">
            AUTHORIZED PERSONNEL ONLY
          </p>
        </div>
        <button
          onClick={handleAddDrone}
          className="bg-[#00d9ff]/10 hover:bg-[#00d9ff]/20 text-[#00d9ff] border border-[#00d9ff]/30 transition-all px-4 py-2 rounded flex items-center gap-2 text-sm font-semibold primary-glow"
        >
          <span className="material-symbols-outlined text-lg">add</span>
          Add New Drone
        </button>
      </div>

      <GlassCard className="p-0 overflow-hidden border-[#ffffff14]">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-[#080f11]/80 border-b border-[#ffffff14]">
                <th className="p-4 text-xs font-semibold text-[#bbc9ce] uppercase tracking-wider font-['Courier_Prime']">
                  Drone ID
                </th>
                <th className="p-4 text-xs font-semibold text-[#bbc9ce] uppercase tracking-wider font-['Courier_Prime']">
                  Firmware
                </th>
                <th className="p-4 text-xs font-semibold text-[#bbc9ce] uppercase tracking-wider font-['Courier_Prime']">
                  Status
                </th>
                <th className="p-4 text-xs font-semibold text-[#bbc9ce] uppercase tracking-wider font-['Courier_Prime'] text-right">
                  Tactical Commands
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#ffffff0a]">
              {drones.map((drone) => (
                <tr key={drone.id} className="hover:bg-[#ffffff05] transition-colors">
                  <td className="p-4">
                    <div className="flex items-center gap-3">
                      <span className="material-symbols-outlined text-[#859398]">
                        memory
                      </span>
                      <span className="font-medium text-[#dde4e6]">{drone.id}</span>
                    </div>
                  </td>
                  <td className="p-4 text-sm text-[#bbc9ce] font-['Courier_Prime']">
                    {drone.firmware}
                  </td>
                  <td className="p-4">
                    <span
                      className={`px-2 py-1 rounded text-xs font-medium border ${
                        drone.status === "Online"
                          ? "bg-[#00d9ff]/10 text-[#00d9ff] border-[#00d9ff]/20"
                          : drone.status === "Maintenance"
                          ? "bg-[#ffdeaa]/10 text-[#ffdeaa] border-[#ffdeaa]/20"
                          : "bg-[#859398]/10 text-[#859398] border-[#859398]/20"
                      }`}
                    >
                      {drone.status}
                    </span>
                  </td>
                  <td className="p-4 flex gap-2 justify-end">
                    <button
                      onClick={() => handleAction(drone.id, "RTH (Return to Base)")}
                      className="px-3 py-1.5 text-xs font-medium rounded bg-[#1a2123] border border-[#ffffff14] text-[#dde4e6] hover:bg-[#ffffff0a] hover:border-[#ffffff2a] transition-all flex items-center gap-1"
                      title="Return to Base"
                    >
                      <span className="material-symbols-outlined text-[14px]">home</span>
                      RTH
                    </button>
                    <button
                      onClick={() => handleAction(drone.id, "Reboot")}
                      className="px-3 py-1.5 text-xs font-medium rounded bg-[#1a2123] border border-[#ffffff14] text-[#dde4e6] hover:bg-[#ffffff0a] hover:border-[#ffffff2a] transition-all flex items-center gap-1"
                      title="Reboot System"
                    >
                      <span className="material-symbols-outlined text-[14px]">restart_alt</span>
                      Reboot
                    </button>
                    <button
                      onClick={() => handleAction(drone.id, "Emergency Land")}
                      className="px-3 py-1.5 text-xs font-medium rounded bg-[#ffb4ab]/10 border border-[#ffb4ab]/20 text-[#ffb4ab] hover:bg-[#ffb4ab]/20 hover:border-[#ffb4ab]/40 transition-all flex items-center gap-1"
                      title="Emergency Land"
                    >
                      <span className="material-symbols-outlined text-[14px]">warning</span>
                      E-Land
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </GlassCard>
    </div>
  );
}
