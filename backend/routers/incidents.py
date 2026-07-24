from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models

from database import get_db
from middleware.auth_middleware import get_operator_user

router = APIRouter(
    prefix="/incidents",
    tags=["Incidents"]
)

@router.get("/")
def get_all_incidents(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_operator_user)
):
    incidents = db.query(models.Incident).all()

    return incidents


@router.get("/critical")
def get_critical_incidents(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_operator_user)
):
    critical_incidents = (
        db.query(models.Incident)
        .filter(models.Incident.severity == "CRITICAL")
        .all()
    )

    return critical_incidents

@router.get("/stats")
def get_incident_stats(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_operator_user)
):
    incidents = db.query(models.Incident).all()

    total = len(incidents)

    critical = len([i for i in incidents if i.severity == "CRITICAL"])
    high = len([i for i in incidents if i.severity == "HIGH"])
    medium = len([i for i in incidents if i.severity == "MEDIUM"])
    low = len([i for i in incidents if i.severity == "LOW"])

    return {
        "total_incidents": total,
        "critical": critical,
        "high": high,
        "medium": medium,
        "low": low
    }

@router.get("/{incident_id}")
def get_incident_by_id(
    incident_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_operator_user)
):
    incident = (
        db.query(models.Incident)
        .filter(models.Incident.id == incident_id)
        .first()
    )

    if incident is None:
        raise HTTPException(
            status_code=404,
            detail="Incident not found"
        )

    return incident