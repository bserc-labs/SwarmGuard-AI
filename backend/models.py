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

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
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

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(Integer, ForeignKey("organizations.id"), index=True, nullable=False)
    drone_id: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=True)
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
    timestamp: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=True)


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
