from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
import schemas
import models
from database import get_db

router = APIRouter(prefix="/incidents", tags=["incidents"])

from middleware.auth_middleware import get_operator_user

@router.get("/", response_model=List[schemas.IncidentOut])
def get_incidents(
    severity: Optional[str] = None,
    limit: int = Query(50, le=1000),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_operator_user)
):
    query = db.query(models.Incident)
    if severity:
        query = query.filter(models.Incident.severity == severity)
    
    return query.order_by(models.Incident.created_at.desc()).limit(limit).all()

@router.get("/{id}", response_model=schemas.IncidentOut)
def get_incident(
    id: int, 
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_operator_user)
):
    incident = db.query(models.Incident).filter(models.Incident.id == id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident
