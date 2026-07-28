from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
import logging
from database import engine, Base
from routers import auth, telemetry, incidents, websocket, users, commands

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Setup JSON logging
from utils.logger import logger

# Create database tables
Base.metadata.create_all(bind=engine)

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="SwarmGuard AI API")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
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

import asyncio
from database import SessionLocal
from services.heartbeat_service import check_drone_heartbeats

async def periodic_heartbeat_check():
    while True:
        await asyncio.sleep(10)
        try:
            db = SessionLocal()
            try:
                check_drone_heartbeats(db)
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error in periodic heartbeat loop: {e}")

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(periodic_heartbeat_check())
    logger.info("Started background Heartbeat & Silent Drone Monitor task (checks every 10s)")

@app.get("/")
def read_root():
    return {"message": "Welcome to SwarmGuard AI API"}

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "SentinelAI"}

@app.get("/system/health")
def system_health_details(db: Session = Depends(SessionLocal)):
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
            "error": str(e)
        }
    finally:
        db.close()

