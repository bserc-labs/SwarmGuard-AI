/**
 * Primary navigation.
 *
 * One component serves three layouts:
 *   desktop (>=1280px)  full 232px sidebar with labels
 *   tablet  (768-1279)  56px icon rail, labels via tooltip and screen readers
 *   mobile  (<768px)    off-canvas drawer with a focus trap and Escape to close
 *
 * Destinations the current role cannot use are omitted rather than shown
 * disabled — an operator should not be offered a page that will refuse them.
 */

import { useEffect, useRef } from "react";
import { Link, useLocation } from "@tanstack/react-router";
import { NAV_PRIMARY, NAV_SECONDARY, visibleNavItems, type NavItem } from "@/lib/constants";
import { useAuth } from "@/hooks/useAuth";
import { Icon } from "@/components/ui/Icon";
import { cn } from "@/lib/utils";

interface SidebarProps {
  /** Rail mode collapses to icons only (tablet). */
  collapsed: boolean;
  /** Drawer open state (mobile only). */
  mobileOpen: boolean;
  onMobileClose: () => void;
  criticalCount: number;
}

function NavLink({
  item,
  isActive,
  collapsed,
  badgeCount,
  onNavigate,
}: {
  item: NavItem;
  isActive: boolean;
  collapsed: boolean;
  badgeCount: number;
  onNavigate?: () => void;
}) {
  const showBadge = item.badge && badgeCount > 0;

  return (
    <Link
      to={item.path}
      onClick={onNavigate}
      aria-current={isActive ? "page" : undefined}
      title={collapsed ? item.label : undefined}
      className={cn(
        "group relative flex items-center rounded-[5px] text-[13px] font-medium transition-colors",
        collapsed ? "h-9 w-9 justify-center" : "h-9 gap-2.5 px-2.5",
        isActive
          ? "bg-accent-wash text-accent-bright"
          : "text-content-muted hover:bg-surface-overlay hover:text-content",
      )}
    >
      {/* Active marker: a rail, not a glow. */}
      {isActive ? (
        <span
          aria-hidden="true"
          className="absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-r bg-accent"
        />
      ) : null}

      <Icon name={item.icon} size={16} className="shrink-0" />

      {collapsed ? (
        <span className="sr-only">{item.label}</span>
      ) : (
        <span className="flex-1 truncate">{item.label}</span>
      )}

      {showBadge ? (
        <span
          className={cn(
            "rounded-[3px] bg-critical-wash px-1 text-[11px] font-semibold tabular text-critical",
            collapsed && "absolute -right-0.5 -top-0.5 px-1 py-0 leading-tight",
          )}
        >
          {badgeCount > 99 ? "99+" : badgeCount}
          <span className="sr-only"> unresolved high or critical incidents</span>
        </span>
      ) : null}
    </Link>
  );
}

function SidebarContent({
  collapsed,
  criticalCount,
  onNavigate,
}: {
  collapsed: boolean;
  criticalCount: number;
  onNavigate?: () => void;
}) {
  const location = useLocation();
  const { user, role, logout } = useAuth();
  const effectiveRole = user?.role ?? role;

  const primary = visibleNavItems(NAV_PRIMARY, effectiveRole);
  const secondary = visibleNavItems(NAV_SECONDARY, effectiveRole);

  const isActivePath = (path: string) =>
    location.pathname === path || location.pathname.startsWith(`${path}/`);

  return (
    <div className="flex h-full flex-col bg-surface-raised">
      {/* Identity */}
      <div
        className={cn(
          "flex h-14 shrink-0 items-center border-b border-line",
          collapsed ? "justify-center px-2" : "gap-2.5 px-3",
        )}
      >
        <img
          src="/logo.png"
          alt=""
          className="h-7 w-7 shrink-0 rounded-[5px] border border-line-strong object-cover"
        />
        {!collapsed && (
          <div className="min-w-0">
            <p className="truncate text-[13px] font-semibold leading-tight text-content">SwarmGuard</p>
            <p className="truncate text-[11px] leading-tight text-content-dim">
              UAV telemetry security
            </p>
          </div>
        )}
      </div>

      <nav
        aria-label="Primary"
        className={cn("flex-1 overflow-y-auto py-3", collapsed ? "px-2" : "px-2.5")}
      >
        <ul className="flex flex-col gap-0.5">
          {primary.map((item) => (
            <li key={item.path}>
              <NavLink
                item={item}
                isActive={isActivePath(item.path)}
                collapsed={collapsed}
                badgeCount={criticalCount}
                onNavigate={onNavigate}
              />
            </li>
          ))}
        </ul>
      </nav>

      <div className={cn("shrink-0 border-t border-line py-3", collapsed ? "px-2" : "px-2.5")}>
        <ul className="flex flex-col gap-0.5">
          {secondary.map((item) => (
            <li key={item.path}>
              <NavLink
                item={item}
                isActive={isActivePath(item.path)}
                collapsed={collapsed}
                badgeCount={0}
                onNavigate={onNavigate}
              />
            </li>
          ))}
        </ul>

        {user ? (
          <div
            className={cn(
              "mt-3 flex items-center border-t border-line-subtle pt-3",
              collapsed ? "justify-center" : "gap-2.5",
            )}
          >
            <span
              aria-hidden="true"
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-line-strong bg-surface-overlay text-[12px] font-semibold text-content-muted"
            >
              {user.username.charAt(0).toUpperCase()}
            </span>
            {!collapsed && (
              <div className="min-w-0 flex-1">
                <p className="truncate text-[12px] font-medium leading-tight text-content">
                  {user.username}
                </p>
                <p className="truncate text-[11px] leading-tight text-content-dim">
                  {user.role.toLowerCase()}
                </p>
              </div>
            )}
            <button
              type="button"
              onClick={logout}
              title="Sign out"
              className={cn(
                "flex h-7 w-7 shrink-0 items-center justify-center rounded-[5px] text-content-dim transition-colors hover:bg-surface-overlay hover:text-critical",
                collapsed && "hidden",
              )}
            >
              <Icon name="logout" size={15} title="Sign out" />
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function Sidebar({ collapsed, mobileOpen, onMobileClose, criticalCount }: SidebarProps) {
  const drawerRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  // Escape closes the drawer, and focus moves into it on open.
  useEffect(() => {
    if (!mobileOpen) return;

    closeButtonRef.current?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onMobileClose();
        return;
      }
      if (event.key !== "Tab" || !drawerRef.current) return;

      const focusables = drawerRef.current.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])',
      );
      if (focusables.length === 0) return;

      const first = focusables[0];
      const last = focusables[focusables.length - 1];

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [mobileOpen, onMobileClose]);

  // Prevent the page behind the drawer from scrolling.
  useEffect(() => {
    if (!mobileOpen) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [mobileOpen]);

  return (
    <>
      {/* Tablet rail and desktop sidebar */}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 hidden border-r border-line md:block",
          collapsed ? "w-14" : "w-[232px]",
        )}
      >
        <SidebarContent collapsed={collapsed} criticalCount={criticalCount} />
      </aside>

      {/* Mobile drawer */}
      {mobileOpen ? (
        <div className="fixed inset-0 z-50 md:hidden">
          <button
            type="button"
            aria-label="Close navigation"
            onClick={onMobileClose}
            className="absolute inset-0 bg-surface-sunken/75"
          />
          <div
            ref={drawerRef}
            role="dialog"
            aria-modal="true"
            aria-label="Navigation"
            className="sg-enter absolute inset-y-0 left-0 w-[264px] border-r border-line shadow-xl"
          >
            <button
              ref={closeButtonRef}
              type="button"
              onClick={onMobileClose}
              className="absolute right-2 top-3.5 z-10 flex h-7 w-7 items-center justify-center rounded-[5px] text-content-muted hover:bg-surface-overlay hover:text-content"
            >
              <Icon name="close" size={16} title="Close navigation" />
            </button>
            <SidebarContent
              collapsed={false}
              criticalCount={criticalCount}
              onNavigate={onMobileClose}
            />
          </div>
        </div>
      ) : null}
    </>
  );
}
