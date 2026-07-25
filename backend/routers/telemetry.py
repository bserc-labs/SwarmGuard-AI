from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.orm import Session

import models
import schemas

from database import get_db
from middleware.auth_middleware import get_operator_user
from services.ai_service import ai_service
from services.threat_service import threat_service
from services.ws_manager import ws_manager

router = APIRouter(
    prefix="/telemetry",
    tags=["Telemetry"]
)


@router.post("/")
def receive_telemetry(
    telemetry: schemas.TelemetryPacket,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_operator_user)
):
    # -----------------------------
    # Save telemetry
    # -----------------------------
    telemetry_log = models.TelemetryLog(
        drone_id=telemetry.drone_id,
        latitude=telemetry.latitude,
        longitude=telemetry.longitude,
        altitude=telemetry.altitude,
        speed=telemetry.speed,
        battery=telemetry.battery,
        packet_sequence=telemetry.packet_sequence
    )

    db.add(telemetry_log)
    db.commit()
    db.refresh(telemetry_log)

    # -----------------------------
    # AI Analysis
    # -----------------------------
    is_anomaly, anomaly_score, attack_type = ai_service.analyze_telemetry(
        telemetry.model_dump()
    )

    # -----------------------------
    # Threat Analysis
    # -----------------------------
    alert = threat_service.generate_alert(
        is_anomaly,
        anomaly_score,
        attack_type
    )

    # -----------------------------
    # Save incident if anomaly
    # -----------------------------
    if alert["is_anomaly"]:

        incident = models.Incident(
            drone_id=telemetry.drone_id,
            attack_type=alert["attack_type"],
            anomaly_score=alert["anomaly_score"],
            threat_level=alert["threat_level"],
            severity=alert["severity"],
            shap_values=alert["shap_top3"],
            explanation=alert["explanation"]
        )

        db.add(incident)
        db.commit()
        db.refresh(incident)

        # -----------------------------
        # Broadcast to Dashboard
        # -----------------------------
        background_tasks.add_task(
            ws_manager.broadcast,
            {
                "type": "incident",
                "drone_id": telemetry.drone_id,
                "attack_type": alert["attack_type"],
                "severity": alert["severity"],
                "threat_level": alert["threat_level"],
                "anomaly_score": alert["anomaly_score"],
                "explanation": alert["explanation"],
                "shap_values": alert["shap_top3"],
                "timestamp": str(incident.created_at)
            }
        )

    return {
        "message": "Telemetry processed successfully",
        "telemetry_id": telemetry_log.id,
        "analysis": alert
    }


@router.get("/")
def get_all_telemetry(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_operator_user)
):
    return db.query(models.TelemetryLog).all()