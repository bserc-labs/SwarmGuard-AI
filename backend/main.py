import asyncio
import logging
import re
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

import models
from config import get_settings
from database import SessionLocal, engine
from middleware.admission import AdmissionLimit
from routers import (
    ai,
    ai_explain,
    auth,
    commands,
    devices,
    geofence,
    incidents,
    settings,
    telemetry,
    users,
    websocket,
)
from services.audit_service import purge_expired_audit_logs
from services.heartbeat_service import check_drone_heartbeats
from services.readiness import Probe, check_readiness
from services.retention import check_retention_policy
from services.supervisor import Supervisor
from services.ws_manager import ws_manager
from utils import metrics
from utils.error_tracking import init_error_tracking
from utils.limiter import REDIS_URL, limiter, storage_healthy

# Setup JSON logging
from utils.logger import logger
from utils.schema_check import assert_schema_current


class RedactQueryToken(logging.Filter):
    """Keep bearer tokens out of the access log.

    The WebSocket handshake carries the JWT as `?token=<jwt>`, and uvicorn's
    access logger writes the full path with its query string for every accepted
    and every rejected socket. nginx was told to stop logging /ws/, but this is
    the second place the same credential landed, and the one nginx cannot reach.
    """

    _token = re.compile(r"([?&]token=)[^&\s\"]+")

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                self._token.sub(r"\1[redacted]", arg) if isinstance(arg, str) else arg
                for arg in record.args
            )
        if isinstance(record.msg, str):
            record.msg = self._token.sub(r"\1[redacted]", record.msg)
        return True


logging.getLogger("uvicorn.access").addFilter(RedactQueryToken())

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start-up and shutdown, in one place, in order.

    Replaces the deprecated on_event startup/shutdown pair. The shape matters more than the deprecation: everything
    before `yield` must succeed for the API to serve, and everything after it
    runs on every shutdown, including the ones that used to abandon the
    background loops mid-iteration.
    """
    await startup()
    try:
        yield
    finally:
        await shutdown()


# Before the app is built, so the SDK's integrations wrap it.
_settings = get_settings()
init_error_tracking(
    _settings.SENTRY_DSN,
    environment=_settings.SWARMGUARD_ENV,
    release=_settings.SWARMGUARD_RELEASE,
    logger=logger,
)

app = FastAPI(title="SwarmGuard AI API", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Bounds how many requests can hold a database connection, which is what kept
# the API out of the pool deadlock the load test found (middleware/admission.py).
# Registered before CORS so it sits inside it: a 503 still carries CORS headers.
app.add_middleware(
    AdmissionLimit,
    limit=_settings.HTTP_MAX_IN_FLIGHT,
    wait_s=_settings.HTTP_ADMISSION_WAIT_S,
    exempt_paths=("/health", "/metrics"),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": "HTTP Exception", "detail": str(exc.detail)}
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    """422 without echoing the rejected value back.

    FastAPI's default body repeats each offending value under `input`. On
    POST /users/ a password that failed the length rule came straight back in
    the response, and from there into browser dev tools, proxy logs and crash
    reports. Location, message and type tell a client everything it needs; the
    value stays on the server. Same envelope as every other error, so a client
    can key on `error` for all of them.
    """
    detail = [
        {key: value for key, value in error.items() if key in ("type", "loc", "msg")}
        for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"error": "Validation Error", "detail": detail})


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"Unhandled error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal Server Error", "detail": "An unexpected error occurred."}
    )

# Include routers
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(telemetry.router)
app.include_router(incidents.router)
app.include_router(websocket.router)
app.include_router(ai.router)
app.include_router(ai_explain.router)
app.include_router(commands.router)
app.include_router(devices.router)
app.include_router(settings.router)
app.include_router(geofence.router)

# Outermost, so it also times the CORS layer and counts what it rejects. Added
# after the routers exist: it needs the endpoint -> template map, and Starlette
# records only the endpoint on the scope.
app.add_middleware(metrics.MetricsMiddleware, route_of_endpoint=metrics.route_templates(app))
metrics.register_collector("db-pool", metrics.PoolCollector(engine))


# The loops below are single passes; the Supervisor runs each on its interval,
# restarts it with backoff when it raises, brings the task back if it ever
# ends for any other reason, and records the time of the last successful pass.
# A bare asyncio task offered none of that: the heartbeat monitor -- the thing
# that notices a jammed, silent drone -- could die quietly, and "monitor dead"
# looked exactly like "no drone is jammed".
supervisor = Supervisor(logger)

HEARTBEAT_INTERVAL_S = 10.0
RETENTION_INTERVAL_S = 3600.0
AUDIT_RETENTION_INTERVAL_S = 86400.0


async def heartbeat_pass() -> None:
    def run_sync_heartbeat():
        db = SessionLocal()
        try:
            return check_drone_heartbeats(db)
        finally:
            db.close()

    alerts = await asyncio.to_thread(run_sync_heartbeat)

    # Broadcast on the main event loop, which owns the sockets. The detection
    # itself runs in a worker thread; the delivery must not.
    #
    # This called ws_manager.broadcast_secure(), which does not exist --
    # ConnectionManager defines connect/disconnect/broadcast/_send_local and
    # nothing else. Every iteration therefore raised AttributeError, and the
    # bare `except Exception` around the whole block swallowed it. Silent
    # drones were detected, CRITICAL SIGNAL_LOSS_JAMMING incidents were written
    # and committed by check_drone_heartbeats, and then no operator was ever
    # told: the alert reached the database and never the screen.
    #
    # Each organization is delivered independently so one failed send does not
    # suppress every later tenant's alert, and exc_info is on because a missing
    # attribute is a programming error, not a transient broker hiccup, and the
    # two must not look alike in the log again.
    for organization_id, payload in alerts:
        try:
            await ws_manager.broadcast(payload, organization_id)
        except Exception as e:
            logger.error(
                f"Heartbeat alert broadcast failed for org {organization_id}: {e}",
                exc_info=True,
            )


async def retention_pass() -> None:
    """Telemetry retention is TimescaleDB's job now (migration k1f2a3b4c5d6).

    This used to be the retention: one unbatched DELETE an hour over a
    hypertable holding up to ~13 million rows -- a long transaction, locks, and
    millions of dead tuples for autovacuum. The database drops whole chunks
    instead, and this pass only asks whether that policy is there and healthy.
    It raises when it is not, so the supervisor records a failure, /ready
    carries the error, and a metric moves -- rather than the table quietly
    growing until the disk fills.
    """

    def run_sync():
        db = SessionLocal()
        try:
            return check_retention_policy(db)
        finally:
            db.close()

    await asyncio.to_thread(run_sync)


async def audit_retention_pass() -> None:
    """Audit retention: deletes audit rows older than AUDIT_RETENTION_DAYS."""

    def run_sync() -> int:
        db = SessionLocal()
        try:
            return purge_expired_audit_logs(db, get_settings().AUDIT_RETENTION_DAYS)
        finally:
            db.close()

    deleted = await asyncio.to_thread(run_sync)
    if deleted:
        logger.info(f"Audit retention: removed {deleted} audit rows older than "
                    f"{get_settings().AUDIT_RETENTION_DAYS} days.")


# run_first=False: drones get one interval to report after a start before any
# of them is declared silent, as before.
supervisor.register("heartbeat-monitor", heartbeat_pass, HEARTBEAT_INTERVAL_S, run_first=False)
supervisor.register("telemetry-retention", retention_pass, RETENTION_INTERVAL_S)
supervisor.register("audit-retention", audit_retention_pass, AUDIT_RETENTION_INTERVAL_S)
metrics.register_collector("supervisor", metrics.SupervisorCollector(supervisor))


# How long shutdown waits for the background loops to acknowledge cancellation
# before giving up on them. Each loop runs its work in a worker thread; a
# cancellation is only observed between iterations, so this is the longest
# single iteration we are prepared to wait for.
SHUTDOWN_GRACE_S = 10.0


async def startup() -> None:
    logger.info("Initializing SwarmGuard AI Backend...")
    # Everything behind asyncio.to_thread -- detection, MAVLink persistence, the
    # background loops -- runs here, each job holding at most one connection.
    # Sized from settings so it fits the pool (Settings._connections_fit_the_pool);
    # Python's default follows the host's CPU count instead.
    asyncio.get_running_loop().set_default_executor(
        ThreadPoolExecutor(
            max_workers=get_settings().BACKGROUND_THREADS, thread_name_prefix="swarmguard-bg"
        )
    )
    # Migrations are applied by the migrate job, never here. Fail now, with the
    # reason, rather than on whichever request first meets a missing column.
    # In a worker thread: it is a blocking database call on the event loop.
    if get_settings().REQUIRE_SCHEMA_AT_HEAD:
        await asyncio.to_thread(assert_schema_current, engine, logger)
    supervisor.start()

    # Start MAVLink receiver
    from services.mavlink_receiver import mavlink_receiver
    await mavlink_receiver.start()

    logger.info("Started background Heartbeat & Silent Drone Monitor task (checks every 10s)")
    logger.info("Started background retention-policy check (TimescaleDB drops chunks older than 3 days)")


async def shutdown() -> None:
    logger.info("Shutting down SwarmGuard AI Backend...")

    # Stop producing before closing the sockets that deliver: the loops first,
    # then the receiver, then the WebSocket manager. They used to be left
    # running until the event loop was torn down under them, which is why a
    # shutdown could log a heartbeat error for a database that had already
    # gone away.
    for name in await supervisor.stop(SHUTDOWN_GRACE_S):
        logger.error(f"Background loop {name!r} did not stop within {SHUTDOWN_GRACE_S}s")

    try:
        from services.mavlink_receiver import mavlink_receiver
        await mavlink_receiver.stop()
    except Exception as e:
        logger.error(f"Error stopping MAVLink receiver: {e}")

    try:
        await ws_manager.shutdown()
    except Exception as e:
        logger.error(f"Error shutting down WebSocket manager: {e}")


@app.get("/")
def read_root():
    return {"message": "Welcome to SwarmGuard AI API"}

@app.get("/health")
def health_check():
    """Liveness: the process is up and serving. Nothing more -- see /ready."""
    return {"status": "ok", "service": "SentinelAI"}


@app.get("/metrics")
def metrics_endpoint(request: Request):
    """Prometheus exposition. See utils/metrics.py for what is measured and why.

    Not proxied by nginx; loopback-only on the host; optionally token-gated
    (METRICS_TOKEN). Scrape it from inside the compose network:
    http://backend:8000/metrics.
    """
    token = get_settings().METRICS_TOKEN
    if token:
        presented = request.headers.get("authorization", "")
        if presented != f"Bearer {token}":
            return JSONResponse(status_code=401, content={"error": "HTTP Exception", "detail": "Not authenticated"})
    body, content_type = metrics.render()
    return Response(content=body, media_type=content_type)


@app.get("/ready")
async def readiness_check():
    """Readiness: the database and Redis answer, so requests will succeed.

    Unauthenticated and cheap, because it is what the container health check
    and an orchestrator ask every few seconds. 503 when a required dependency
    is down; the body says which. Verified by experiment: with postgres
    stopped, /health kept answering 200 and the container stayed healthy for
    as long as anyone watched. This is the signal that was missing.
    """
    settings = get_settings()
    readiness = await check_readiness(
        engine,
        REDIS_URL,
        redis_required=settings.READINESS_REQUIRES_REDIS,
        timeout_s=settings.READINESS_TIMEOUT_S,
    )
    # A loop that has stopped ticking is a dependency that is down. For the
    # heartbeat monitor it is the difference between "no drone is jammed" and
    # "nobody is looking".
    stalled = supervisor.stalled()
    readiness.checks["background"] = Probe(
        not stalled,
        "loops ticking" if not stalled else f"stalled: {', '.join(stalled)}",
    )
    body = readiness.as_dict()
    body["background"] = supervisor.status()
    return JSONResponse(status_code=200 if readiness.ready else 503, content=body)

from database import get_db
from middleware.auth_middleware import TenantContext, get_tenant_context


@app.get("/system/health")
def system_health_details(
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    """Fleet and incident counters for the dashboard gauges, scoped to one tenant.

    Every count here was previously unfiltered -- `db.query(Drone).count()` over
    the whole table -- while the route was gated only on role. An operator saw
    every other organization's fleet size, incident total and critical count on
    the first screen after signing in, and the derived health percentage was
    dragged down by incidents belonging to tenants they cannot see.

    The dependency is `get_tenant_context` rather than the previous
    `get_operator_user`: it admits the same five roles, since every role that
    could reach this route already holds an organization, but it yields the
    organization to scope by instead of just a role check.
    """
    try:
        org = tenant.organization_id
        drones = db.query(models.Drone).filter(models.Drone.organization_id == org)
        incidents = db.query(models.Incident).filter(models.Incident.organization_id == org)

        total_drones = drones.count()
        active_drones = drones.filter(models.Drone.status == "ACTIVE").count()
        silent_drones = drones.filter(models.Drone.status == "SILENT_POSSIBLE_JAMMING").count()
        total_incidents = incidents.count()
        critical_incidents = incidents.filter(models.Incident.severity == "CRITICAL").count()
        
        # Calculate dynamic system health score
        system_health_pct = 100
        if total_drones > 0:
            system_health_pct -= int((silent_drones / total_drones) * 40)
        if critical_incidents > 0:
            system_health_pct -= min(30, critical_incidents * 5)
        system_health_pct = max(10, system_health_pct)

        # The rate limiter fails open when Redis is unreachable (see
        # utils/limiter.py), which keeps authentication alive but silently
        # weakens the limit. Report it, so "degraded" is something an operator
        # is told rather than something they deduce.
        limiter_ok, limiter_detail = storage_healthy()

        return {
            "status": "OPERATIONAL" if limiter_ok else "DEGRADED",
            "db_connected": True,
            "rate_limiter": {"healthy": limiter_ok, "detail": limiter_detail},
            "system_health_pct": system_health_pct,
            "signal_fidelity_pct": 98 if silent_drones == 0 else 72,
            "active_drones": active_drones,
            "total_drones": total_drones,
            "silent_drones": silent_drones,
            "total_incidents": total_incidents,
            "critical_incidents": critical_incidents,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Health details query error: {e}")
        return {
            "status": "DEGRADED",
            "db_connected": False,
            "system_health_pct": 50,
            "signal_fidelity_pct": 50,
        }

