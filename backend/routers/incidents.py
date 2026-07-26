from fastapi import APIRouter, Depends, Query, HTTPException, Request
from sqlalchemy.orm import Session
from typing import List, Optional
import schemas
import models
from database import get_db
from middleware.auth_middleware import get_operator_user, get_admin_user

router = APIRouter(prefix="/incidents", tags=["incidents"])


def log_audit(db: Session, username: str, action: str, target: str = None, details: str = None, ip: str = None):
    """Record an audit trail entry for defense-grade traceability."""
    audit = models.AuditLog(
        username=username,
        action=action,
        target=target,
        details=details,
        ip_address=ip
    )
    db.add(audit)
    db.commit()


@router.get("/", response_model=List[schemas.IncidentOut])
def get_incidents(
    severity: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(50, le=1000),
    skip: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_operator_user)
):
    query = db.query(models.Incident)
    if severity:
        query = query.filter(models.Incident.severity == severity)
    if status:
        query = query.filter(models.Incident.status == status)
    
    return query.order_by(models.Incident.created_at.desc()).offset(skip).limit(limit).all()


@router.get("/stats")
def get_incident_stats(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_operator_user)
):
    """Get incident statistics for dashboard analytics."""
    total = db.query(models.Incident).count()
    critical = db.query(models.Incident).filter(models.Incident.severity == "CRITICAL").count()
    high = db.query(models.Incident).filter(models.Incident.severity == "HIGH").count()
    open_count = db.query(models.Incident).filter(models.Incident.status == "OPEN").count()
    resolved = db.query(models.Incident).filter(models.Incident.status == "RESOLVED").count()
    
    return {
        "total": total,
        "critical": critical,
        "high": high,
        "open": open_count,
        "resolved": resolved
    }


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


@router.patch("/{id}", response_model=schemas.IncidentOut)
def update_incident_status(
    id: int,
    update: schemas.IncidentUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_operator_user)
):
    """Update incident status (ACKNOWLEDGED, FALSE_POSITIVE, ESCALATED, RESOLVED)."""
    incident = db.query(models.Incident).filter(models.Incident.id == id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    
    old_status = incident.status
    incident.status = update.status
    db.commit()
    db.refresh(incident)
    
    # Audit trail
    log_audit(
        db=db,
        username=current_user.username,
        action="INCIDENT_STATUS_CHANGE",
        target=f"incident:{id}",
        details=f"{old_status} → {update.status}",
        ip=request.client.host if request.client else None
    )
    
    return incident


@router.get("/audit/logs", response_model=List[schemas.AuditLogOut])
def get_audit_logs(
    limit: int = Query(100, le=500),
    skip: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_admin_user)
):
    """Get audit trail logs (admin only)."""
    return db.query(models.AuditLog).order_by(
        models.AuditLog.created_at.desc()
    ).offset(skip).limit(limit).all()
