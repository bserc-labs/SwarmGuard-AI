"""
RBAC Permission Map for SwarmGuard AI Enterprise.

Defines granular permissions and maps them to roles.
"""

# --- Permission Definitions ---
class Permissions:
    # Telemetry
    TELEMETRY_READ = "telemetry.read"
    TELEMETRY_INGEST = "telemetry.ingest"

    # Incidents
    INCIDENT_READ = "incident.read"
    INCIDENT_ACKNOWLEDGE = "incident.acknowledge"
    INCIDENT_ASSIGN = "incident.assign"
    INCIDENT_RESOLVE = "incident.resolve"
    INCIDENT_CLOSE = "incident.close"

    # Drones
    DRONE_READ = "drone.read"
    DRONE_COMMAND_REQUEST = "drone.command.request"
    DRONE_COMMAND_APPROVE = "drone.command.approve"
    # Issue and revoke per-drone ingest keys. Admin only: a key authenticates
    # telemetry as that drone, so issuing one is granting the ability to
    # speak for an aircraft.
    DEVICE_CREDENTIALS_MANAGE = "device.credentials.manage"

    # Audit
    AUDIT_READ = "audit.read"

    # Organization & Users
    ORGANIZATION_MANAGE = "organization.manage"
    USER_MANAGE = "user.manage"

    # Geofence
    GEOFENCE_READ = "geofence.read"
    GEOFENCE_MANAGE = "geofence.manage"

    # Settings
    SETTINGS_READ = "settings.read"
    SETTINGS_MANAGE = "settings.manage"

    # AI
    AI_EXPLAIN = "ai.explain"


# --- Role -> Permission Mapping ---
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "admin": {
        Permissions.TELEMETRY_READ, Permissions.TELEMETRY_INGEST,
        Permissions.INCIDENT_READ, Permissions.INCIDENT_ACKNOWLEDGE,
        Permissions.INCIDENT_ASSIGN, Permissions.INCIDENT_RESOLVE,
        Permissions.INCIDENT_CLOSE,
        Permissions.DRONE_READ, Permissions.DRONE_COMMAND_REQUEST,
        Permissions.DRONE_COMMAND_APPROVE,
        Permissions.AUDIT_READ,
        Permissions.ORGANIZATION_MANAGE, Permissions.USER_MANAGE,
        Permissions.DEVICE_CREDENTIALS_MANAGE,
        Permissions.GEOFENCE_READ, Permissions.GEOFENCE_MANAGE,
        Permissions.SETTINGS_READ, Permissions.SETTINGS_MANAGE,
        Permissions.AI_EXPLAIN,
    },
    "commander": {
        Permissions.TELEMETRY_READ, Permissions.TELEMETRY_INGEST,
        Permissions.INCIDENT_READ, Permissions.INCIDENT_ACKNOWLEDGE,
        Permissions.INCIDENT_ASSIGN, Permissions.INCIDENT_RESOLVE,
        Permissions.INCIDENT_CLOSE,
        Permissions.DRONE_READ, Permissions.DRONE_COMMAND_REQUEST,
        Permissions.DRONE_COMMAND_APPROVE,
        Permissions.AUDIT_READ,
        Permissions.GEOFENCE_READ, Permissions.GEOFENCE_MANAGE,
        Permissions.SETTINGS_READ,
        Permissions.AI_EXPLAIN,
    },
    "analyst": {
        Permissions.TELEMETRY_READ,
        Permissions.INCIDENT_READ, Permissions.INCIDENT_ACKNOWLEDGE,
        Permissions.INCIDENT_ASSIGN, Permissions.INCIDENT_RESOLVE,
        Permissions.DRONE_READ,
        Permissions.AUDIT_READ,
        Permissions.GEOFENCE_READ,
        Permissions.SETTINGS_READ,
        Permissions.AI_EXPLAIN,
    },
    "operator": {
        Permissions.TELEMETRY_READ, Permissions.TELEMETRY_INGEST,
        Permissions.INCIDENT_READ,
        Permissions.DRONE_READ, Permissions.DRONE_COMMAND_REQUEST,
        Permissions.GEOFENCE_READ,
        Permissions.SETTINGS_READ,
        Permissions.AI_EXPLAIN,
    },
    "observer": {
        Permissions.TELEMETRY_READ,
        Permissions.INCIDENT_READ,
        Permissions.DRONE_READ,
        Permissions.GEOFENCE_READ,
        Permissions.SETTINGS_READ,
    },
}


def get_permissions_for_role(role: str) -> set[str]:
    """Returns the set of permissions for a given role."""
    return ROLE_PERMISSIONS.get(role.lower(), set())


def has_permission(role: str, permission: str) -> bool:
    """Checks if a role has a specific permission."""
    return permission in get_permissions_for_role(role)
