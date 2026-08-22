from datetime import datetime
from typing import List

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    status,
)
from sqlalchemy.orm import Session

import models
import schemas
from database import get_db
from services.detection_pipeline import run_detection
from services.ws_manager import ws_manager
from utils.limiter import limiter
from utils.logger import logger
from config import get_settings
from services.telemetry_service import telemetry_service
from middleware.auth_middleware import get_tenant_context, TenantContext, require_permission, get_current_user
from middleware.rbac import Permissions
from services.audit_service import audit_service

settings = get_settings()
EXPECTED_DRONE_API_KEY = settings.DRONE_API_KEY

router = APIRouter(prefix="/telemetry", tags=["telemetry"])

@router.post("/ingest")
@limiter.limit("50/second")
def ingest_telemetry(
    request: Request,
    packet: schemas.TelemetryPacket, 
    background_tasks: BackgroundTasks, 
    x_drone_api_key: str = Header(None),
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(require_permission(Permissions.TELEMETRY_INGEST)),
):
    # Drone Device Security Check (Anti-Spoofing)
    if not x_drone_api_key or x_drone_api_key != EXPECTED_DRONE_API_KEY:
        logger.warning(f"🚨 UNAUTHORIZED DRONE SPOOFING ATTEMPT: {packet.drone_id} sent invalid or missing API Key!")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Device Authentication Failed: Invalid or missing API Key for drone '{packet.drone_id}'"
        )
    
    try:
        processed_data = telemetry_service.process_telemetry(
            packet, db, organization_id=tenant.organization_id
        )
        # Scoped to the ingesting device's organization so the live feed cannot
        # cross tenants.
        background_tasks.add_task(
            ws_manager.broadcast, processed_data, tenant.organization_id
        )

        # Anomaly detection runs after the packet is committed, off the request
        # path. Rolling features are computed against the preceding packets, so
        # the detector reads its window back from the database rather than
        # scoring this packet in isolation.
        background_tasks.add_task(
            run_detection, packet.drone_id, tenant.organization_id
        )

        audit_service.log_from_context(
            db=db,
            tenant=tenant,
            action="TELEMETRY_INGEST",
            resource="TelemetryLog",
            resource_id=packet.drone_id,
            details=f"Ingested telemetry for drone {packet.drone_id}",
            ip_address=request.client.host if request.client else None,
        )

        return {"status": "success", "data": processed_data}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to process telemetry: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")

@router.get("/latest")
def get_latest_telemetry(
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(require_permission(Permissions.TELEMETRY_READ)),
):
    """Fetch the latest telemetry packet for each active drone."""
    # Note: DISTINCT ON is specific to PostgreSQL
    logs = db.query(models.TelemetryLog).filter(
        models.TelemetryLog.organization_id == tenant.organization_id
    ).order_by(
        models.TelemetryLog.drone_id, 
        models.TelemetryLog.created_at.desc()
    ).distinct(models.TelemetryLog.drone_id).all()
    return logs

@router.get("/health/status")
def get_telemetry_health():
    """Health check endpoint for telemetry ingestion pipeline."""
    from services.mavlink_receiver import mavlink_receiver
    return {
        "status": "healthy" if mavlink_receiver.running else "down",
        "mavlink_connected": mavlink_receiver.mav_connection is not None,
        "packets_processed": mavlink_receiver.packet_sequence
    }

@router.get("/history")
def get_telemetry_history(
    start_time: str,
    end_time: str,
    limit: int = Query(500, le=2000),
    skip: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(require_permission(Permissions.TELEMETRY_READ)),
):
    """Fetch historical telemetry bounded by time for DVR playback with pagination."""
    try:
        start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
        
        logs = db.query(models.TelemetryLog).filter(
            models.TelemetryLog.organization_id == tenant.organization_id,
            models.TelemetryLog.created_at >= start_dt,
            models.TelemetryLog.created_at <= end_dt
        ).order_by(models.TelemetryLog.created_at.asc()).offset(skip).limit(limit).all()
        
        return logs
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid time format. Use ISO 8601.")

@router.get("/{drone_id}")
def get_drone_telemetry(
    drone_id: str,
    limit: int = 100,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(require_permission(Permissions.TELEMETRY_READ)),
):
    """Fetch recent telemetry for a specific drone."""
    logs = db.query(models.TelemetryLog).filter(
        models.TelemetryLog.organization_id == tenant.organization_id,
        models.TelemetryLog.drone_id == drone_id
    ).order_by(models.TelemetryLog.created_at.desc()).limit(limit).all()
    if not logs:
        raise HTTPException(status_code=404, detail="Drone not found or no telemetry available")
    return logs

@router.get("/{drone_id}/latest")
def get_drone_latest_telemetry(
    drone_id: str,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(require_permission(Permissions.TELEMETRY_READ)),
):
    """Fetch the single latest telemetry packet for a specific drone."""
    log = db.query(models.TelemetryLog).filter(
        models.TelemetryLog.organization_id == tenant.organization_id,
        models.TelemetryLog.drone_id == drone_id
    ).order_by(models.TelemetryLog.created_at.desc()).first()
    if not log:
        raise HTTPException(status_code=404, detail="Drone not found or no telemetry available")
    return log
