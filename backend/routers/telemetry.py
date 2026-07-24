from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from collections import deque
import asyncio
import schemas
import models
from database import get_db
from services.ai_service import ai_service
from services.threat_service import threat_service
from services.ws_manager import ws_manager

router = APIRouter(prefix="/telemetry", tags=["telemetry"])

# In-memory buffer for live telemetry
telemetry_buffer = deque(maxlen=500)

@router.post("/ingest", response_model=schemas.DetectionResult)
def ingest_telemetry(packet: schemas.TelemetryPacket, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    # 1. Append to buffer
    telemetry_buffer.append(packet.model_dump())
    
    # 2. Save raw telemetry to DB
    db_log = models.TelemetryLog(**packet.model_dump())
    db.add(db_log)
    db.commit()
    
    # 3. AI Inference
    is_anomaly, anomaly_score, attack_type = ai_service.analyze_telemetry(packet.model_dump())
    
    # 4. Generate Alert & Incident if anomaly
    alert_data = threat_service.generate_alert(is_anomaly, anomaly_score, attack_type)
    
    if is_anomaly:
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
        
        # Broadcast the alert to all connected websocket clients in the background
        background_tasks.add_task(ws_manager.broadcast, alert_data)
    
    return alert_data

from middleware.auth_middleware import get_operator_user

@router.get("/live")
def get_live_telemetry(current_user: models.User = Depends(get_operator_user)):
    return list(telemetry_buffer)
