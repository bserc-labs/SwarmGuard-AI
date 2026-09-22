from datetime import datetime

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
from sqlalchemy import select, true
from sqlalchemy.orm import Session, aliased

import models
import schemas
from config import get_settings
from database import get_db
from middleware.auth_middleware import TenantContext, require_permission
from middleware.rbac import Permissions
from services.audit_service import audit_service
from services.detection_pipeline import run_detection
from services.telemetry_service import telemetry_service
from services.ws_manager import ws_manager
from utils.limiter import limiter
from utils.logger import logger
from utils.metrics import INGEST

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
        # Recorded, not just logged. A caller holding a valid operator token but
        # presenting the wrong device key is the signature of a compromised or
        # misconfigured airframe, and it is exactly the event an investigator
        # comes looking for. `commit=True` because this request ends in a 403
        # and there is no later write to carry the row.
        audit_service.log_from_context(
            db=db,
            tenant=tenant,
            action="TELEMETRY_DEVICE_AUTH_FAILED",
            resource="TelemetryLog",
            resource_id=packet.drone_id,
            reason="missing_api_key" if not x_drone_api_key else "invalid_api_key",
            details=(
                f"Rejected telemetry for drone '{packet.drone_id}': device API key "
                f"{'missing' if not x_drone_api_key else 'did not match'}."
            ),
            ip_address=request.client.host if request.client else None,
            commit=True,
        )
        INGEST.labels("rejected_device_key").inc()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Device Authentication Failed: Invalid or missing API Key for drone '{packet.drone_id}'"
        )

    try:
        processed_data = telemetry_service.process_telemetry(
            packet, db, organization_id=tenant.organization_id, actor=tenant.username
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

        # No per-packet audit row. There used to be a TELEMETRY_INGEST entry
        # here, and it never reached the database: process_telemetry had already
        # committed, this staged an INSERT, and the request-scoped session was
        # closed without another commit -- which rolls it back. The trail was
        # silently empty rather than merely wrong.
        #
        # Committing it would have been the worse fix. This route is rate
        # limited at 50 req/s, so a row per packet is ~4.3 M rows a day on a
        # table that has no retention policy. `telemetry_logs` already records
        # every packet. What is audited instead is the security-relevant subset:
        # a rejected device key (above) and a drone seen for the first time
        # (inside process_telemetry, in the same transaction as the drone row).
        INGEST.labels("accepted").inc()
        return {"status": "success", "data": processed_data}
    except ValueError as e:
        INGEST.labels("rejected_bad_request").inc()
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        INGEST.labels("error").inc()
        logger.error(f"Failed to process telemetry: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error") from e

@router.get("/latest")
def get_latest_telemetry(
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(require_permission(Permissions.TELEMETRY_READ)),
):
    """Fetch the latest telemetry packet for each active drone."""
    # One index lookup per drone, not one sort of the tenant's whole history.
    #
    # This used to be `SELECT DISTINCT ON (drone_id) ... ORDER BY drone_id,
    # created_at DESC` over every telemetry row the organization holds -- no
    # LIMIT, and no index covering that order, so the planner fetched them all
    # and sorted (EXPLAIN: Unique -> Sort -> Seq Scan). The table keeps three
    # days of packets; at the ingest cap that is about 13 million rows, sorted
    # on every poll from three dashboard pages.
    #
    # `drones` holds exactly one row per (organization_id, drone_id)
    # (uq_drones_org_drone_id, migration f6a7b8c9d0e1) and is refreshed by every
    # packet, so it is the natural driver: for each drone the LATERAL subquery
    # walks ix_telemetry_logs_org_drone_created_at (migration j0e1f2a3b4c5)
    # newest-first and stops at the first row. Cost is proportional to fleet
    # size, not to history length. Still PostgreSQL-only, as DISTINCT ON was.
    #
    # A drone that has never reported has no telemetry row and is therefore
    # absent, exactly as before: the join is inner.
    newest = (
        select(models.TelemetryLog)
        .where(
            models.TelemetryLog.organization_id == models.Drone.organization_id,
            models.TelemetryLog.drone_id == models.Drone.drone_id,
        )
        .order_by(models.TelemetryLog.created_at.desc(), models.TelemetryLog.id.desc())
        .limit(1)
        .lateral("newest")
    )
    newest_log = aliased(models.TelemetryLog, newest)
    stmt = (
        select(newest_log)
        .select_from(models.Drone)
        .join(newest, true())
        .where(models.Drone.organization_id == tenant.organization_id)
        .order_by(models.Drone.drone_id)
    )
    return db.execute(stmt).scalars().all()

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
        raise HTTPException(status_code=400, detail="Invalid time format. Use ISO 8601.") from None

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
