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