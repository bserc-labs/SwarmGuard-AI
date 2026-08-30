/**
 * Client-side mirror of backend/middleware/rbac.py.
 *
 * This is a UI affordance only — it hides controls a role cannot use so the
 * operator is not offered actions that will 403. The backend remains the sole
 * authority; every guarded route re-checks server-side. Keep this table in sync
 * when ROLE_PERMISSIONS changes.
 */

export const Permissions = {
  TELEMETRY_READ: "telemetry.read",
  TELEMETRY_INGEST: "telemetry.ingest",
  INCIDENT_READ: "incident.read",
  INCIDENT_ACKNOWLEDGE: "incident.acknowledge",
  INCIDENT_ASSIGN: "incident.assign",
  INCIDENT_RESOLVE: "incident.resolve",
  INCIDENT_CLOSE: "incident.close",
  DRONE_READ: "drone.read",
  DRONE_COMMAND_REQUEST: "drone.command.request",
  DRONE_COMMAND_APPROVE: "drone.command.approve",
  AUDIT_READ: "audit.read",
  ORGANIZATION_MANAGE: "organization.manage",
  USER_MANAGE: "user.manage",
  GEOFENCE_READ: "geofence.read",
  GEOFENCE_MANAGE: "geofence.manage",
  SETTINGS_READ: "settings.read",
  SETTINGS_MANAGE: "settings.manage",
  AI_EXPLAIN: "ai.explain",
} as const;

export type Permission = (typeof Permissions)[keyof typeof Permissions];

const P = Permissions;

export const ROLE_PERMISSIONS: Record<string, ReadonlySet<Permission>> = {
  admin: new Set<Permission>([
    P.TELEMETRY_READ, P.TELEMETRY_INGEST,
    P.INCIDENT_READ, P.INCIDENT_ACKNOWLEDGE, P.INCIDENT_ASSIGN, P.INCIDENT_RESOLVE, P.INCIDENT_CLOSE,
    P.DRONE_READ, P.DRONE_COMMAND_REQUEST, P.DRONE_COMMAND_APPROVE,
    P.AUDIT_READ, P.ORGANIZATION_MANAGE, P.USER_MANAGE,
    P.GEOFENCE_READ, P.GEOFENCE_MANAGE,
    P.SETTINGS_READ, P.SETTINGS_MANAGE,
    P.AI_EXPLAIN,
  ]),
  commander: new Set<Permission>([
    P.TELEMETRY_READ, P.TELEMETRY_INGEST,
    P.INCIDENT_READ, P.INCIDENT_ACKNOWLEDGE, P.INCIDENT_ASSIGN, P.INCIDENT_RESOLVE, P.INCIDENT_CLOSE,
    P.DRONE_READ, P.DRONE_COMMAND_REQUEST, P.DRONE_COMMAND_APPROVE,
    P.AUDIT_READ,
    P.GEOFENCE_READ, P.GEOFENCE_MANAGE,
    P.SETTINGS_READ,
    P.AI_EXPLAIN,
  ]),
  analyst: new Set<Permission>([
    P.TELEMETRY_READ,
    P.INCIDENT_READ, P.INCIDENT_ACKNOWLEDGE, P.INCIDENT_ASSIGN, P.INCIDENT_RESOLVE,
    P.DRONE_READ,
    P.AUDIT_READ,
    P.GEOFENCE_READ,
    P.SETTINGS_READ,
    P.AI_EXPLAIN,
  ]),
  operator: new Set<Permission>([
    P.TELEMETRY_READ, P.TELEMETRY_INGEST,
    P.INCIDENT_READ,
    P.DRONE_READ, P.DRONE_COMMAND_REQUEST,
    P.GEOFENCE_READ,
    P.SETTINGS_READ,
    P.AI_EXPLAIN,
  ]),
  observer: new Set<Permission>([
    P.TELEMETRY_READ,
    P.INCIDENT_READ,
    P.DRONE_READ,
    P.GEOFENCE_READ,
    P.SETTINGS_READ,
  ]),
};

/** Roles are compared case-insensitively, matching the backend. */
export function hasPermission(role: string | null | undefined, permission: Permission): boolean {
  if (!role) return false;
  return ROLE_PERMISSIONS[role.toLowerCase()]?.has(permission) ?? false;
}

export function permissionsFor(role: string | null | undefined): Permission[] {
  if (!role) return [];
  return [...(ROLE_PERMISSIONS[role.toLowerCase()] ?? [])];
}

/** Roles the router allows into /admin and /settings. Mirrors router.tsx. */
export const ELEVATED_ROLES = ["admin", "commander"] as const;

export function isElevated(role: string | null | undefined): boolean {
  return !!role && (ELEVATED_ROLES as readonly string[]).includes(role.toLowerCase());
}
