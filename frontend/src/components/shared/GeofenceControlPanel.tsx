import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/services/api";

export function GeofenceControlPanel() {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [radius, setRadius] = useState(800);

  const { data: zones = [], isLoading } = useQuery({
    queryKey: ['geofences'],
    queryFn: () => api.getGeofences(),
  });

  const createMutation = useMutation({
    mutationFn: (newZone: any) => api.createGeofence(newZone),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['geofences'] });
      setName("");
    },
  });

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    
    // Defaulting to a CIRCLE at the Los Angeles base center
    createMutation.mutate({
      name,
      zone_type: "CIRCLE",
      coordinates: { center: [34.0522, -118.2437], radius },
      severity: "CRITICAL"
    });
  };

  return (
    <div className="absolute top-16 left-4 z-[400] w-72 bg-black/80 backdrop-blur-md border border-[#00d9ff]/30 rounded-lg shadow-[0_0_15px_rgba(0,217,255,0.2)] p-4 font-mono text-xs">
      <div className="flex items-center gap-2 mb-3 border-b border-white/10 pb-2">
        <span className="h-2 w-2 rounded-full bg-[#ef4444] animate-pulse" />
        <h3 className="uppercase tracking-widest text-[#00d9ff] font-bold">Autonomous Defense</h3>
      </div>
      
      <form onSubmit={handleCreate} className="space-y-3 mb-4">
        <div>
          <label className="block text-[10px] text-sg-text-dim uppercase tracking-wider mb-1">Zone Name</label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Sector Alpha"
            className="w-full bg-black/50 border border-white/10 rounded px-2 py-1.5 text-sg-text focus:border-[#00d9ff] focus:outline-none transition-colors"
          />
        </div>
        <div>
          <label className="block text-[10px] text-sg-text-dim uppercase tracking-wider mb-1">Radius (meters)</label>
          <input
            type="number"
            value={radius}
            onChange={(e) => setRadius(Number(e.target.value))}
            className="w-full bg-black/50 border border-white/10 rounded px-2 py-1.5 text-sg-text focus:border-[#00d9ff] focus:outline-none transition-colors"
          />
        </div>
        <button
          type="submit"
          disabled={createMutation.isPending || !name}
          className="w-full bg-[#ef4444]/20 hover:bg-[#ef4444]/40 border border-[#ef4444]/50 text-[#ef4444] rounded py-1.5 font-bold uppercase tracking-wider transition-colors disabled:opacity-50"
        >
          {createMutation.isPending ? "Deploying..." : "Deploy Kill-Zone"}
        </button>
      </form>

      <div className="space-y-2">
        <label className="block text-[10px] text-sg-text-dim uppercase tracking-wider border-b border-white/10 pb-1">Active Kill-Zones</label>
        {isLoading ? (
          <div className="text-sg-text-dim italic">Scanning perimeter...</div>
        ) : zones.length === 0 ? (
          <div className="text-sg-text-dim italic">No restricted zones active.</div>
        ) : (
          zones.map((zone: any) => (
            <div key={zone.id} className="flex items-center justify-between bg-black/40 border border-red-500/30 p-2 rounded">
              <div>
                <div className="text-[#ef4444] font-bold">{zone.name}</div>
                <div className="text-[9px] text-sg-text-muted">{zone.zone_type} - {zone.coordinates?.radius}m</div>
              </div>
              <div className="h-1.5 w-1.5 rounded-full bg-red-500 animate-ping" />
            </div>
          ))
        )}
      </div>
    </div>
  );
}
