import logging
import re
from datetime import datetime, timedelta

from fastapi import Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

import models
from config import get_settings
from database import SessionLocal, engine
from routers import (
    ai,
    ai_explain,
    auth,
    commands,
    geofence,
    incidents,
    settings,
    telemetry,
    users,
    websocket,
)
from services.ws_manager import ws_manager
from utils.limiter import limiter, storage_healthy

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

app = FastAPI(title="SwarmGuard AI API")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

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
app.include_router(settings.router)
app.include_router(geofence.router)

import asyncio

from services.heartbeat_service import check_drone_heartbeats


async def periodic_heartbeat_check():
    while True:
        await asyncio.sleep(10)

        def run_sync_heartbeat():
            db = SessionLocal()
            try:
                return check_drone_heartbeats(db)
            finally:
                db.close()

        try:
            alerts = await asyncio.to_thread(run_sync_heartbeat)
        except Exception as e:
            logger.error(f"Heartbeat detection failed: {e}", exc_info=True)
            continue

        # Broadcast on the main event loop, which owns the sockets. The
        # detection itself runs in a worker thread; the delivery must not.
        #
        # This called ws_manager.broadcast_secure(), which does not exist --
        # ConnectionManager defines connect/disconnect/broadcast/_send_local and
        # nothing else. Every iteration therefore raised AttributeError, and the
        # bare `except Exception` around the whole block swallowed it. Silent
        # drones were detected, CRITICAL SIGNAL_LOSS_JAMMING incidents were
        # written and committed by check_drone_heartbeats, and then no operator
        # was ever told: the alert reached the database and never the screen.
        #
        # Each organization is delivered independently so one failed send does
        # not suppress every later tenant's alert, and exc_info is on because a
        # missing attribute is a programming error, not a transient broker
        # hiccup, and the two must not look alike in the log again.
        for organization_id, payload in alerts:
            try:
                await ws_manager.broadcast(payload, organization_id)
            except Exception as e:
                logger.error(
                    f"Heartbeat alert broadcast failed for org {organization_id}: {e}",
                    exc_info=True,
                )

async def periodic_database_cleanup():
    """Data Retention Policy: Deletes telemetry older than 3 days every hour."""
    while True:
        def run_sync_cleanup():
            db = SessionLocal()
            try:
                cutoff = datetime.utcnow() - timedelta(days=3)
                deleted = db.query(models.TelemetryLog).filter(models.TelemetryLog.created_at < cutoff).delete()
                db.commit()
                if deleted > 0:
                    logger.info(f"Data Retention Policy executed: Pruned {deleted} old telemetry rows.")
            finally:
                db.close()
        try:
            await asyncio.to_thread(run_sync_cleanup)
        except Exception as e:
            logger.error(f"Error in database cleanup loop: {e}")
        # Run every hour
        await asyncio.sleep(3600)

@app.on_event("startup")
async def startup_event():
    logger.info("Initializing SwarmGuard AI Backend...")
    # Migrations are applied by the migrate job, never here. Fail now, with the
    # reason, rather than on whichever request first meets a missing column.
    # In a worker thread: it is a blocking database call on the event loop.
    if get_settings().REQUIRE_SCHEMA_AT_HEAD:
        await asyncio.to_thread(assert_schema_current, engine, logger)
    # Hold references: a bare create_task() result can be garbage-collected
    # while the coroutine is still running.
    app.state.background_tasks = [
        asyncio.create_task(periodic_heartbeat_check()),
        asyncio.create_task(periodic_database_cleanup()),
    ]
    
    # Start MAVLink receiver
    from services.mavlink_receiver import mavlink_receiver
    await mavlink_receiver.start()
    
    logger.info("Started background Heartbeat & Silent Drone Monitor task (checks every 10s)")
    logger.info("Started background Data Retention Policy (prunes data older than 3 days)")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down SwarmGuard AI Backend...")
    try:
        await ws_manager.shutdown()
    except Exception as e:
        logger.error(f"Error shutting down WebSocket manager: {e}")
    
    # Stop MAVLink receiver
    try:
        from services.mavlink_receiver import mavlink_receiver
        await mavlink_receiver.stop()
    except Exception as e:
        logger.error(f"Error stopping MAVLink receiver: {e}")

@app.get("/")
def read_root():
    return {"message": "Welcome to SwarmGuard AI API"}

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "SentinelAI"}

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

