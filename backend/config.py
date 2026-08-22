from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Values that have appeared in committed examples, compose files, or CI.
# Treating them as secrets in a real deployment is the same as having none.
KNOWN_PUBLIC_SECRETS = {
    "CHANGE_ME",
    "CHANGE_THIS_TO_A_SECURE_64_CHAR_RANDOM_SECRET_IN_PRODUCTION",
    "SWARMGUARD_DEFENSE_PRODUCTION_SECRET_KEY_2026",
    "SWARMGUARD_DRONE_DEFENSE_SECRET_2026",
    "test_ci_secret_key",
    "secret",
    "changeme",
}

MIN_SECRET_LENGTH = 32


def _validate_secret(value: str, field_name: str, *, min_length: int = MIN_SECRET_LENGTH) -> str:
    """Reject secrets that are absent, too short, or publicly known."""
    if not value or not value.strip():
        raise ValueError(f"{field_name} must be set. Generate one with: openssl rand -hex 32")
    if value in KNOWN_PUBLIC_SECRETS:
        raise ValueError(
            f"{field_name} is a publicly known placeholder and cannot be used. "
            "Generate a unique value with: openssl rand -hex 32"
        )
    if len(value) < min_length:
        raise ValueError(
            f"{field_name} must be at least {min_length} characters (got {len(value)}). "
            "Generate one with: openssl rand -hex 32"
        )
    return value


class Settings(BaseSettings):
    DATABASE_URL: str
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # AI models & thresholds (for future use)
    THREAT_ANOMALY_THRESHOLD: float = 0.8
    THREAT_CRITICAL_THRESHOLD: float = 85.0

    # Device authentication for /telemetry/ingest. No default: a shared secret
    # that ships in the image authenticates an attacker as readily as a drone.
    DRONE_API_KEY: str

    # MAVLink Configurations.
    #
    # Disabled by default. The receiver previously started unconditionally, so a
    # deployment with no MAVLink source reconnect-looped against 127.0.0.1:14550
    # forever. It also needs an organization: telemetry ingested without one is
    # written with organization_id NULL and is then invisible to every tenant.
    MAVLINK_ENABLED: bool = False
    MAVLINK_ORGANIZATION_ID: int | None = None
    MAVLINK_HOST: str = "127.0.0.1"
    MAVLINK_PORT: int = 14550
    MAVLINK_PROTOCOL: str = "udp"
    WEBSOCKET_INTERVAL: float = 0.1 # 10Hz Broadcast
    
    # Sprint 3 AI Configurations
    MODEL_VERSION: str = "v2"
    MODELS_DIR: str = "models_ml"
    DATASET_PATH: str = "data/telemetry_dataset_v1.csv"
    CONTAMINATION: float = 0.05
    RANDOM_SEED: int = 42
    
    # ML Hyperparameters & Data Specs
    WINDOW_SIZE: int = 5
    FEATURE_VERSION: str = "v1.0"
    
    # Incident Engine Settings
    DEFAULT_MISSION_CRITICALITY: str = "NORMAL"
    SCALING_METHOD: str = "StandardScaler"
    FEATURE_LIST: str = "speed_variance,gps_drift,altitude_deviation,battery_discharge_rate,heading_deviation,flight_mode_transitions,satellite_variation,velocity_consistency"
    
    # Threshold Calibration Profiles
    THREAT_SCORE_LOW: float = 30.0
    THREAT_SCORE_MED: float = 60.0
    THREAT_SCORE_HIGH: float = 80.0

    # --- Tier 1: kinematic guard -------------------------------------------
    #
    # Physical limits of the airframe, with margin. These are deliberately set
    # beyond anything a real aircraft can do, so a valid manoeuvre cannot trip
    # them -- the cost of a false positive here is an operator grounding a
    # healthy drone. Defaults suit a fast multirotor; raise them for fixed-wing.
    GUARD_ENABLED: bool = True
    GUARD_MAX_SPEED_MPS: float = 60.0
    GUARD_MAX_CLIMB_MPS: float = 25.0
    # Disagreement between GNSS-derived ground speed and the speed the airframe
    # reports. Normal GNSS noise is well under 5 m/s; a spoofed position
    # disagrees by orders of magnitude.
    GUARD_GPS_SPEED_ERROR_MPS: float = 25.0
    GUARD_MIN_SATELLITES: int = 6

    # --- Tier 2: ML anomaly layer ------------------------------------------
    #
    # OFF by default, and that is a measured decision rather than caution. The
    # v2 model scores F1 0.086 with a 0.862 false-positive rate under
    # leave-one-flight-out validation (backend/models_ml/v2/evaluation.json).
    # Letting it raise incidents would bury real alerts under false ones.
    # Enable only to collect advisory scores for research.
    AI_INCIDENTS_ENABLED: bool = False
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("SECRET_KEY")
    @classmethod
    def _check_secret_key(cls, v: str) -> str:
        return _validate_secret(v, "SECRET_KEY")

    @field_validator("DRONE_API_KEY")
    @classmethod
    def _check_drone_api_key(cls, v: str) -> str:
        return _validate_secret(v, "DRONE_API_KEY")


@lru_cache
def get_settings() -> Settings:
    return Settings()
