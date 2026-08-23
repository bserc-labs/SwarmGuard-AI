/**
 * Authenticated application shell.
 *
 * Layout responsibilities live here so pages never manage their own chrome:
 *   <768px   header + off-canvas drawer, content is full width
 *   >=768px  fixed icon rail, content offset by 56px
 *   >=1280px full sidebar, content offset by 232px
 *
 * The rail preference persists so an operator's choice survives navigation.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { Outlet } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { Sidebar } from "./Sidebar";
import { Header } from "./Header";
import { AlertBanner } from "@/components/AlertBanner";
import { TacticalShortcuts } from "@/components/shared/TacticalShortcuts";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { WebSocketProvider } from "@/contexts/WebSocketContext";
import { api } from "@/services/api";
import { POLL_INTERVALS } from "@/config";
import { hasPermission, Permissions } from "@/lib/rbac";
import { useAuth } from "@/hooks/useAuth";
import { cn } from "@/lib/utils";

const RAIL_STORAGE_KEY = "swarmguard_rail_collapsed";
const DESKTOP_QUERY = "(min-width: 1280px)";

function useRailCollapsed(): [boolean, () => void] {
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    try {
      const stored = localStorage.getItem(RAIL_STORAGE_KEY);
      if (stored !== null) return stored === "true";
    } catch {
      /* storage unavailable */
    }
    // Default: expanded on desktop, rail on tablet.
    return typeof window !== "undefined" ? !window.matchMedia(DESKTOP_QUERY).matches : false;
  });

  const toggle = useCallback(() => {
    setCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(RAIL_STORAGE_KEY, String(next));
      } catch {
        /* preference is session-only */
      }
      return next;
    });
  }, []);

  return [collapsed, toggle];
}

function LayoutInner() {
  const [railCollapsed, toggleRail] = useRailCollapsed();
  const [mobileOpen, setMobileOpen] = useState(false);
  const { user, role } = useAuth();
  const effectiveRole = user?.role ?? role;

  // Close the drawer when the viewport grows past the mobile breakpoint.
  useEffect(() => {
    const mql = window.matchMedia("(min-width: 768px)");
    const onChange = () => {
      if (mql.matches) setMobileOpen(false);
    };
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);

  const { data: incidents } = useQuery({
    queryKey: ["incidents", "badge"],
    queryFn: () => api.getIncidents(undefined, 100),
    refetchInterval: POLL_INTERVALS.incidents,
    enabled: hasPermission(effectiveRole, Permissions.INCIDENT_READ),
  });

  const criticalCount = useMemo(
    () =>
      (incidents ?? []).filter(
        (i) =>
          (i.severity === "CRITICAL" || i.severity === "HIGH") &&
          i.status !== "RESOLVED" &&
          i.status !== "CLOSED",
      ).length,
    [incidents],
  );

  return (
    <div className="min-h-screen bg-surface-base">
      <a href="#main-content" className="skip-link">
        Skip to main content
      </a>

      <Sidebar
        collapsed={railCollapsed}
        mobileOpen={mobileOpen}
        onMobileClose={() => setMobileOpen(false)}
        criticalCount={criticalCount}
      />

      <div
        className={cn(
          "flex min-h-screen flex-col transition-[padding] duration-150",
          railCollapsed ? "md:pl-14" : "md:pl-[232px]",
        )}
      >
        <Header
          onOpenMobileNav={() => setMobileOpen(true)}
          onToggleRail={toggleRail}
          railCollapsed={railCollapsed}
        />

        <AlertBanner />

        <main id="main-content" className="flex-1 px-3 py-4 sm:px-5 sm:py-5">
          <ErrorBoundary>
            <Outlet />
          </ErrorBoundary>
        </main>
      </div>

      {/* Global Alt+E / Alt+R / Alt+S. Renders nothing until a shortcut fires. */}
      <TacticalShortcuts />
    </div>
  );
}

export function AppLayout() {
  return (
    <WebSocketProvider>
      <LayoutInner />
    </WebSocketProvider>
  );
}
