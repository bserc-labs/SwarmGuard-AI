from fastapi import APIRouter, Depends, BackgroundTasks, Header, HTTPException, status
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

router = APIRouter(prefix="/telemetry", tags=["telemetry"])

# In-memory buffer for live telemetry
telemetry_buffer = deque(maxlen=500)
EXPECTED_DRONE_API_KEY = os.getenv("DRONE_API_KEY", "SWARMGUARD_DRONE_DEFENSE_SECRET_2026")

@router.post("/ingest", response_model=schemas.DetectionResult)
def ingest_telemetry(
    packet: schemas.TelemetryPacket, 
    background_tasks: BackgroundTasks, 
    x_drone_api_key: str = Header(None),
    db: Session = Depends(get_db)
):
    # Drone Device Security Check (Anti-Spoofing)
    if x_drone_api_key and x_drone_api_key != EXPECTED_DRONE_API_KEY:
        logger.warning(f"🚨 UNAUTHORIZED DRONE SPOOFING ATTEMPT: {packet.drone_id} sent invalid API Key!")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Device Authentication Failed: Invalid API Key for drone '{packet.drone_id}'"
        )
        
    # 1. Append to buffer
    telemetry_buffer.append(packet.model_dump())
    
    # 2. Save raw telemetry & update Drone last_seen in DB
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
    
    # 3. AI Inference
    try:
        is_anomaly, anomaly_score, attack_type = ai_service.analyze_telemetry(packet.model_dump())
    except Exception as e:
        logger.error(f"AI inference failed: {e}")
        is_anomaly, anomaly_score, attack_type = False, 0.0, None
    
    # 4. Generate Alert & Incident if anomaly
    alert_data = threat_service.generate_alert(is_anomaly, anomaly_score, attack_type)
    
    if is_anomaly:
        try:
            incident = models.Incident(
                drone_id=packet.drone_id,
                attack_type=alert_data.get("attack_type"),
                anomaly_score=anomaly_score,
                threat_level=alert_data.get("threat_level"),
                severity=alert_data.get("severity"),
                shap_values=alert_data.get("shap_top3"),
                explanation=alert_data.get("explanation")
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
def get_live_telemetry(current_user: models.User = Depends(get_operator_user)):
    return list(telemetry_buffer)
