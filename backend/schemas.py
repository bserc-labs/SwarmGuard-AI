from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class LoginRequest(BaseModel):
    username: str
    password: str

class UserCreate(BaseModel):
    username: str
    email: Optional[str] = None
    password: str

class UserOut(BaseModel):
    id: int
    username: str
    email: Optional[str]
    role: str
    created_at: datetime
    
    model_config = {
        "from_attributes": True
    }

class UserUpdate(BaseModel):
    email: Optional[str] = None

class PasswordUpdate(BaseModel):
    current_password: str
    new_password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str


class TelemetryPacket(BaseModel):
    drone_id: str = Field(..., min_length=1, max_length=50)
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    altitude: float = Field(..., ge=0.0, le=50000.0)
    speed: float = Field(..., ge=0.0, le=500.0)
    battery: float = Field(..., ge=0.0, le=100.0)
    packet_sequence: int = Field(..., ge=0)


class DetectionResult(BaseModel):
    is_anomaly: bool
    anomaly_score: float
    attack_type: Optional[str] = None
    threat_level: Optional[int] = None
    severity: Optional[str] = None
    shap_top3: Optional[List[dict]] = None
    explanation: Optional[str] = None


class IncidentOut(BaseModel):
    id: int
    drone_id: str
    attack_type: str
    threat_level: int
    severity: str
    shap_values: Optional[List[dict]] = None
    explanation: str
    status: str = "OPEN"
    created_at: datetime

    model_config = {
        "from_attributes": True
    }


class IncidentUpdate(BaseModel):
    status: str = Field(..., pattern="^(ACKNOWLEDGED|FALSE_POSITIVE|ESCALATED|RESOLVED)$")


class CommandCreate(BaseModel):
    command_type: str  # RETURN_TO_HOME, EMERGENCY_LAND, SWITCH_SAFE_MODE, KILL_MOTOR, RESUME_MISSION
    reason: Optional[str] = None


class CommandOut(BaseModel):
    id: int
    drone_id: str
    command_type: str
    reason: Optional[str]
    issued_by: str
    status: str
    created_at: datetime

    model_config = {
        "from_attributes": True
    }


class DroneOut(BaseModel):
    id: int
    drone_id: str
    status: str
    last_seen: datetime
    last_command: Optional[str]

    model_config = {
        "from_attributes": True
    }


class AuditLogOut(BaseModel):
    id: int
    username: str
    action: str
    target: Optional[str] = None
    details: Optional[str] = None
    ip_address: Optional[str] = None
    created_at: datetime

    model_config = {
        "from_attributes": True
    }


class SystemSettingsOut(BaseModel):
    critical_threshold: float
    high_threshold: float
    refresh_rate: str
    ui_sound: bool
    push_notif: bool
    webhooks: bool

    model_config = {
        "from_attributes": True
    }


class SystemSettingsUpdate(BaseModel):
    critical_threshold: Optional[float] = None
    high_threshold: Optional[float] = None
    refresh_rate: Optional[str] = None
    ui_sound: Optional[bool] = None
    push_notif: Optional[bool] = None
    webhooks: Optional[bool] = None