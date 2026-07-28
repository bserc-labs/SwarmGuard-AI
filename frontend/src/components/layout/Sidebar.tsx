import { Link, useLocation, useNavigate } from "@tanstack/react-router";
import { useAuth } from "@/hooks/useAuth";
import { NAV_ITEMS, NAV_BOTTOM } from "@/lib/constants";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/services/api";

export function Sidebar() {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const { data: incidents } = useQuery({
    queryKey: ["incidents-count"],
    queryFn: () => api.getIncidents(undefined, 100),
    refetchInterval: 30_000,
  });

  const incidentCount = incidents?.filter((i) => i.severity === "CRITICAL" || i.severity === "HIGH").length ?? 0;

  return (
    <aside className="fixed top-0 left-0 h-screen w-[280px] bg-sg-surface-dim/80 backdrop-blur-xl border-r border-white/10 flex flex-col z-50">
      {/* Logo */}
      <div className="p-6 border-b border-white/5">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-sg-primary/10 border border-sg-primary/30 flex items-center justify-center primary-glow">
            <span className="material-symbols-outlined filled text-sg-primary text-xl">security</span>
          </div>
          <div>
            <h1 className="text-base font-bold tracking-tight text-sg-text">SwarmGuard</h1>
            <span className="text-[10px] uppercase tracking-[0.2em] text-sg-primary font-semibold">AI SENTINEL</span>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 py-4 px-3 space-y-1 overflow-y-auto">
        <span className="text-[10px] uppercase tracking-[0.15em] text-sg-text-dim font-semibold px-3 mb-2 block">Operations</span>
        {NAV_ITEMS.map((item) => {
          const isActive = location.pathname === item.path;
          return (
            <Link
              key={item.path}
              to={item.disabled ? "#" : item.path}
              className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-200 group
                ${isActive
                  ? "bg-sg-primary/10 text-sg-primary border-l-2 border-sg-primary"
                  : item.disabled
                    ? "text-sg-text-dim/50 cursor-not-allowed"
                    : "text-sg-text-muted hover:bg-white/5 hover:text-sg-text"
                }`}
            >
              <span className={`material-symbols-outlined text-xl ${isActive ? "filled text-sg-primary" : ""}`}>
                {item.icon}
              </span>
              <span className="flex-1">{item.label}</span>
              {item.badge && incidentCount > 0 && (
                <span className="bg-red-500/80 text-white text-[10px] font-bold px-1.5 py-0.5 rounded-full min-w-[18px] text-center animate-pulse-red">
                  {incidentCount}
                </span>
              )}
              {item.disabled && (
                <span className="text-[9px] uppercase tracking-wider text-sg-text-dim/40">Soon</span>
              )}
            </Link>
          );
        })}
      </nav>

      {/* Bottom */}
      <div className="border-t border-white/5 p-3 space-y-1">
        {NAV_BOTTOM.map((item) => (
          <Link
            key={item.path}
            to={item.disabled ? "#" : item.path}
            className="flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-sg-text-muted hover:bg-white/5 hover:text-sg-text transition-all"
          >
            <span className="material-symbols-outlined text-xl">{item.icon}</span>
            <span>{item.label}</span>
          </Link>
        ))}

        <button
          onClick={() => { logout(); navigate({ to: '/login' }); }}
          className="flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-red-400/80 hover:bg-red-500/10 hover:text-red-400 transition-all w-full"
        >
          <span className="material-symbols-outlined text-xl">logout</span>
          <span>Sign Out</span>
        </button>

        {/* User */}
        {user && (
          <div className="flex items-center gap-3 mt-3 px-3 py-2 rounded-lg bg-white/3">
            <div className="w-8 h-8 rounded-full bg-sg-primary/20 border border-sg-primary/30 flex items-center justify-center">
              <span className="text-xs font-bold text-sg-primary">{(user.username || "U")[0].toUpperCase()}</span>
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-xs font-semibold text-sg-text truncate">{user.username}</p>
              <p className="text-[10px] uppercase tracking-wider text-sg-primary">{user.role}</p>
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}
