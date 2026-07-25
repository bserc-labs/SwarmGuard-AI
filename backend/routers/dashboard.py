from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

import models

from database import get_db
from middleware.auth_middleware import get_operator_user

router = APIRouter(
    prefix="/dashboard",
    tags=["Dashboard"]
)

@router.get("/overview")
def dashboard_overview(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_operator_user)
):
    total_telemetry = db.query(models.TelemetryLog).count()
    total_incidents = db.query(models.Incident).count()

    critical_incidents = (
        db.query(models.Incident)
        .filter(models.Incident.severity == "CRITICAL")
        .count()
    )

    return {
        "total_telemetry": total_telemetry,
        "total_incidents": total_incidents,
        "critical_incidents": critical_incidents
    }

@router.get("/recent-incidents")
def recent_incidents(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_operator_user)
):
    incidents = (
        db.query(models.Incident)
        .order_by(models.Incident.created_at.desc())
        .limit(5)
        .all()
    )

    return incidents

@router.get("/threat-distribution")
def threat_distribution(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_operator_user)
):
    return {
        "LOW": db.query(models.Incident).filter(
            models.Incident.severity == "LOW"
        ).count(),

        "MEDIUM": db.query(models.Incident).filter(
            models.Incident.severity == "MEDIUM"
        ).count(),

        "HIGH": db.query(models.Incident).filter(
            models.Incident.severity == "HIGH"
        ).count(),

        "CRITICAL": db.query(models.Incident).filter(
            models.Incident.severity == "CRITICAL"
        ).count(),
    }

@router.get("/system-health")
def system_health(
    current_user: models.User = Depends(get_operator_user)
):
    return {
        "api": "UP",
        "database": "UP",
        "ai_service": "UP",
        "threat_engine": "UP"
    }