from fastapi import APIRouter, Depends, BackgroundTasks, Header, HTTPException, status, Request, Query

from sqlalchemy.orm import Session
from collections import deque
import asyncio
from datetime import datetime
import os
import schemas
import models
from database import get_db
from services.ai_service import ai_service
from services.threat_service import threat_service
from services.ws_manager import ws_manager
from utils.logger import logger
from utils.limiter import limiter

router = APIRouter(prefix="/telemetry", tags=["telemetry"])

EXPECTED_DRONE_API_KEY = os.getenv("DRONE_API_KEY", "SWARMGUARD_DRONE_DEFENSE_SECRET_2026")

@router.post("/ingest", response_model=schemas.DetectionResult)
@limiter.limit("50/second")
def ingest_telemetry(
    request: Request,
    packet: schemas.TelemetryPacket, 
    background_tasks: BackgroundTasks, 
    x_drone_api_key: str = Header(None),
    db: Session = Depends(get_db)
):
    # Drone Device Security Check (Anti-Spoofing)
    if not x_drone_api_key or x_drone_api_key != EXPECTED_DRONE_API_KEY:
        logger.warning(f"🚨 UNAUTHORIZED DRONE SPOOFING ATTEMPT: {packet.drone_id} sent invalid or missing API Key!")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Device Authentication Failed: Invalid or missing API Key for drone '{packet.drone_id}'"
        )
    
    # 1. Save raw telemetry & update Drone last_seen in DB
    try:
        db_log = models.TelemetryLog(**packet.model_dump())
        db.add(db_log)
        
        # Update or register Drone
        drone = db.query(models.Drone).filter(models.Drone.drone_id == packet.drone_id).first()
        if not drone:
            drone = models.Drone(drone_id=packet.drone_id, status="ACTIVE", last_seen=datetime.utcnow())
            db.add(drone)
        else:
            drone.last_seen = datetime.utcnow()
            # If drone was marked SILENT, set back to ACTIVE upon receiving new telemetry
            if drone.status == "SILENT_POSSIBLE_JAMMING":
                drone.status = "ACTIVE"
        
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"DB write failed for telemetry: {e}")
    
    # 2. AI Inference & Multi-Sensor Fusion
    try:
        is_anomaly, anomaly_score, attack_type = ai_service.analyze_telemetry(packet.model_dump())
    except Exception as e:
        logger.error(f"AI inference failed: {e}")
        is_anomaly, anomaly_score, attack_type = False, 0.0, None
    
    # 3. Multi-Sensor Fusion (Radar + RF + Optical AI + Acoustic + Kalman Trajectory)
    from services.sensor_fusion import sensor_fusion_engine
    fusion_data = sensor_fusion_engine.fuse_sensors(packet.model_dump())

    # 4. Geofence Perimeter Check
    from services.geofence_service import GeofenceEngine
    violated_zones = GeofenceEngine.check_geofence_violations(db, packet.latitude, packet.longitude)
    
    # 5. Generate Alert & Incident if anomaly
    alert_data = threat_service.generate_alert(is_anomaly, anomaly_score, attack_type)
    alert_data["sensor_fusion"] = fusion_data
    if violated_zones:
        alert_data["geofence_violations"] = [z.name for z in violated_zones]
    
    # 6. Autonomous Kill-Chain Mitigation
    from services.killchain_service import killchain_engine
    is_silent = (drone.status == "SILENT_POSSIBLE_JAMMING")
    killchain_result = killchain_engine.evaluate_and_intercept(
        db=db,
        drone_id=packet.drone_id,
        threat_level=alert_data.get("threat_level", 0),
        violated_zones=violated_zones,
        background_tasks=background_tasks,
        is_silent=is_silent
    )
    if killchain_result.get("intercepted"):
        alert_data["killchain_action"] = killchain_result["action"]
    
    if is_anomaly and not fusion_data.get("is_false_positive_bird"):
        try:
            incident = models.Incident(
                drone_id=packet.drone_id,
                attack_type=alert_data.get("attack_type"),
                anomaly_score=anomaly_score,
                threat_level=alert_data.get("threat_level"),
                severity=alert_data.get("severity"),
                shap_values=alert_data.get("shap_top3"),
                explanation=alert_data.get("explanation"),
                status="AUTONOMOUSLY_MITIGATED" if killchain_result.get("intercepted") else "OPEN"
            )
            db.add(incident)
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"DB write failed for incident: {e}")
        
        # Broadcast the alert to all connected websocket clients in the background
        background_tasks.add_task(ws_manager.broadcast, alert_data)
    
    return alert_data

from middleware.auth_middleware import get_operator_user

@router.get("/live")
def get_live_telemetry(db: Session = Depends(get_db), current_user: models.User = Depends(get_operator_user)):
    """Fetch the latest telemetry directly from the database (solves multi-worker state isolation)."""
    logs = db.query(models.TelemetryLog).order_by(models.TelemetryLog.id.desc()).limit(500).all()
    # Reverse so it's oldest to newest (like the deque was)
    logs.reverse()
    return logs

@router.get("/sensor-fusion/live")
def get_live_sensor_fusion(db: Session = Depends(get_db), current_user: models.User = Depends(get_operator_user)):
    """Return real-time multi-sensor fusion matrix for all active drones."""
    from services.sensor_fusion import sensor_fusion_engine
    
    # Get last 20 packets from DB
    logs = db.query(models.TelemetryLog).order_by(models.TelemetryLog.id.desc()).limit(20).all()
    logs.reverse()
    
    fusion_matrix = []
    for pkt in logs:
        # Convert SQLAlchemy object to dict for the engine
        pkt_dict = {
            "drone_id": pkt.drone_id,
            "altitude": pkt.altitude,
            "speed": pkt.speed,
            "latitude": pkt.latitude,
            "longitude": pkt.longitude,
            "battery": pkt.battery
        }
        fusion_matrix.append({
            "drone_id": pkt.drone_id,
            "altitude": pkt.altitude,
            "speed": pkt.speed,
            "fusion": sensor_fusion_engine.fuse_sensors(pkt_dict)
        })
    return fusion_matrix


@router.get("/swarm-formation")
def get_swarm_formation(db: Session = Depends(get_db), current_user: models.User = Depends(get_operator_user)):
    """Return live spatial swarm formation classification (V-Shape, Grid Encircle, Leader-Follower)."""
    from services.swarm_service import swarm_service

    # Fetch latest telemetry log for each active drone
    latest_logs = db.query(models.TelemetryLog).order_by(models.TelemetryLog.id.desc()).limit(100).all()

    # Deduplicate to get the latest packet per drone
    drone_map = {}
    for pkt in latest_logs:
        if pkt.drone_id not in drone_map:
            drone_map[pkt.drone_id] = {
                "drone_id": pkt.drone_id,
                "latitude": pkt.latitude,
                "longitude": pkt.longitude,
                "altitude": pkt.altitude,
                "speed": pkt.speed,
                "battery": pkt.battery
            }

    telemetry_list = list(drone_map.values())
    return swarm_service.analyze_swarm(telemetry_list)

@router.get("/history")
def get_telemetry_history(
    start_time: str,
    end_time: str,
    limit: int = Query(500, le=2000),
    skip: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_operator_user)
):
    """Fetch historical telemetry bounded by time for DVR playback with pagination."""
    try:
        start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
        
        logs = db.query(models.TelemetryLog).filter(
            models.TelemetryLog.created_at >= start_dt,
            models.TelemetryLog.created_at <= end_dt
        ).order_by(models.TelemetryLog.created_at.asc()).offset(skip).limit(limit).all()
        
        return logs
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid time format. Use ISO 8601.")


