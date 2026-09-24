# SwarmGuard AI — Database Schema Documentation

**Supported Engine:** PostgreSQL 16 with TimescaleDB, everywhere.

SQLite is not supported and has not been since the telemetry table became a
hypertable: `database.py` refuses to start on a SQLite URL rather than let a
deployment discover the difference at run time.

---

## Entity-Relationship (ER) Diagram

```mermaid
erDiagram
    User {
        int id PK
        int organization_id FK
        string username UK
        string email UK
        string password
        string role
        bool is_active
        int token_version
        datetime created_at
    }

    DeviceCredential {
        int id PK
        int organization_id FK
        string drone_id
        string key_hash UK
        string key_prefix
        string label
        string created_by
        datetime created_at
        datetime last_used_at
        datetime revoked_at
        string revoked_by
    }

    TelemetryLog {
        int id PK
        string drone_id FK
        float latitude
        float longitude
        float altitude
        float speed
        float battery
        int packet_sequence
        bigint sample_time_ms
        datetime created_at
    }

    Incident {
        int id PK
        string drone_id FK
        string attack_type
        float anomaly_score
        int threat_level
        string severity
        json shap_values
        string explanation
        string status
        datetime created_at
        datetime updated_at
    }

    Drone {
        int id PK
        string drone_id UK
        string status
        datetime last_seen
        string last_command
    }

    DroneCommand {
        int id PK
        string drone_id FK
        string command_type
        string reason
        string issued_by
        string status
        datetime created_at
    }

    AuditLog {
        int id PK
        string username FK
        string action
        string target
        string details
        string ip_address
        datetime created_at
    }

    GeofenceZone {
        int id PK
        string name UK
        string zone_type
        json coordinates
        string severity
        bool is_active
        datetime created_at
    }

    SystemSettings {
        int id PK
        float critical_threshold
        float high_threshold
        string refresh_rate
        bool ui_sound
        bool push_notif
        bool webhooks
    }

    Drone ||--o{ TelemetryLog : "generates"
    Drone ||--o{ Incident : "triggers"
    Drone ||--o{ DroneCommand : "receives"
    Drone ||--o{ DeviceCredential : "authenticates with"
    User ||--o{ DroneCommand : "issues"
    User ||--o{ AuditLog : "creates"
```

Every table above except `system_settings` carries an `organization_id`: it is
the tenancy boundary, and `tests/test_route_tenancy.py` refuses to let a route
read one of these tables without scoping by it.

---

## Timestamps

Every `datetime` column above is `timestamp with time zone`, an absolute
instant (migration `m3b4c5d6e7f8`). They were `timestamp without time zone`
holding UTC by convention, which nothing enforced and which left every value
in an API response without an offset. Connections pin their session to UTC, so
a bare timestamp handed to the driver still means UTC whatever the server is
configured for.

## High-Performance Database Indexes

| Table | Index Column(s) | Type | Rationale |
|:---|:---|:---:|:---|
| `telemetry_logs` | `created_at` | B-Tree | Optimizes historical time-window queries for DVR playback |
| `telemetry_logs` | `drone_id` | B-Tree | Fast lookup for specific drone telemetry histories |
| `incidents` | `created_at` | B-Tree | Fast sorting for recent incident feeds |
| `incidents` | `severity` | B-Tree | High-speed filtering by `CRITICAL` / `HIGH` severity |
| `incidents` | `status` | B-Tree | High-speed filtering by `OPEN` / `RESOLVED` status |
| `drones` | `drone_id` | Unique B-Tree | Instant drone registration and lookup |
| `users` | `username`, `email` | Unique B-Tree | Fast authentication lookups |
