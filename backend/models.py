from sqlalchemy import JSON, Boolean, Column, DateTime, Float, Integer, String, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from database import Base

class Organization(Base):
    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    slug = Column(String, unique=True, index=True)
    status = Column(String, default="ACTIVE")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True)
    password = Column(String)
    role = Column(String, default="operator")
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True) # Temporarily nullable for migration
    # Incremented on password or role change. The value is embedded in every
    # issued token and compared on each request, so a single UPDATE invalidates
    # all of a user's outstanding sessions without needing a blocklist.
    token_version = Column(Integer, nullable=False, server_default="0", default=0)
    created_at = Column(DateTime, server_default=func.now())
    
    organization = relationship("Organization")


class TelemetryLog(Base):
    __tablename__ = "telemetry_logs"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), index=True, nullable=True)
    drone_id = Column(String, index=True)
    latitude = Column(Float)
    longitude = Column(Float)
    altitude = Column(Float)
    speed = Column(Float)
    heading = Column(Float, nullable=True)
    battery = Column(Float)
    flight_mode = Column(String, nullable=True)
    armed_status = Column(Boolean, nullable=True)
    satellites = Column(Integer, nullable=True)
    packet_sequence = Column(Integer)
    created_at = Column(DateTime, primary_key=True, server_default=func.now(), index=True)


class Incident(Base):
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), index=True, nullable=True)
    drone_id = Column(String, index=True)
    mission_id = Column(String, index=True, nullable=True)
    attack_type = Column(String)
    threat_score = Column(Float, default=0.0)
    anomaly_score = Column(Float)
    threat_level = Column(Integer)
    severity = Column(String, index=True)
    priority = Column(Integer, default=0, index=True)
    shap_values = Column(JSON)
    explanation = Column(String)
    explanation_summary = Column(JSON, nullable=True)
    recommended_action = Column(String, nullable=True)
    model_version = Column(String, nullable=True)
    feature_version = Column(String, nullable=True)
    
    status = Column(String, default="NEW", index=True)  # NEW, OPEN, ACKNOWLEDGED, INVESTIGATING, CONTAINED, RESOLVED, CLOSED
    assigned_analyst = Column(String, nullable=True)
    
    detection_time = Column(DateTime, server_default=func.now(), index=True)
    resolution_time = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class Drone(Base):
    __tablename__ = "drones"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), index=True, nullable=True)
    drone_id = Column(String, unique=True, index=True)
    status = Column(String, default="ACTIVE")  # ACTIVE, COMPROMISED, GROUNDED, RETURNING
    last_seen = Column(DateTime, server_default=func.now(), onupdate=func.now())
    last_command = Column(String, nullable=True)


class CommandRequest(Base):
    __tablename__ = "command_requests"

    command_id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), index=True, nullable=True)
    drone_id = Column(String, index=True)
    requested_by = Column(String)
    command_type = Column(String)  # RETURN_TO_HOME, EMERGENCY_LAND, SWITCH_SAFE_MODE, KILL_MOTOR, RESUME_MISSION
    reason = Column(String, nullable=True)
    status = Column(String, default="PENDING")  # PENDING, APPROVED, REJECTED
    created_at = Column(DateTime, server_default=func.now())
    approved_by = Column(String, nullable=True)
    approved_at = Column(DateTime, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    actor = Column(String, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), index=True, nullable=True)
    action = Column(String)
    resource = Column(String, nullable=True)
    resource_id = Column(String, nullable=True)
    target = Column(String, nullable=True)  # Legacy support
    previous_state = Column(String, nullable=True)
    new_state = Column(String, nullable=True)
    reason = Column(String, nullable=True)
    details = Column(String, nullable=True)
    ip_address = Column(String, nullable=True)
    correlation_id = Column(String, nullable=True)
    timestamp = Column(DateTime, server_default=func.now(), index=True)
    created_at = Column(DateTime, server_default=func.now())


class SystemSettings(Base):
    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), unique=True, index=True, nullable=True)
    critical_threshold = Column(Float, default=0.85)
    high_threshold = Column(Float, default=0.60)
    refresh_rate = Column(String, default="5s")
    ui_sound = Column(Boolean, default=True)
    push_notif = Column(Boolean, default=False)
    webhooks = Column(Boolean, default=True)


class GeofenceZone(Base):
    __tablename__ = "geofence_zones"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), index=True, nullable=True)
    name = Column(String, unique=True, index=True)
    zone_type = Column(String)  # POLYGON, CIRCLE
    coordinates = Column(JSON)  # List of [lat, lng] for POLYGON, or {"center": [lat, lng], "radius": int} for CIRCLE
    severity = Column(String, default="CRITICAL")  # WARNING, CRITICAL
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())