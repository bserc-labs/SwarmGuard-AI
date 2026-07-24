from pydantic import BaseModel
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

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str


class TelemetryPacket(BaseModel):
    drone_id: str
    latitude: float
    longitude: float
    altitude: float
    speed: float
    battery: float
    packet_sequence: int


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
    created_at: datetime

    model_config = {
        "from_attributes": True
    }