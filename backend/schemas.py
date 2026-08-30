from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

# Mirrors the keys of middleware.rbac.ROLE_PERMISSIONS. A free-form string here
# meant a typo produced a user with an empty permission set and no error at all.
UserRole = Literal["admin", "commander", "analyst", "operator", "observer"]

# Long enough to resist offline cracking of the pbkdf2 hash. Applied to both
# account creation and self-service password change.
MIN_PASSWORD_LENGTH = 12


class LoginRequest(BaseModel):
    username: str
    password: str

class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, pattern=r"^[A-Za-z0-9._-]+$")
    email: str | None = Field(None, max_length=254)
    password: str = Field(..., min_length=MIN_PASSWORD_LENGTH, max_length=128)
    role: UserRole = "operator"

class UserOut(BaseModel):
    id: int
    username: str
    email: str | None
    role: str
    organization_id: int | None = None
    created_at: datetime

    model_config = {
        "from_attributes": True
    }

class UserUpdate(BaseModel):
    email: str | None = None

class PasswordUpdate(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=MIN_PASSWORD_LENGTH, max_length=128)

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 — OAuth2 token type, not a credential
    role: str


# --- Organization ---
class OrganizationCreate(BaseModel):
    name: str
    slug: str

class OrganizationOut(BaseModel):
    id: int
    name: str
    slug: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {
        "from_attributes": True
    }


class TelemetryPacket(BaseModel):
    drone_id: str = Field(..., min_length=1, max_length=50)
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    altitude: float = Field(..., ge=0.0, le=50000.0)
    speed: float = Field(..., ge=0.0, le=500.0)
    heading: float | None = Field(None, ge=0.0, le=360.0)
    battery: float = Field(..., ge=0.0, le=100.0)
    flight_mode: str | None = None
    armed_status: bool | None = None
    satellites: int | None = Field(None, ge=0)
    packet_sequence: int = Field(..., ge=0)


class DetectionResult(BaseModel):
    is_anomaly: bool
    anomaly_score: float
    attack_type: str | None = None
    threat_level: int | None = None
    severity: str | None = None
    shap_top3: list[dict] | None = None
    explanation: str | None = None


class IncidentOut(BaseModel):
    id: int
    drone_id: str
    organization_id: int | None = None
    mission_id: str | None = None
    attack_type: str
    threat_score: float
    anomaly_score: float
    threat_level: int
    severity: str
    priority: int
    shap_values: list[dict] | None = None
    explanation: str
    explanation_summary: dict | None = None
    recommended_action: str | None = None
    model_version: str | None = None
    feature_version: str | None = None
    status: str
    assigned_analyst: str | None = None
    detection_time: datetime
    resolution_time: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {
        "from_attributes": True
    }


class IncidentUpdate(BaseModel):
    status: str = Field(..., pattern="^(NEW|OPEN|ACKNOWLEDGED|INVESTIGATING|CONTAINED|RESOLVED|CLOSED)$")


class IncidentAssign(BaseModel):
    username: str

class IncidentTransition(BaseModel):
    reason: str | None = None


# --- Command Request (Dry-Run Framework) ---
class CommandRequestCreate(BaseModel):
    command_type: str = Field(..., pattern="^(RETURN_TO_HOME|LAND|HOLD|EMERGENCY_LAND|SWITCH_SAFE_MODE|RESUME_MISSION)$")
    reason: str | None = None

class CommandRequestOut(BaseModel):
    command_id: int
    organization_id: int | None = None
    drone_id: str
    requested_by: str
    command_type: str
    reason: str | None
    status: str
    created_at: datetime
    approved_by: str | None = None
    approved_at: datetime | None = None

    model_config = {
        "from_attributes": True
    }

class CommandApproval(BaseModel):
    approved: bool
    reason: str | None = None


class DroneOut(BaseModel):
    id: int
    drone_id: str
    organization_id: int | None = None
    status: str
    last_seen: datetime
    last_command: str | None

    model_config = {
        "from_attributes": True
    }


class AuditLogOut(BaseModel):
    id: int
    actor: str
    organization_id: int | None = None
    action: str
    resource: str | None = None
    resource_id: str | None = None
    target: str | None = None
    previous_state: str | None = None
    new_state: str | None = None
    reason: str | None = None
    details: str | None = None
    ip_address: str | None = None
    correlation_id: str | None = None
    timestamp: datetime | None = None
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
    """Partial update. Every field is optional; only what is sent is applied.

    The two thresholds are fractions of a 0-100 threat score, matching what the
    Settings screen's inputs accept (min 0, max 1, step 0.01). They are bounded
    here as well: the console is a convenience, not the authority, and a value
    outside this range would silently disable a severity band for the whole
    organization.
    """

    critical_threshold: float | None = Field(None, gt=0.0, le=1.0)
    high_threshold: float | None = Field(None, gt=0.0, le=1.0)
    refresh_rate: str | None = Field(None, pattern=r"^(1s|5s|10s|30s)$")
    ui_sound: bool | None = None
    push_notif: bool | None = None
    webhooks: bool | None = None


class SystemSettingsOrdering(BaseModel):
    """The band ordering, checked against the values a partial update produces.

    Validating the two thresholds independently is not enough: sending only
    `high_threshold=0.9` against a stored critical of 0.85 leaves the bands
    inverted, and nothing could then be classified HIGH. The router merges the
    update onto the stored row and validates the result through this model.
    """

    critical_threshold: float = Field(..., gt=0.0, le=1.0)
    high_threshold: float = Field(..., gt=0.0, le=1.0)

    @model_validator(mode="after")
    def _high_below_critical(self) -> "SystemSettingsOrdering":
        if self.high_threshold >= self.critical_threshold:
            raise ValueError(
                "high_threshold must be below critical_threshold, otherwise no "
                "incident can fall into the high band."
            )
        return self