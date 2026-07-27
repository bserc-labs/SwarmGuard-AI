import { useState, useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type Incident, type Drone } from "@/services/api";
import { Link, useNavigate } from "@tanstack/react-router";

export function Header() {
  const navigate = useNavigate();
  const [time, setTime] = useState(new Date());
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const interval = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(interval);
  }, []);

  // Close dropdowns on click outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsDropdownOpen(false);
      }
      if (searchRef.current && !searchRef.current.contains(event.target as Node)) {
        setIsSearchOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // Fetch recent incidents for notifications
  const { data: incidents = [] } = useQuery({
    queryKey: ["header-notifications"],
    queryFn: () => api.getIncidents(undefined, 50),
    refetchInterval: 10_000,
  });

  // Fetch drones for search
  const { data: drones = [] } = useQuery({
    queryKey: ["header-drones"],
    queryFn: () => api.getDrones(),
    refetchInterval: 10_000,
  });

  const utcString = time.toISOString().slice(11, 19);
  const unreadCount = incidents.filter(i => i.severity === "CRITICAL" || i.severity === "HIGH").length;

  // Search Results Filtering
  const filteredIncidents = searchQuery.trim()
    ? incidents.filter(
        i =>
          i.drone_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
          i.attack_type.toLowerCase().includes(searchQuery.toLowerCase()) ||
          i.explanation.toLowerCase().includes(searchQuery.toLowerCase())
      ).slice(0, 5)
    : [];

  const filteredDrones = searchQuery.trim()
    ? drones.filter(
        d =>
          d.drone_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
          d.status.toLowerCase().includes(searchQuery.toLowerCase())
      ).slice(0, 5)
    : [];

  const availableCommands = ["RETURN_TO_HOME", "EMERGENCY_LAND", "SWITCH_SAFE_MODE", "KILL_MOTOR", "RESUME_MISSION"];
  const filteredCommands = searchQuery.trim()
    ? availableCommands.filter(c => c.toLowerCase().includes(searchQuery.toLowerCase()))
    : [];

  const hasSearchResults = filteredIncidents.length > 0 || filteredDrones.length > 0 || filteredCommands.length > 0;

  return (
    <header className="h-16 border-b border-white/5 bg-sg-surface-dim/60 backdrop-blur-xl flex items-center justify-between px-6 sticky top-0 z-40">
      {/* Search */}
      <div className="relative flex-1 max-w-md" ref={searchRef}>
        <div className="flex items-center gap-3">
          <span className="material-symbols-outlined text-sg-text-dim text-xl">search</span>
          <input
            type="text"
            placeholder="Search commands, drones, incidents..."
            value={searchQuery}
            onChange={(e) => {
              setSearchQuery(e.target.value);
              setIsSearchOpen(true);
            }}
            onFocus={() => setIsSearchOpen(true)}
            className="bg-transparent border-none outline-none text-sm text-sg-text-muted placeholder:text-sg-text-dim/50 w-full"
          />
          {searchQuery && (
            <button onClick={() => setSearchQuery("")} className="text-sg-text-dim hover:text-white text-xs font-mono">
              CLEAR
            </button>
          )}
        </div>

        {/* Search Results Dropdown */}
        {isSearchOpen && searchQuery.trim() && (
          <div className="absolute left-0 right-0 mt-2 glass-card p-0 overflow-hidden animate-fade-in shadow-2xl z-50 max-h-96 overflow-y-auto">
            {!hasSearchResults ? (
              <div className="p-4 text-center text-sg-text-dim text-xs font-mono">
                No matching drones, commands, or incidents found
              </div>
            ) : (
              <div className="divide-y divide-white/5">
                {/* Drones */}
                {filteredDrones.length > 0 && (
                  <div className="p-2">
                    <div className="text-[10px] font-mono text-sg-primary px-2 py-1 uppercase tracking-wider font-semibold">
                      Drones
                    </div>
                    {filteredDrones.map(d => (
                      <Link
                        key={d.id}
                        to="/admin"
                        onClick={() => setIsSearchOpen(false)}
                        className="flex items-center justify-between p-2 hover:bg-white/5 rounded text-xs transition-colors"
                      >
                        <span className="font-mono font-semibold text-sg-text">{d.drone_id}</span>
                        <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-white/10 text-sg-primary">
                          {d.status}
                        </span>
                      </Link>
                    ))}
                  </div>
                )}

                {/* Commands */}
                {filteredCommands.length > 0 && (
                  <div className="p-2">
                    <div className="text-[10px] font-mono text-amber-400 px-2 py-1 uppercase tracking-wider font-semibold">
                      Tactical Commands
                    </div>
                    {filteredCommands.map(cmd => (
                      <Link
                        key={cmd}
                        to="/admin"
                        onClick={() => setIsSearchOpen(false)}
                        className="flex items-center justify-between p-2 hover:bg-white/5 rounded text-xs transition-colors"
                      >
                        <span className="font-mono text-amber-300 font-semibold">{cmd}</span>
                        <span className="text-[10px] font-mono text-sg-text-dim">Execute in Management</span>
                      </Link>
                    ))}
                  </div>
                )}

                {/* Incidents */}
                {filteredIncidents.length > 0 && (
                  <div className="p-2">
                    <div className="text-[10px] font-mono text-red-400 px-2 py-1 uppercase tracking-wider font-semibold">
                      Incidents
                    </div>
                    {filteredIncidents.map(inc => (
                      <Link
                        key={inc.id}
                        to="/incidents"
                        onClick={() => setIsSearchOpen(false)}
                        className="flex items-center justify-between p-2 hover:bg-white/5 rounded text-xs transition-colors"
                      >
                        <span className="font-mono text-sg-text truncate max-w-[200px]">
                          #{inc.id} {inc.attack_type} ({inc.drone_id})
                        </span>
                        <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-red-500/20 text-red-400">
                          {inc.severity}
                        </span>
                      </Link>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Right Section */}
      <div className="flex items-center gap-4">
        {/* System Status */}
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-500/10 border border-emerald-500/20">
          <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
          <span className="text-[10px] uppercase tracking-wider text-emerald-400 font-semibold">System Online</span>
        </div>

        {/* UTC Clock */}
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-white/3">
          <span className="material-symbols-outlined text-sg-text-dim text-base">schedule</span>
          <span className="text-xs font-mono text-sg-text-muted tracking-wider">{utcString} UTC</span>
        </div>

        {/* Notifications */}
        <div className="relative" ref={dropdownRef}>
          <button 
            onClick={() => setIsDropdownOpen(!isDropdownOpen)}
            className={`relative p-2 rounded-lg transition-colors ${isDropdownOpen ? 'bg-white/10' : 'hover:bg-white/5'}`}
          >
            <span className="material-symbols-outlined text-sg-text-muted text-xl">notifications</span>
            {unreadCount > 0 && (
              <span className="absolute top-1 right-1 w-2.5 h-2.5 bg-red-500 rounded-full animate-pulse border border-[#080f11]" />
            )}
          </button>

          {/* Dropdown Menu */}
          {isDropdownOpen && (
            <div className="absolute right-0 mt-2 w-80 glass-card p-0 overflow-hidden animate-fade-in shadow-2xl origin-top-right">
              <div className="px-4 py-3 border-b border-white/5 flex items-center justify-between bg-white/5">
                <span className="text-sm font-semibold tracking-wide text-sg-text">Notifications</span>
                {unreadCount > 0 && (
                  <span className="text-[10px] bg-red-500/20 text-red-400 px-2 py-0.5 rounded uppercase font-bold tracking-wider">
                    {unreadCount} Unread
                  </span>
                )}
              </div>
              
              <div className="max-h-96 overflow-y-auto">
                {!incidents || incidents.length === 0 ? (
                  <div className="p-6 text-center text-sg-text-dim text-sm">
                    No recent notifications
                  </div>
                ) : (
                  incidents.slice(0, 5).map((incident: Incident) => (
                    <div key={incident.id} className="p-3 border-b border-white/5 hover:bg-white/5 transition-colors cursor-pointer group">
                      <div className="flex items-start gap-3">
                        <span className={`material-symbols-outlined text-lg mt-0.5 ${incident.severity === 'CRITICAL' ? 'text-red-500' : incident.severity === 'HIGH' ? 'text-amber-500' : 'text-sg-primary'}`}>
                          {incident.severity === 'CRITICAL' ? 'warning' : 'info'}
                        </span>
                        <div className="flex-1 min-w-0">
                          <p className="text-xs font-semibold text-sg-text mb-1 truncate">{incident.attack_type}</p>
                          <p className="text-[11px] text-sg-text-muted line-clamp-2 leading-relaxed">
                            Anomaly detected on Drone ID: <span className="font-mono text-sg-primary">{incident.drone_id}</span>
                          </p>
                          <p className="text-[9px] text-sg-text-dim mt-2 uppercase tracking-wider">
                            {new Date(incident.created_at).toLocaleTimeString()}
                          </p>
                        </div>
                      </div>
                    </div>
                  ))
                )}
              </div>
              
              <div className="p-2 border-t border-white/5 bg-black/20">
                <Link 
                  to="/incidents" 
                  onClick={() => setIsDropdownOpen(false)}
                  className="block w-full text-center text-xs text-sg-primary hover:text-white transition-colors py-1.5 uppercase tracking-widest font-semibold"
                >
                  View All Incidents
                </Link>
              </div>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
