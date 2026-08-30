import type { IconName } from "@/components/ui/Icon";
import { hasPermission, isElevated, Permissions, type Permission } from "./rbac";

/**
 * Navigation. Each item declares the permission that makes it useful, so the
 * sidebar hides destinations the current role cannot act on rather than
 * routing the operator to a page that renders permission-denied.
 */
export interface NavItem {
  label: string;
  icon: IconName;
  path: string;
  permission: Permission;
  /** Show a count of open critical/high incidents. */
  badge?: boolean;
  /** Additionally gated by the router's role guard. */
  elevatedOnly?: boolean;
}

export const NAV_PRIMARY: readonly NavItem[] = [
  { label: "Dashboard", icon: "dashboard", path: "/dashboard", permission: Permissions.INCIDENT_READ },
  { label: "Telemetry", icon: "activity", path: "/telemetry", permission: Permissions.TELEMETRY_READ },
  { label: "Fleet", icon: "drone", path: "/fleet", permission: Permissions.DRONE_READ },
  { label: "Incidents", icon: "alert", path: "/incidents", permission: Permissions.INCIDENT_READ, badge: true },
  { label: "Threat intelligence", icon: "shield", path: "/threats", permission: Permissions.INCIDENT_READ },
  // Gated on ai.explain: the guard thresholds this page shows are effectively
  // the evasion envelope, so observers do not get them.
  { label: "Detection", icon: "gauge", path: "/detection", permission: Permissions.AI_EXPLAIN },
  { label: "Fleet control", icon: "zap", path: "/admin", permission: Permissions.DRONE_COMMAND_REQUEST, elevatedOnly: true },
] as const;

export const NAV_SECONDARY: readonly NavItem[] = [
  // user.manage is admin-only, so the permission filter alone gates this; the
  // route carries its own admin guard rather than the broader elevated check.
  { label: "Team", icon: "user", path: "/users", permission: Permissions.USER_MANAGE },
  { label: "Settings", icon: "settings", path: "/settings", permission: Permissions.SETTINGS_READ, elevatedOnly: true },
  { label: "Profile", icon: "user", path: "/profile", permission: Permissions.TELEMETRY_READ },
] as const;

/**
 * Filters navigation for a role. Extracted from the sidebar so the visibility
 * rules can be tested without mounting the router.
 *
 * A destination is shown only when the role holds the permission that makes it
 * useful and, for elevated entries, passes the router's own role guard.
 */
export function visibleNavItems(items: readonly NavItem[], role: string | null | undefined): NavItem[] {
  return items.filter((item) => {
    if (item.elevatedOnly && !isElevated(role)) return false;
    return hasPermission(role, item.permission);
  });
}

/* ------------------------------------------------------------- severity */

export type SeverityTone = "critical" | "warning" | "accent" | "neutral";

/**
 * Severity to visual tone. Amber and red are reserved for HIGH and CRITICAL
 * so that colour in the console always means an actual escalation.
 */
export const SEVERITY_TONE: Record<string, SeverityTone> = {
  CRITICAL: "critical",
  HIGH: "warning",
  MEDIUM: "accent",
  LOW: "neutral",
  NONE: "neutral",
};

export function severityTone(severity: string | null | undefined): SeverityTone {
  if (!severity) return "neutral";
  return SEVERITY_TONE[severity.toUpperCase()] ?? "neutral";
}

/** Severity order for sorting, highest first. */
export const SEVERITY_RANK: Record<string, number> = {
  CRITICAL: 4,
  HIGH: 3,
  MEDIUM: 2,
  LOW: 1,
};

export const SEVERITY_FILTERS = ["All", "CRITICAL", "HIGH", "MEDIUM", "LOW"] as const;

/* --------------------------------------------------------- drone status */

/**
 * Drone status values the backend writes. SILENT_POSSIBLE_JAMMING is set by
 * the heartbeat service; the rest are set on ingest or by command handling.
 */
export const DRONE_STATUS_TONE: Record<string, SeverityTone> = {
  ACTIVE: "accent",
  SAFE_MODE: "warning",
  SILENT_POSSIBLE_JAMMING: "critical",
  COMPROMISED: "critical",
  GROUNDED: "neutral",
  RETURNING: "warning",
};

export function droneStatusTone(status: string | null | undefined): SeverityTone {
  if (!status) return "neutral";
  return DRONE_STATUS_TONE[status.toUpperCase()] ?? "neutral";
}

/* ------------------------------------------------------ incident status */

/**
 * The incident lifecycle, in order. Mirrors LIFECYCLE in
 * backend/routers/incidents.py.
 *
 * The backend walks intermediate states on the caller's behalf, so a transition
 * request names a destination rather than the next hop. What this ordering is
 * for on the client is deciding which destinations are still *ahead* of the
 * incident — offering "Resolve" on an already-resolved incident produces a 400,
 * and offering "Acknowledge" on a resolved one produces a different 400.
 */
export const INCIDENT_LIFECYCLE = [
  "NEW",
  "OPEN",
  "ACKNOWLEDGED",
  "INVESTIGATING",
  "CONTAINED",
  "RESOLVED",
  "CLOSED",
] as const;

export type IncidentStatus = (typeof INCIDENT_LIFECYCLE)[number];

/** Position in the lifecycle, or -1 for a status the client does not know. */
export function lifecycleIndex(status: string | null | undefined): number {
  if (!status) return -1;
  return (INCIDENT_LIFECYCLE as readonly string[]).indexOf(status.toUpperCase());
}

/**
 * True when `target` is still reachable from `status` — strictly ahead of it.
 * An unknown current status returns false rather than guessing, so the UI
 * withholds the action instead of offering one that will fail.
 */
export function canAdvanceTo(status: string | null | undefined, target: IncidentStatus): boolean {
  const from = lifecycleIndex(status);
  if (from < 0) return false;
  return lifecycleIndex(target) > from;
}

/** Terminal statuses — no further transitions are offered. */
export const CLOSED_STATUSES = new Set(["RESOLVED", "CLOSED"]);

export const INCIDENT_STATUS_TONE: Record<string, SeverityTone> = {
  NEW: "critical",
  OPEN: "warning",
  ACKNOWLEDGED: "accent",
  INVESTIGATING: "accent",
  CONTAINED: "accent",
  RESOLVED: "neutral",
  CLOSED: "neutral",
};

export function incidentStatusTone(status: string | null | undefined): SeverityTone {
  if (!status) return "neutral";
  return INCIDENT_STATUS_TONE[status.toUpperCase()] ?? "neutral";
}
