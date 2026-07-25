from sqlalchemy import Column, Integer, String, Float, DateTime, JSON
from sqlalchemy.sql import func
from database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True)
    password = Column(String)
    role = Column(String, default="operator")
    created_at = Column(DateTime, server_default=func.now())


class TelemetryLog(Base):
    __tablename__ = "telemetry_logs"

    id = Column(Integer, primary_key=True, index=True)
    drone_id = Column(String)
    latitude = Column(Float)
    longitude = Column(Float)
    altitude = Column(Float)
    speed = Column(Float)
    battery = Column(Float)
    packet_sequence = Column(Integer)
    created_at = Column(DateTime, server_default=func.now())


class Incident(Base):
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, index=True)
    drone_id = Column(String)
    attack_type = Column(String)
    anomaly_score = Column(Float)
    threat_level = Column(Integer)
    severity = Column(String)
    shap_values = Column(JSON)
    explanation = Column(String)
    created_at = Column(DateTime, server_default=func.now())


class Drone(Base):
    __tablename__ = "drones"

    id = Column(Integer, primary_key=True, index=True)
    drone_id = Column(String, unique=True, index=True)
    status = Column(String, default="ACTIVE")  # ACTIVE, COMPROMISED, GROUNDED, RETURNING
    last_seen = Column(DateTime, server_default=func.now(), onupdate=func.now())
    last_command = Column(String, nullable=True)


class DroneCommand(Base):
    __tablename__ = "drone_commands"

    id = Column(Integer, primary_key=True, index=True)
    drone_id = Column(String, index=True)
    command_type = Column(String)  # RETURN_TO_HOME, EMERGENCY_LAND, SWITCH_SAFE_MODE, KILL_MOTOR, RESUME_MISSION
    reason = Column(String, nullable=True)
    issued_by = Column(String)
    status = Column(String, default="PENDING")  # PENDING, EXECUTED, FAILED
    created_at = Column(DateTime, server_default=func.now())