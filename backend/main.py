from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
import logging
from database import engine, Base
from routers import auth, telemetry, incidents, websocket, users, commands, settings, geofence

from slowapi.errors import RateLimitExceeded

# Setup JSON logging
from utils.logger import logger
from database import SessionLocal
from services.ws_manager import broadcast_client
from datetime import datetime, timedelta
import models

from utils.limiter import limiter
from slowapi import _rate_limit_exceeded_handler

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
                check_drone_heartbeats(db)
            finally:
                db.close()
        try:
            await asyncio.to_thread(run_sync_heartbeat)
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
    Base.metadata.create_all(bind=engine)
    
    # Auto-seed default RBAC military accounts if not present
    def seed_rbac_users():
        db = SessionLocal()
        try:
            from services.auth_service import get_password_hash
            default_users = [
                ("admin", "admin@swarmguard.ai", "admin123", "admin"),
                ("commander", "commander@swarmguard.ai", "commander123", "commander"),
                ("analyst", "analyst@swarmguard.ai", "analyst123", "analyst"),
                ("observer", "observer@swarmguard.ai", "observer123", "observer"),
            ]
            for username, email, pwd, role in default_users:
                existing = db.query(models.User).filter(models.User.username == username).first()
                if not existing:
                    user = models.User(
                        username=username,
                        email=email,
                        password=get_password_hash(pwd),
                        role=role
                    )
                    db.add(user)
            db.commit()
            logger.info("Default RBAC users (admin, commander, analyst, observer) seeded into database.")
        finally:
            db.close()
    
    await asyncio.to_thread(seed_rbac_users)
    asyncio.create_task(periodic_heartbeat_check())
    asyncio.create_task(periodic_database_cleanup())
    logger.info("Started background Heartbeat & Silent Drone Monitor task (checks every 10s)")
    logger.info("Started background Data Retention Policy (prunes data older than 3 days)")

@app.on_event("shutdown")
async def shutdown_event():
    await broadcast_client.disconnect()

@app.get("/")
def read_root():
    return {"message": "Welcome to SwarmGuard AI API"}

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "SentinelAI"}

from middleware.auth_middleware import get_operator_user
from database import get_db

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

