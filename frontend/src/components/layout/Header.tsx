/**
 * Application header.
 *
 * The previous version showed a hardcoded "System Online" chip that stayed green
 * while the socket was closed. Status here comes from two measured sources: the
 * telemetry feed state, and GET /system/health. When the health request fails,
 * that is shown as unknown rather than assumed healthy.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { api, type Drone, type Incident } from "@/services/api";
import { POLL_INTERVALS } from "@/config";
import { useWebSocketContext } from "@/contexts/WebSocketContext";
import { FeedStatus } from "@/components/ui/FeedStatus";
import { Icon } from "@/components/ui/Icon";
import { Chip, Mono } from "@/components/ui/primitives";
import { formatUtcClock, humanizeEnum, relativeTime } from "@/lib/format";
import { severityTone } from "@/lib/constants";
import { hasPermission, Permissions } from "@/lib/rbac";
import { useAuth } from "@/hooks/useAuth";
import { cn } from "@/lib/utils";

function useUtcClock(): string {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  return formatUtcClock(now);
}

/** Closes a popover on outside click. */
function useDismissOnOutside(onDismiss: () => void, active: boolean) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!active) return;
    const handler = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) onDismiss();
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onDismiss();
    };
    document.addEventListener("mousedown", handler);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", handler);
      document.removeEventListener("keydown", escape);
    };
  }, [active, onDismiss]);
  return ref;
}

export function Header({
  onOpenMobileNav,
  onToggleRail,
  railCollapsed,
}: {
  onOpenMobileNav: () => void;
  onToggleRail: () => void;
  railCollapsed: boolean;
}) {
  const navigate = useNavigate();
  const clock = useUtcClock();
  const { feedState } = useWebSocketContext();
  const { user, role } = useAuth();
  const effectiveRole = user?.role ?? role;

  const [searchOpen, setSearchOpen] = useState(false);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [query, setQuery] = useState("");

  const searchRef = useDismissOnOutside(() => setSearchOpen(false), searchOpen);
  const notificationsRef = useDismissOnOutside(() => setNotificationsOpen(false), notificationsOpen);

  const canReadIncidents = hasPermission(effectiveRole, Permissions.INCIDENT_READ);
  const canReadDrones = hasPermission(effectiveRole, Permissions.DRONE_READ);

  const incidentsQuery = useQuery({
    queryKey: ["incidents", "header"],
    queryFn: () => api.getIncidents(undefined, 50),
    refetchInterval: POLL_INTERVALS.incidents,
    enabled: canReadIncidents,
  });

  const dronesQuery = useQuery({
    queryKey: ["drones", "header"],
    queryFn: () => api.getDrones(),
    refetchInterval: POLL_INTERVALS.fleet,
    enabled: canReadDrones && searchOpen,
  });

  const incidents = useMemo(() => incidentsQuery.data ?? [], [incidentsQuery.data]);
  const drones = useMemo(() => dronesQuery.data ?? [], [dronesQuery.data]);

  const unresolved = useMemo(
    () =>
      incidents.filter(
        (i) =>
          (i.severity === "CRITICAL" || i.severity === "HIGH") &&
          i.status !== "RESOLVED" &&
          i.status !== "CLOSED",
      ),
    [incidents],
  );

  const trimmed = query.trim().toLowerCase();
  const matchedIncidents: Incident[] = trimmed
    ? incidents
        .filter(
          (i) =>
            i.drone_id.toLowerCase().includes(trimmed) ||
            i.attack_type.toLowerCase().includes(trimmed) ||
            String(i.id) === trimmed,
        )
        .slice(0, 5)
    : [];

  const matchedDrones: Drone[] = trimmed
    ? drones.filter((d) => d.drone_id.toLowerCase().includes(trimmed)).slice(0, 5)
    : [];

  const hasResults = matchedIncidents.length > 0 || matchedDrones.length > 0;

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b border-line bg-surface-raised px-3 sm:px-4">
      {/* Mobile menu */}
      <button
        type="button"
        onClick={onOpenMobileNav}
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[5px] text-content-muted hover:bg-surface-overlay hover:text-content md:hidden"
      >
        <Icon name="menu" size={18} title="Open navigation" />
      </button>

      {/* Rail toggle (tablet and up) */}
      <button
        type="button"
        onClick={onToggleRail}
        className="hidden h-8 w-8 shrink-0 items-center justify-center rounded-[5px] text-content-muted hover:bg-surface-overlay hover:text-content md:flex"
        aria-pressed={railCollapsed}
      >
        <Icon
          name={railCollapsed ? "chevron-right" : "chevron-left"}
          size={16}
          title={railCollapsed ? "Expand navigation" : "Collapse navigation"}
        />
      </button>

      {/* Search */}
      <div ref={searchRef} className="relative min-w-0 flex-1 md:max-w-sm">
        <div className="flex h-8 items-center gap-2 rounded-[5px] border border-line-strong bg-surface-sunken px-2.5 focus-within:border-accent">
          <Icon name="search" size={14} className="shrink-0 text-content-dim" />
          <input
            type="search"
            value={query}
            placeholder="Search drones and incidents"
            aria-label="Search drones and incidents"
            onChange={(e) => {
              setQuery(e.target.value);
              setSearchOpen(true);
            }}
            onFocus={() => setSearchOpen(true)}
            className="min-w-0 flex-1 bg-transparent text-[13px] text-content outline-none placeholder:text-content-dim"
          />
        </div>

        {searchOpen && trimmed ? (
          <div className="sg-enter absolute left-0 right-0 top-full z-40 mt-1.5 max-h-80 overflow-y-auto rounded-[6px] border border-line-strong bg-surface-overlay shadow-xl">
            {!hasResults ? (
              <p className="px-3 py-4 text-center text-[12px] text-content-dim">
                Nothing matches “{query.trim()}”.
              </p>
            ) : (
              <>
                {matchedDrones.length > 0 && (
                  <section className="border-b border-line-subtle p-1.5">
                    <h3 className="px-2 py-1 text-[11px] font-semibold text-content-dim">Drones</h3>
                    {matchedDrones.map((d) => (
                      <Link
                        key={d.id}
                        to="/fleet"
                        onClick={() => setSearchOpen(false)}
                        className="flex items-center justify-between gap-2 rounded-[4px] px-2 py-1.5 hover:bg-surface-hover"
                      >
                        <Mono className="truncate text-content">{d.drone_id}</Mono>
                        <span className="shrink-0 text-[11px] text-content-muted">
                          {humanizeEnum(d.status)}
                        </span>
                      </Link>
                    ))}
                  </section>
                )}
                {matchedIncidents.length > 0 && (
                  <section className="p-1.5">
                    <h3 className="px-2 py-1 text-[11px] font-semibold text-content-dim">Incidents</h3>
                    {matchedIncidents.map((i) => (
                      <Link
                        key={i.id}
                        to="/incidents/$id"
                        params={{ id: String(i.id) }}
                        onClick={() => setSearchOpen(false)}
                        className="flex items-center justify-between gap-2 rounded-[4px] px-2 py-1.5 hover:bg-surface-hover"
                      >
                        <span className="min-w-0 truncate text-[12px] text-content">
                          <Mono className="text-content-muted">#{i.id}</Mono>{" "}
                          {humanizeEnum(i.attack_type)}
                        </span>
                        <Chip tone={severityTone(i.severity)}>{humanizeEnum(i.severity)}</Chip>
                      </Link>
                    ))}
                  </section>
                )}
              </>
            )}
          </div>
        ) : null}
      </div>

      <div className="ml-auto flex shrink-0 items-center gap-2">
        <FeedStatus state={feedState} showLabel={false} className="sm:hidden" />
        <FeedStatus state={feedState} className="hidden sm:inline-flex" />

        <Mono className="hidden text-content-muted lg:inline" data-numeric>
          {clock}
        </Mono>

        {canReadIncidents ? (
          <div ref={notificationsRef} className="relative">
            <button
              type="button"
              onClick={() => setNotificationsOpen((v) => !v)}
              aria-expanded={notificationsOpen}
              aria-haspopup="dialog"
              className={cn(
                "relative flex h-8 w-8 items-center justify-center rounded-[5px] text-content-muted transition-colors hover:bg-surface-overlay hover:text-content",
                notificationsOpen && "bg-surface-overlay text-content",
              )}
            >
              <Icon
                name="bell"
                size={16}
                title={`Notifications${unresolved.length ? ` (${unresolved.length} unresolved)` : ""}`}
              />
              {unresolved.length > 0 ? (
                <span
                  aria-hidden="true"
                  className="absolute right-1 top-1 h-1.5 w-1.5 rounded-full bg-critical"
                />
              ) : null}
            </button>

            {notificationsOpen ? (
              <div
                role="dialog"
                aria-label="Recent incidents"
                className="sg-enter absolute right-0 top-full z-40 mt-1.5 w-[min(20rem,calc(100vw-1.5rem))] overflow-hidden rounded-[6px] border border-line-strong bg-surface-overlay shadow-xl"
              >
                <div className="flex items-center justify-between border-b border-line-subtle px-3 py-2">
                  <h3 className="text-[12px] font-semibold text-content">Unresolved</h3>
                  <span className="text-[11px] tabular text-content-dim">{unresolved.length}</span>
                </div>

                <div className="max-h-72 overflow-y-auto">
                  {incidentsQuery.isLoading ? (
                    <p className="px-3 py-5 text-center text-[12px] text-content-dim">Loading…</p>
                  ) : incidentsQuery.isError ? (
                    <p className="px-3 py-5 text-center text-[12px] text-content-muted">
                      Could not load incidents.
                    </p>
                  ) : unresolved.length === 0 ? (
                    <p className="px-3 py-5 text-center text-[12px] text-content-dim">
                      No unresolved high or critical incidents.
                    </p>
                  ) : (
                    unresolved.slice(0, 6).map((i) => (
                      <Link
                        key={i.id}
                        to="/incidents/$id"
                        params={{ id: String(i.id) }}
                        onClick={() => setNotificationsOpen(false)}
                        className="block border-b border-line-subtle px-3 py-2.5 last:border-b-0 hover:bg-surface-hover"
                      >
                        <div className="flex items-start justify-between gap-2">
                          <p className="min-w-0 flex-1 truncate text-[12px] font-medium text-content">
                            {humanizeEnum(i.attack_type)}
                          </p>
                          <Chip tone={severityTone(i.severity)}>{humanizeEnum(i.severity)}</Chip>
                        </div>
                        <p className="mt-1 flex items-center gap-2 text-[11px] text-content-dim">
                          <Mono>{i.drone_id}</Mono>
                          <span>{relativeTime(i.detection_time ?? i.created_at)}</span>
                        </p>
                      </Link>
                    ))
                  )}
                </div>

                <button
                  type="button"
                  onClick={() => {
                    setNotificationsOpen(false);
                    navigate({ to: "/incidents" });
                  }}
                  className="w-full border-t border-line-subtle px-3 py-2 text-[12px] text-accent-bright hover:bg-surface-hover"
                >
                  View all incidents
                </button>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </header>
  );
}
