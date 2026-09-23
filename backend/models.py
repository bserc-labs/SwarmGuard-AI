"""ORM models.

Declared in the SQLAlchemy 2.0 `Mapped[]` style so attribute access is typed as
the Python value (`user.role` is a `str`, not a `Column[str]`).

Typing convention, chosen so that no DDL changes:
  * `Mapped[T]`         -- primary keys and `nullable=False` columns.
  * `Mapped[T | None]`  -- columns declared `nullable=True`; callers must handle None.
  * `Mapped[T]` with an explicit `nullable=True` -- columns the application always
    populates (defaults, server defaults, identity strings) but which the schema
    never constrained. The database column stays nullable; tightening that is a
    migration, not an annotation.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from database import Base


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, index=True, nullable=True)
    slug: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=True)
    status: Mapped[str] = mapped_column(String, default="ACTIVE", nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=True)

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=True)
    password: Mapped[str] = mapped_column(String, nullable=True)
    role: Mapped[str] = mapped_column(String, default="operator", nullable=True)
    organization_id: Mapped[int] = mapped_column(Integer, ForeignKey("organizations.id"), nullable=False)
    # Incremented on password or role change. The value is embedded in every
    # issued token and compared on each request, so a single UPDATE invalidates
    # all of a user's outstanding sessions without needing a blocklist.
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=True)

    organization: Mapped["Organization"] = relationship()


class TelemetryLog(Base):
    __tablename__ = "telemetry_logs"
    # Serves GET /telemetry/latest (one newest row per drone via LATERAL),
    # GET /telemetry/{drone_id}[/latest] and the detection pipeline's history
    # window: every read of this table filters on (organization_id, drone_id)
    # and orders by created_at DESC, and until migration j0e1f2a3b4c5 the table
    # had only single-column indexes, so each of them fetched and sorted.
    __table_args__ = (
        Index(
            "ix_telemetry_logs_org_drone_created_at",
            "organization_id",
            "drone_id",
            text("created_at DESC"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, index=True)
    organization_id: Mapped[int] = mapped_column(Integer, ForeignKey("organizations.id"), index=True, nullable=False)
    drone_id: Mapped[str] = mapped_column(String, index=True, nullable=True)
    latitude: Mapped[float] = mapped_column(Float, nullable=True)
    longitude: Mapped[float] = mapped_column(Float, nullable=True)
    altitude: Mapped[float] = mapped_column(Float, nullable=True)
    speed: Mapped[float] = mapped_column(Float, nullable=True)
    heading: Mapped[float | None] = mapped_column(Float, nullable=True)
    battery: Mapped[float] = mapped_column(Float, nullable=True)
    flight_mode: Mapped[str | None] = mapped_column(String, nullable=True)
    armed_status: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    satellites: Mapped[int | None] = mapped_column(Integer, nullable=True)
    packet_sequence: Mapped[int] = mapped_column(Integer, nullable=True)
    # Device sample clock, ms (MAVLink time_boot_ms or equivalent). Nullable:
    # added by migration g7b8c9d0e1f2, so rows from before it, and devices that
    # never report one, are NULL and the kinematic guard rates them on
    # created_at. BigInteger because a device may report epoch milliseconds,
    # which overflow a 32-bit Integer.
    sample_time_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, primary_key=True, server_default=func.now(), index=True)


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(Integer, ForeignKey("organizations.id"), index=True, nullable=False)
    drone_id: Mapped[str] = mapped_column(String, index=True, nullable=True)
    mission_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    attack_type: Mapped[str] = mapped_column(String, nullable=True)
    threat_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=True)
    anomaly_score: Mapped[float] = mapped_column(Float, nullable=True)
    threat_level: Mapped[int] = mapped_column(Integer, nullable=True)
    severity: Mapped[str] = mapped_column(String, index=True, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=0, index=True, nullable=True)
    shap_values: Mapped[Any] = mapped_column(JSON, nullable=True)
    explanation: Mapped[str] = mapped_column(String, nullable=True)
    explanation_summary: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    recommended_action: Mapped[str | None] = mapped_column(String, nullable=True)
    model_version: Mapped[str | None] = mapped_column(String, nullable=True)
    feature_version: Mapped[str | None] = mapped_column(String, nullable=True)
    
    status: Mapped[str] = mapped_column(String, default="NEW", index=True, nullable=True)  # NEW, OPEN, ACKNOWLEDGED, INVESTIGATING, CONTAINED, RESOLVED, CLOSED
    assigned_analyst: Mapped[str | None] = mapped_column(String, nullable=True)
    
    detection_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True, nullable=True)
    resolution_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=True)


class Drone(Base):
    __tablename__ = "drones"
    # Identifiers are unique per organization, not globally -- the same defect
    # and the same fix as geofence zone names below. See migration f6a7b8c9d0e1.
    __table_args__ = (
        UniqueConstraint("organization_id", "drone_id", name="uq_drones_org_drone_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(Integer, ForeignKey("organizations.id"), index=True, nullable=False)
    # Unique per organization, not globally -- see migration f6a7b8c9d0e1. A
    # global unique index here meant two tenants could not both operate a
    # "UAV-001": the second one's ingest failed with a constraint violation on
    # every packet, and the failure itself disclosed that another tenant held
    # that identifier.
    drone_id: Mapped[str] = mapped_column(String, index=True, nullable=True)
    status: Mapped[str] = mapped_column(String, default="ACTIVE", nullable=True)  # ACTIVE, COMPROMISED, GROUNDED, RETURNING
    last_seen: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=True)
    last_command: Mapped[str | None] = mapped_column(String, nullable=True)


class CommandRequest(Base):
    __tablename__ = "command_requests"

    command_id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(Integer, ForeignKey("organizations.id"), index=True, nullable=False)
    drone_id: Mapped[str] = mapped_column(String, index=True, nullable=True)
    requested_by: Mapped[str] = mapped_column(String, nullable=True)
    command_type: Mapped[str] = mapped_column(String, nullable=True)  # RETURN_TO_HOME, EMERGENCY_LAND, SWITCH_SAFE_MODE, KILL_MOTOR, RESUME_MISSION
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="PENDING", nullable=True)  # PENDING, APPROVED, REJECTED
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    actor: Mapped[str] = mapped_column(String, index=True, nullable=True)
    # The one tenant-scoped column that stays nullable, and deliberately.
    # A LOGIN_FAILED for a username that does not exist has no organization to
    # attribute it to, and dropping those rows to satisfy a constraint would
    # discard exactly the evidence a credential-stuffing attempt leaves behind.
    # A CHECK constraint bounds the exception to that action; see migration
    # d4e5f6a7b8c9.
    organization_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("organizations.id"), index=True, nullable=True)
    action: Mapped[str] = mapped_column(String, nullable=True)
    resource: Mapped[str | None] = mapped_column(String, nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String, nullable=True)
    target: Mapped[str | None] = mapped_column(String, nullable=True)  # Legacy support
    previous_state: Mapped[str | None] = mapped_column(String, nullable=True)
    new_state: Mapped[str | None] = mapped_column(String, nullable=True)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    details: Mapped[str | None] = mapped_column(String, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # One timestamp, not two. `timestamp` was added alongside this column in
    # sprint 7, both defaulting to now(), and nothing ever read it -- see
    # migration e5f6a7b8c9d0, which drops it and moves its index here, onto the
    # column `routers/incidents.py` actually orders by.
    #
    # Rows in this table are append-only at the database level: a trigger
    # rejects UPDATE outright and permits DELETE only for a retention pass that
    # sets `swarmguard.audit_maintenance` on its session first.
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True, nullable=True)


class SystemSettings(Base):
    __tablename__ = "system_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(Integer, ForeignKey("organizations.id"), unique=True, index=True, nullable=False)
    critical_threshold: Mapped[float] = mapped_column(Float, default=0.85, nullable=True)
    high_threshold: Mapped[float] = mapped_column(Float, default=0.60, nullable=True)
    refresh_rate: Mapped[str] = mapped_column(String, default="5s", nullable=True)
    ui_sound: Mapped[bool] = mapped_column(Boolean, default=True, nullable=True)
    push_notif: Mapped[bool] = mapped_column(Boolean, default=False, nullable=True)
    webhooks: Mapped[bool] = mapped_column(Boolean, default=True, nullable=True)


class GeofenceZone(Base):
    __tablename__ = "geofence_zones"
    # Names are unique per organization, not globally. A global constraint stopped
    # one tenant creating a zone whose name another had used -- and the rejection
    # revealed that the other row existed.
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_geofence_zone_org_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(Integer, ForeignKey("organizations.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String, index=True, nullable=True)
    zone_type: Mapped[str] = mapped_column(String, nullable=True)  # POLYGON, CIRCLE
    coordinates: Mapped[Any] = mapped_column(JSON, nullable=True)  # List of [lat, lng] for POLYGON, or {"center": [lat, lng], "radius": int} for CIRCLE
    severity: Mapped[str] = mapped_column(String, default="CRITICAL", nullable=True)  # WARNING, CRITICAL
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=True)


class DeviceCredential(Base):
    """One drone's ingest key, stored as a SHA-256 digest. See services/device_credentials.py."""

    __tablename__ = "device_credentials"
    __table_args__ = (
        Index("ux_device_credentials_key_hash", "key_hash", unique=True),
        Index("ix_device_credentials_org_drone", "organization_id", "drone_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, ForeignKey("organizations.id"), nullable=False)
    drone_id: Mapped[str] = mapped_column(String, nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    label: Mapped[str | None] = mapped_column(String, nullable=True)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_by: Mapped[str | None] = mapped_column(String, nullable=True)

