from datetime import datetime, timedelta

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

import models
from database import SessionLocal
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
from utils.limiter import limiter

# Setup JSON logging
from utils.logger import logger

app = FastAPI(title="SwarmGuard AI API")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost", "http://127.0.0.1"],
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
            # Broadcast on the main event loop, which owns the sockets. The
            # detection itself runs in a worker thread; the delivery must not.
            for organization_id, payload in alerts:
                await ws_manager.broadcast(payload, organization_id)
        except Exception as e:
            logger.error(f"Error in periodic heartbeat loop: {e}")

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
    # Alembic handles migrations and hypertable initialization in production.
    asyncio.create_task(periodic_heartbeat_check())
    asyncio.create_task(periodic_database_cleanup())
    
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
from middleware.auth_middleware import get_operator_user


@app.get("/system/health")
def system_health_details(db: Session = Depends(get_db), current_user: models.User = Depends(get_operator_user)):
    """Return real system health, active node counts, and telemetry statistics for defense dashboard gauges."""
    try:
        total_drones = db.query(models.Drone).count()
        active_drones = db.query(models.Drone).filter(models.Drone.status == "ACTIVE").count()
        silent_drones = db.query(models.Drone).filter(models.Drone.status == "SILENT_POSSIBLE_JAMMING").count()
        total_incidents = db.query(models.Incident).count()
        critical_incidents = db.query(models.Incident).filter(models.Incident.severity == "CRITICAL").count()
        
        # Calculate dynamic system health score
        system_health_pct = 100
        if total_drones > 0:
            system_health_pct -= int((silent_drones / total_drones) * 40)
        if critical_incidents > 0:
            system_health_pct -= min(30, critical_incidents * 5)
        system_health_pct = max(10, system_health_pct)

        return {
            "status": "OPERATIONAL",
            "db_connected": True,
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

