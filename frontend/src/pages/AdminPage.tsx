import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type Drone } from "@/services/api";
import { GlassCard } from "@/components/shared/GlassCard";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { toast } from 'sonner';
import { useAuth } from "@/hooks/useAuth";
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";

export default function AdminPage() {
  const { user, role } = useAuth();
  const queryClient = useQueryClient();
  const [newDroneId, setNewDroneId] = useState("");
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  const activeRole = (user?.role || role || "observer").toLowerCase();
  const isCommander = activeRole === "commander" || activeRole === "admin";

  // Fetch real drones from backend
  const { data: drones = [], isLoading, isError } = useQuery({
    queryKey: ["drones"],
    queryFn: () => api.getDrones(),
    refetchInterval: 5000,
  });

  // Issue command mutation
  const issueCmdMutation = useMutation({
    mutationFn: ({ droneId, cmd, reason }: { droneId: string; cmd: string; reason?: string }) =>
      api.issueCommand(droneId, cmd, reason),
    onSuccess: (data) => {
      setActionMessage(`✅ Command '${data.command_type}' issued to ${data.drone_id}`);
      queryClient.invalidateQueries({ queryKey: ["drones"] });
      setTimeout(() => setActionMessage(null), 4000);
      toast.success(`Command '${data.command_type}' issued to ${data.drone_id}`);
    },
    onError: (err: any) => {
      setActionMessage(`❌ Error: ${err.message}`);
      setTimeout(() => setActionMessage(null), 4000);
      toast.error(`Error: ${err.message}`);
    },
  });

  // Check heartbeats mutation
  const checkHeartbeatsMutation = useMutation({
    mutationFn: () => api.checkHeartbeats(),
    onSuccess: (data) => {
      setActionMessage(`📡 Heartbeat audit complete: ${data.silent_drones_detected} silent drone(s) detected.`);
      queryClient.invalidateQueries({ queryKey: ["drones"] });
      setTimeout(() => setActionMessage(null), 4000);
      toast.success(`Heartbeat audit complete: ${data.silent_drones_detected} silent drone(s) detected.`);
    },
  });

  useKeyboardShortcuts({
    enabled: isCommander,
    onEmergencyLand: () => {
      if (!isCommander) return;
      drones.forEach((d: Drone) => issueCmdMutation.mutate({ droneId: d.drone_id, cmd: "EMERGENCY_LAND", reason: "Shortcut override" }));
    },
    onReturnToHome: () => {
      if (!isCommander) return;
      drones.forEach((d: Drone) => issueCmdMutation.mutate({ droneId: d.drone_id, cmd: "RETURN_TO_HOME", reason: "Shortcut override" }));
    },
    onSafeMode: () => {
      if (!isCommander) return;
      drones.forEach((d: Drone) => issueCmdMutation.mutate({ droneId: d.drone_id, cmd: "SWITCH_SAFE_MODE", reason: "Shortcut override" }));
    }
  });

  const handleAddDrone = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newDroneId.trim() || !isCommander) return;
    issueCmdMutation.mutate({
      droneId: newDroneId.trim(),
      cmd: "RESUME_MISSION",
      reason: "Initial registration",
    });
    setNewDroneId("");
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "ACTIVE":
        return "bg-emerald-500/10 text-emerald-400 border-emerald-500/20";
      case "RETURNING":
        return "bg-cyan-500/10 text-cyan-400 border-cyan-500/20";
      case "SAFE_MODE":
        return "bg-amber-500/10 text-amber-400 border-amber-500/20";
      case "GROUNDED":
      case "SILENT_POSSIBLE_JAMMING":
        return "bg-red-500/10 text-red-400 border-red-500/20 animate-pulse";
      default:
        return "bg-gray-500/10 text-gray-400 border-gray-500/20";
    }
  };

  return (
    <div className="p-8 max-w-7xl mx-auto text-[#dde4e6] font-['Inter'] min-h-screen bg-[#0e1417]">
      {/* Header */}
      <div className="mb-8 flex flex-col md:flex-row md:items-center justify-between border-b border-[#ffffff14] pb-4 gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight bg-clip-text text-transparent bg-gradient-to-r from-[#00d9ff] to-[#afecff]">
            Drone Command & Tactical Control
          </h1>
          <p className="text-[#859398] mt-1 text-sm font-['Courier_Prime'] flex items-center gap-2">
            AUTHORIZED OPERATOR COMMAND CENTER • 
            <span className={`px-2 py-0.5 rounded font-mono text-xs border ${
              isCommander 
                ? "bg-cyan-500/20 border-cyan-500/40 text-cyan-300"
                : activeRole === "analyst"
                ? "bg-amber-500/20 border-amber-500/40 text-amber-300"
                : "bg-gray-500/20 border-gray-500/40 text-gray-300"
            }`}>
              {isCommander ? "🎖️ LEVEL 3: COMMANDER CLEARANCE" : activeRole === "analyst" ? "🔍 LEVEL 2: ANALYST CLEARANCE" : "👁️ LEVEL 1: OBSERVER CLEARANCE"}
            </span>
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={() => checkHeartbeatsMutation.mutate()}
            disabled={checkHeartbeatsMutation.isPending || !isCommander}
            className={`transition-all px-3 py-2 rounded flex items-center gap-2 text-xs font-semibold border ${
              isCommander
                ? "bg-amber-500/10 hover:bg-amber-500/20 text-amber-400 border-amber-500/30"
                : "bg-gray-500/10 text-gray-500 border-gray-500/20 cursor-not-allowed"
            }`}
          >
            <span className="material-symbols-outlined text-base">monitor_heart</span>
            Run Heartbeat Audit
          </button>
        </div>
      </div>

      {/* Action Notification Toast */}
      {actionMessage && (
        <div className="mb-6 p-4 rounded-lg bg-sg-surface border border-sg-primary/30 text-sm font-mono text-sg-primary animate-fade-in flex items-center justify-between">
          <span>{actionMessage}</span>
          <button onClick={() => setActionMessage(null)} className="text-sg-text-dim hover:text-white">✕</button>
        </div>
      )}

      {/* Add New Drone Form */}
      <GlassCard className="mb-6 p-4 border-[#ffffff14]">
        <form onSubmit={handleAddDrone} className="flex items-center gap-3">
          <span className="material-symbols-outlined text-sg-primary">add_circle</span>
          <input
            type="text"
            placeholder="Enter new Drone ID (e.g. drone_delta)..."
            value={newDroneId}
            onChange={(e) => setNewDroneId(e.target.value)}
            className="bg-black/30 border border-white/10 rounded px-3 py-2 text-sm font-mono text-sg-text focus:outline-none focus:border-sg-primary flex-1"
          />
          <button
            type="submit"
            className="bg-sg-primary/20 hover:bg-sg-primary/30 text-sg-primary border border-sg-primary/40 px-4 py-2 rounded text-xs font-semibold font-mono tracking-wider transition-all"
          >
            REGISTER DRONE
          </button>
        </form>
      </GlassCard>

      {/* Drones Table */}
      <GlassCard className="p-0 overflow-hidden border-[#ffffff14]">
        <div className="overflow-x-auto">
          {isLoading ? (
            <div className="p-12 flex justify-center"><LoadingSpinner /></div>
          ) : isError ? (
            <div className="p-8 text-center text-red-400 font-mono">Failed to load drones from backend</div>
          ) : drones.length === 0 ? (
            <div className="p-12 text-center text-sg-text-dim font-mono">
              No registered drones found. Send telemetry data or register a drone above.
            </div>
          ) : (
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="bg-[#080f11]/80 border-b border-[#ffffff14]">
                  <th className="p-4 text-xs font-semibold text-[#bbc9ce] uppercase tracking-wider font-['Courier_Prime']">
                    Drone ID
                  </th>
                  <th className="p-4 text-xs font-semibold text-[#bbc9ce] uppercase tracking-wider font-['Courier_Prime']">
                    Status
                  </th>
                  <th className="p-4 text-xs font-semibold text-[#bbc9ce] uppercase tracking-wider font-['Courier_Prime']">
                    Last Command
                  </th>
                  <th className="p-4 text-xs font-semibold text-[#bbc9ce] uppercase tracking-wider font-['Courier_Prime']">
                    Last Seen
                  </th>
                  <th className="p-4 text-xs font-semibold text-[#bbc9ce] uppercase tracking-wider font-['Courier_Prime'] text-right">
                    Tactical Override Commands
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#ffffff0a]">
                {drones.map((drone: Drone) => (
                  <tr key={drone.id} className="hover:bg-[#ffffff05] transition-colors">
                    <td className="p-4">
                      <div className="flex items-center gap-3">
                        <span className="material-symbols-outlined text-[#859398]">flight</span>
                        <span className="font-medium text-[#dde4e6] font-mono">{drone.drone_id}</span>
                      </div>
                    </td>
                    <td className="p-4">
                      <span className={`px-2.5 py-1 rounded text-xs font-mono font-semibold border ${getStatusBadge(drone.status)}`}>
                        {drone.status}
                      </span>
                    </td>
                    <td className="p-4 text-sm text-[#bbc9ce] font-mono">
                      {drone.last_command || "NONE"}
                    </td>
                    <td className="p-4 text-xs text-[#859398] font-mono">
                      {new Date(drone.last_seen).toLocaleTimeString()}
                    </td>
                    <td className="p-4 flex gap-2 justify-end">
                      {isCommander ? (
                        <>
                          <button
                            onClick={() => issueCmdMutation.mutate({ droneId: drone.drone_id, cmd: "RETURN_TO_HOME", reason: "Operator tactical override" })}
                            className="px-3 py-1.5 text-xs font-medium rounded bg-[#1a2123] border border-[#ffffff14] text-cyan-400 hover:bg-cyan-500/20 hover:border-cyan-500/40 transition-all flex items-center gap-1 font-mono"
                            title="Return to Base"
                          >
                            <span className="material-symbols-outlined text-[14px]">home</span>
                            RTH
                          </button>
                          <button
                            onClick={() => issueCmdMutation.mutate({ droneId: drone.drone_id, cmd: "SWITCH_SAFE_MODE", reason: "Operator risk mitigation" })}
                            className="px-3 py-1.5 text-xs font-medium rounded bg-[#1a2123] border border-[#ffffff14] text-amber-400 hover:bg-amber-500/20 hover:border-amber-500/40 transition-all flex items-center gap-1 font-mono"
                            title="Switch to Safe Mode"
                          >
                            <span className="material-symbols-outlined text-[14px]">security</span>
                            Safe Mode
                          </button>
                          <button
                            onClick={() => issueCmdMutation.mutate({ droneId: drone.drone_id, cmd: "EMERGENCY_LAND", reason: "Emergency landing forced" })}
                            className="px-3 py-1.5 text-xs font-medium rounded bg-red-500/10 border border-red-500/20 text-red-400 hover:bg-red-500/20 hover:border-red-500/40 transition-all flex items-center gap-1 font-mono"
                            title="Emergency Land"
                          >
                            <span className="material-symbols-outlined text-[14px]">warning</span>
                            E-Land
                          </button>
                        </>
                      ) : (
                        <span className="px-3 py-1.5 text-xs font-mono text-gray-500 bg-gray-500/10 border border-gray-500/20 rounded flex items-center gap-1">
                          <span className="material-symbols-outlined text-[14px]">lock</span>
                          COMMANDER CLEARANCE REQUIRED
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </GlassCard>

      {/* Keyboard Shortcuts Help */}
      <GlassCard className="mt-6 p-4 border-[#ffffff14]">
        <h3 className="text-sm font-semibold text-[#00d9ff] uppercase tracking-wider font-['Courier_Prime'] mb-3">
          <span className="material-symbols-outlined align-middle mr-2 text-[18px]">keyboard</span>
          Keyboard Shortcuts
        </h3>
        <div className="flex flex-wrap gap-6 text-sm font-mono text-[#bbc9ce]">
          <div className="flex items-center"><span className="text-[#dde4e6] font-bold bg-[#ffffff14] px-1.5 py-0.5 rounded mr-2">Alt + E</span> Emergency Land All</div>
          <div className="flex items-center"><span className="text-[#dde4e6] font-bold bg-[#ffffff14] px-1.5 py-0.5 rounded mr-2">Alt + R</span> Return To Home All</div>
          <div className="flex items-center"><span className="text-[#dde4e6] font-bold bg-[#ffffff14] px-1.5 py-0.5 rounded mr-2">Alt + S</span> Safe Mode All</div>
        </div>
      </GlassCard>
    </div>
  );
}
