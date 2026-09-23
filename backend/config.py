import os
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Where Docker and Kubernetes mount secrets, one file per value, named after
# the setting (`/run/secrets/secret_key` fills SECRET_KEY; matching ignores
# case and surrounding whitespace is stripped).
#
# A secret passed as an environment variable is printed by `docker inspect`,
# inherited by every child process and captured in crash dumps. A mounted file
# is none of those. Environment variables are still read, and still win, so a
# native run, CI and the test suite are unchanged; compose deliberately passes
# the secrets as *empty* variables, which env_ignore_empty treats as unset, so
# the value can only come from the file.
#
# Only handed to pydantic when it exists: it warns on every start otherwise.
SECRETS_DIR = Path(os.getenv("SECRETS_DIR", "/run/secrets"))


def _secrets_dir() -> str | None:
    return str(SECRETS_DIR) if SECRETS_DIR.is_dir() else None


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

# Database passwords that are fine for a throwaway CI service container and not
# fine anywhere else. The CI workflow deliberately uses postgres/password for an
# ephemeral database that exists only for the length of a run; the risk is a
# developer .env copying those values and a deployment inheriting them.
WEAK_DB_PASSWORDS = {
    "password", "postgres", "root", "admin", "changeme", "secret", "swarmguard",
    "123456", "test", "dev", "local",
}


def _db_password(database_url: str) -> str | None:
    """The password embedded in a SQLAlchemy URL, if there is one."""
    try:
        from urllib.parse import unquote, urlparse

        parsed = urlparse(database_url)
        return unquote(parsed.password) if parsed.password else None
    except Exception:
        return None


def _warn_if_weak_db_password(password: str | None) -> None:
    if password and password.lower() in WEAK_DB_PASSWORDS:
        import warnings

        warnings.warn(
            f"The database connection uses a weak, guessable password ({len(password)} "
            "chars, dictionary word). This is acceptable only for a local or "
            "CI database that is not reachable off-host. Generate one with: "
            "openssl rand -hex 32",
            UserWarning,
            stacklevel=3,
        )


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
    # The database password, supplied apart from the URL so that the URL can sit
    # in ordinary configuration and only this is secret. It fills in a
    # DATABASE_URL that carries no password; a URL with its own is left alone.
    # Under compose it arrives as the file /run/secrets/database_password.
    DATABASE_PASSWORD: str | None = None
    SECRET_KEY: str
    # Rotation without an outage. Tokens are always *signed* with SECRET_KEY and
    # *verified* against SECRET_KEY and then this. To rotate: move the current
    # key here, put a new one in SECRET_KEY, restart; clear this again once
    # ACCESS_TOKEN_EXPIRE_MINUTES have passed and every old token has expired.
    #
    # Without it, changing SECRET_KEY invalidates every session at the same
    # instant, so in practice the key is never changed. If the key has actually
    # leaked, that instant logout is exactly what you want: rotate and leave
    # this empty (scripts/rotate-secret-key.sh --emergency).
    SECRET_KEY_PREVIOUS: str | None = None
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # Login attempts per client address. Five a minute is the production value
    # and the default; it exists as a setting only so the live integration suite
    # can be given room to run.
    #
    # tests/test_sprint7_security.py drives a real server over HTTP and every
    # test in it authenticates. Against the 5/minute limit the third test
    # onwards always took a 429 and skipped -- so of six tests covering auth,
    # RBAC, tenant isolation, audit and rate limiting, at most two ever
    # executed. Run one per rate-limit window, all six pass; the suite was
    # failing to run, not failing.
    #
    # Raise this only for an ephemeral test deployment. A production value
    # loose enough to make brute force cheap is worse than no limit, because it
    # looks like protection.
    LOGIN_RATE_LIMIT: str = "5/minute"

    # Telemetry ingest per client address. Measured (reports/06-LOAD-TEST-
    # RESULTS.md): precise at the limit, and the limiter -- not the pool or the
    # CPU -- is what caps throughput. Keyed by client address, so every drone
    # behind one ground-station uplink shares it: 20 drones get 2.5 Hz each.
    # Raise it for a larger fleet behind one uplink, or for a capacity test.
    INGEST_RATE_LIMIT: str = "50/second"

    # AI models & thresholds (for future use)
    THREAT_ANOMALY_THRESHOLD: float = 0.8
    THREAT_CRITICAL_THRESHOLD: float = 85.0

    # Device authentication for /telemetry/ingest. No default: a shared secret
    # that ships in the image authenticates an attacker as readily as a drone.
    DRONE_API_KEY: str
    # Accept DRONE_API_KEY on ingest as well as per-device keys. On by default so
    # an upgrade breaks nothing; turn it off once swarmguard_device_auth_total
    # shows no more shared_key traffic, and a lost airframe stops being a lost
    # fleet. See docs/OPERATIONS.md, "Device credentials".
    DEVICE_SHARED_KEY_ENABLED: bool = True

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

    # --- Database connection pool ------------------------------------------
    #
    # Ingest consumes two connections per packet -- the request session and the
    # background detection task's own session, held concurrently. Sized to
    # clear the 50 req/s ingest rate limit with headroom, and to stay inside
    # PostgreSQL's default max_connections of 100 for one backend instance.
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 40
    # Fail fast under saturation instead of holding requests for SQLAlchemy's
    # 30 s default, which the client times out before and so hides the cause.
    DB_POOL_TIMEOUT: int = 10

    # --- Admission: never ask the pool for more than it has ---------------------
    #
    # The load test of 2026-09-22 stopped the API at 100 packets/second: all 60
    # connections sat "idle in transaction" after the authentication lookup,
    # each request waiting for a worker thread to run its endpoint, while every
    # worker thread held a newer request waiting for a connection. Only the
    # 10 s pool timeout broke it, and it re-formed at once. Nothing bounded how
    # many requests could hold a connection. Now two things do:
    #
    # HTTP requests inside the application at once. Each holds at most one
    # request-session connection. Beyond this, requests wait at the door holding
    # nothing, and after HTTP_ADMISSION_WAIT_S get 503 with Retry-After.
    HTTP_MAX_IN_FLIGHT: int = 40
    HTTP_ADMISSION_WAIT_S: float = 5.0
    # Threads behind asyncio.to_thread: detection, MAVLink persistence, the
    # background loops, the readiness probe. Each holds at most one connection.
    # Python's default is min(32, CPUs + 4), which follows the host, not the pool.
    BACKGROUND_THREADS: int = 12
    # Connections left for work outside both bounds: WebSocket authentication,
    # and slack. HTTP_MAX_IN_FLIGHT + BACKGROUND_THREADS + this must fit in
    # DB_POOL_SIZE + DB_MAX_OVERFLOW; startup refuses otherwise.
    DB_POOL_RESERVE: int = 4

    # --- CORS ----------------------------------------------------------------
    #
    # Comma-separated origins allowed to call the API from a browser with
    # credentials. The deployed frontend does not need to be listed: nginx
    # serves the page and proxies /api on one origin, so those requests are
    # same-origin and CORS never applies. This is for a page served from
    # somewhere else -- in practice the Vite dev server -- and for the API
    # reached directly on the loopback port.
    #
    # Never "*": with credentials allowed that would let any site a logged-in
    # operator visits drive the API as them.
    CORS_ALLOWED_ORIGINS: str = (
        "http://localhost:5173,https://localhost,https://127.0.0.1,"
        "http://localhost,http://127.0.0.1"
    )

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.CORS_ALLOWED_ORIGINS.split(",") if o.strip()]

    # --- Audit retention --------------------------------------------------------
    #
    # audit_logs is append-only at the database level; a table that can only
    # grow is its own outage. Rows older than this are deleted once a day by a
    # supervised loop, through the maintenance flag the trigger requires. 0
    # keeps everything -- for a deployment whose retention is set by regulation
    # rather than disk, say so here and archive elsewhere.
    AUDIT_RETENTION_DAYS: int = 365

    # --- Error tracking -------------------------------------------------------
    #
    # Unhandled exceptions become an opaque 500 and one log line. With a DSN
    # they are also grouped, counted and attached to the request that raised
    # them, in Sentry or anything that speaks its protocol. Off when unset.
    # Credentials are scrubbed before an event leaves the process
    # (utils/error_tracking.py); turn on server-side scrubbing as well.
    SENTRY_DSN: str | None = None
    # Tags every event and metric with where it came from.
    SWARMGUARD_ENV: str = "development"
    # The image tag CI built; deploy.sh passes it through so an issue names the
    # exact commit that raised it.
    SWARMGUARD_RELEASE: str | None = None

    # --- Metrics --------------------------------------------------------------
    #
    # /metrics is the Prometheus exposition. nginx does not proxy it (404 through
    # the public front), and the API port is loopback-only, so by default it is
    # reachable only from inside the compose network and the host. Set a token
    # to require `Authorization: Bearer <token>` as well -- for a scraper that
    # is not on the same network, or a host with other users.
    METRICS_TOKEN: str | None = None

    # --- Readiness ------------------------------------------------------------
    #
    # /ready probes the database and Redis and answers 503 when one that
    # matters is down; /health stays a bare liveness answer. Redis down means no
    # live alerts and a weaker login rate limit, so by default it makes the
    # instance not ready. Set this false when several replicas sit behind a
    # load balancer and a Redis outage should degrade rather than take every
    # replica out at once.
    READINESS_REQUIRES_REDIS: bool = True
    # Per-probe deadline. An orchestrator asks every few seconds; a probe that
    # hangs is itself reported as not ready when this passes.
    READINESS_TIMEOUT_S: float = 3.0

    # --- Schema guard -------------------------------------------------------
    #
    # Migrations run once, from a dedicated job, not from every container start
    # (two replicas starting together ran the same DDL concurrently). The API
    # therefore checks at startup that the database is at the revision this
    # build ships, and refuses to serve if it is behind -- see
    # utils/schema_check.py for why "ahead" only warns.
    #
    # Turn this off only to bring the API up against a database you are in the
    # middle of repairing by hand.
    REQUIRE_SCHEMA_AT_HEAD: bool = True

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
    # Clock-rate sanity bound for the device sample clock (sample_time_ms).
    # How much longer the device may say two samples were apart than their
    # packets were on arrival before the device clock is disbelieved for that
    # pair and the guard falls back to arrival time. Covers delivery jitter and
    # buffered bursts; a device interval far beyond that means a broken or
    # mis-scaled clock, and dividing by it would hide a real jump.
    GUARD_DEVICE_CLOCK_MAX_LEAD_S: float = 10.0
    # How far a packet's device clock may sit behind everything else in the
    # guard's window and still be read as a late packet (rated against its
    # nearest neighbour on the device clock) rather than as a reboot or counter
    # wrap (rated on arrival time). Resets step back by the whole uptime;
    # overloaded delivery steps back by queueing delay.
    GUARD_DEVICE_CLOCK_MAX_REORDER_S: float = 10.0

    # --- Tier 2: ML anomaly layer ------------------------------------------
    #
    # OFF by default, and that is a measured decision rather than caution. The
    # v2 model scores F1 0.086 with a 0.862 false-positive rate under
    # leave-one-flight-out validation (backend/models_ml/v2/evaluation.json).
    # Letting it raise incidents would bury real alerts under false ones.
    # Enable only to collect advisory scores for research.
    AI_INCIDENTS_ENABLED: bool = False
    
    # env_ignore_empty: a blank assignment such as `MAVLINK_ORGANIZATION_ID=`
    # means "unset", not "the empty string". .env.example ships several blanks
    # and compose now passes .env through to the container whole; without this
    # an empty string reached the `int | None` field and startup died with
    # int_parsing before the first request.
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
        secrets_dir=_secrets_dir(),
    )

    @field_validator("SECRET_KEY")
    @classmethod
    def _check_secret_key(cls, v: str) -> str:
        return _validate_secret(v, "SECRET_KEY")

    @field_validator("DRONE_API_KEY")
    @classmethod
    def _check_drone_api_key(cls, v: str) -> str:
        return _validate_secret(v, "DRONE_API_KEY")

    @field_validator("SECRET_KEY_PREVIOUS", mode="before")
    @classmethod
    def _check_previous_secret_key(cls, v: str | None) -> str | None:
        # Compose always mounts the file; an empty one means "not rotating".
        if v is None or not str(v).strip():
            return None
        return _validate_secret(str(v).strip(), "SECRET_KEY_PREVIOUS")

    @field_validator("DATABASE_URL")
    @classmethod
    def _warn_on_weak_database_password(cls, v: str) -> str:
        """Warn, loudly, on a dictionary-word database password.

        Deliberately a warning and not a hard failure, unlike SECRET_KEY and
        DRONE_API_KEY. Those two are read directly by the application and a bad
        value is always wrong. The database password is also what the compose
        file and the CI service container use, and refusing to start would break
        a working local stack over a credential that -- because compose exposes
        Postgres only on the internal network -- is not reachable from outside
        the host today.

        Escalate this to a failure once deployment sets its own credentials.
        """
        _warn_if_weak_db_password(_db_password(v))
        return v

    @field_validator("CORS_ALLOWED_ORIGINS")
    @classmethod
    def _no_wildcard_origin(cls, v: str) -> str:
        if any(origin.strip() == "*" for origin in v.split(",")):
            raise ValueError(
                "CORS_ALLOWED_ORIGINS must not contain '*': the API allows credentials, so a "
                "wildcard would let any website act as a signed-in operator. List origins."
            )
        return v

    @model_validator(mode="after")
    def _previous_key_must_differ(self) -> "Settings":
        if self.SECRET_KEY_PREVIOUS and self.SECRET_KEY_PREVIOUS == self.SECRET_KEY:
            raise ValueError(
                "SECRET_KEY_PREVIOUS is the same as SECRET_KEY: that is not a rotation. "
                "Generate a new SECRET_KEY, or clear SECRET_KEY_PREVIOUS."
            )
        return self

    @model_validator(mode="after")
    def _connections_fit_the_pool(self) -> "Settings":
        """Demand that can never exceed the pool cannot deadlock on it."""
        demand = self.HTTP_MAX_IN_FLIGHT + self.BACKGROUND_THREADS + self.DB_POOL_RESERVE
        pool = self.DB_POOL_SIZE + self.DB_MAX_OVERFLOW
        if min(self.HTTP_MAX_IN_FLIGHT, self.BACKGROUND_THREADS) < 1:
            raise ValueError("HTTP_MAX_IN_FLIGHT and BACKGROUND_THREADS must each be at least 1.")
        if demand > pool:
            raise ValueError(
                f"HTTP_MAX_IN_FLIGHT ({self.HTTP_MAX_IN_FLIGHT}) + BACKGROUND_THREADS "
                f"({self.BACKGROUND_THREADS}) + DB_POOL_RESERVE ({self.DB_POOL_RESERVE}) = {demand} "
                f"connections, but the pool holds DB_POOL_SIZE + DB_MAX_OVERFLOW = {pool}. "
                "Requests would wait on the pool while holding it, which deadlocks. "
                "Lower the first two or raise the pool (and PostgreSQL's max_connections)."
            )
        return self

    @model_validator(mode="after")
    def _assemble_database_url(self) -> "Settings":
        """Join DATABASE_PASSWORD into a DATABASE_URL that has none."""
        if not self.DATABASE_PASSWORD or _db_password(self.DATABASE_URL) is not None:
            return self
        from sqlalchemy.engine import make_url
        from sqlalchemy.exc import ArgumentError

        try:
            url = make_url(self.DATABASE_URL)
        except ArgumentError as exc:
            raise ValueError("DATABASE_URL is not a valid database URL") from exc
        # .set() percent-encodes, so a password containing @ : / # survives.
        self.DATABASE_URL = url.set(password=self.DATABASE_PASSWORD).render_as_string(
            hide_password=False
        )
        _warn_if_weak_db_password(self.DATABASE_PASSWORD)
        return self


@lru_cache
def get_settings() -> Settings:
    # Required fields come from the environment / .env via pydantic-settings.
    return Settings()  # type: ignore[call-arg]
