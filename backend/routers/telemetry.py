from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

import models
import schemas

from database import get_db
from middleware.auth_middleware import get_operator_user
from services.ai_service import ai_service
from services.threat_service import threat_service

router = APIRouter(
    prefix="/telemetry",
    tags=["Telemetry"]
)

@router.post("/")
def receive_telemetry(
    telemetry: schemas.TelemetryPacket,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_operator_user)
):
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

    # Analyze telemetry using AI
    is_anomaly, anomaly_score, attack_type = ai_service.analyze_telemetry(
        telemetry.model_dump()
    )

    # Generate alert
    alert = threat_service.generate_alert(
        is_anomaly,
        anomaly_score,
        attack_type
    )

    # Save incident if anomaly detected
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