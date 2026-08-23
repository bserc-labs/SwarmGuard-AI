from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime

import models
import schemas
from database import get_db
from middleware.auth_middleware import get_tenant_context, TenantContext, require_permission
from middleware.rbac import Permissions
from services.audit_service import audit_service

router = APIRouter(prefix="/incidents", tags=["incidents"])

# Valid state transitions
TRANSITIONS = {
    "NEW": ["OPEN"],
    "OPEN": ["ACKNOWLEDGED"],
    "ACKNOWLEDGED": ["INVESTIGATING"],
    "INVESTIGATING": ["CONTAINED"],
    "CONTAINED": ["RESOLVED"],
    "RESOLVED": ["CLOSED"]
}

def _validate_transition(current_status: str, new_status: str):
    allowed = TRANSITIONS.get(current_status, [])
    if new_status not in allowed:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid transition from {current_status} to {new_status}. Allowed: {allowed}"
        )

@router.get("/", response_model=list[schemas.IncidentOut])
def get_incidents(
    severity: str | None = None,
    status: str | None = None,
    limit: int = Query(50, le=1000),
    skip: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(require_permission(Permissions.INCIDENT_READ))
):
    query = db.query(models.Incident).filter(
        models.Incident.organization_id == tenant.organization_id
    )
    if severity:
        query = query.filter(models.Incident.severity == severity)
    if status:
        query = query.filter(models.Incident.status == status)
    
    return query.order_by(models.Incident.priority.desc(), models.Incident.detection_time.desc()).offset(skip).limit(limit).all()

@router.get("/open", response_model=list[schemas.IncidentOut])
def get_open_incidents(
    limit: int = Query(50, le=1000),
    skip: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(require_permission(Permissions.INCIDENT_READ))
):
    query = db.query(models.Incident).filter(
        models.Incident.organization_id == tenant.organization_id,
        models.Incident.status.in_(["NEW", "OPEN", "ACKNOWLEDGED", "INVESTIGATING", "CONTAINED"])
    )
    return query.order_by(models.Incident.priority.desc(), models.Incident.detection_time.desc()).offset(skip).limit(limit).all()


@router.get("/stats")
def get_incident_stats(
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(require_permission(Permissions.INCIDENT_READ))
):
    """Get extended incident statistics for dashboard analytics."""
    # Base query scoped to tenant's organization
    incidents = db.query(models.Incident).filter(
        models.Incident.organization_id == tenant.organization_id
    ).all()
    
    total = len(incidents)
    if total == 0:
        return {"total": 0}
        
    severity_dist = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    status_dist = {}
    attack_type_dist = {}
    drone_dist = {}
    
    # Timing metrics
    res_times = []
    
    for inc in incidents:
        severity_dist[inc.severity] = severity_dist.get(inc.severity, 0) + 1
        status_dist[inc.status] = status_dist.get(inc.status, 0) + 1
        attack_type_dist[inc.attack_type] = attack_type_dist.get(inc.attack_type, 0) + 1
        drone_dist[inc.drone_id] = drone_dist.get(inc.drone_id, 0) + 1
        
        if inc.resolution_time and inc.detection_time:
            res_times.append((inc.resolution_time - inc.detection_time).total_seconds())

    avg_resolution = sum(res_times) / len(res_times) if res_times else 0

    return {
        "total": total,
        "by_severity": severity_dist,
        "by_status": status_dist,
        "by_threat_type": attack_type_dist,
        "by_drone": drone_dist,
        "avg_resolution_time_seconds": round(avg_resolution, 2)
    }


@router.get("/{id}", response_model=schemas.IncidentOut)
def get_incident(
    id: int, 
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(require_permission(Permissions.INCIDENT_READ))
):
    incident = db.query(models.Incident).filter(
        models.Incident.id == id,
        models.Incident.organization_id == tenant.organization_id
    ).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident


def _transition_incident(db: Session, incident: models.Incident, new_status: str, tenant: TenantContext, ip: str, reason: str = None):
    _validate_transition(incident.status, new_status)
    old_status = incident.status
    incident.status = new_status
    
    if new_status == "RESOLVED":
        incident.resolution_time = datetime.utcnow()
        
    audit_service.log_from_context(
        db=db,
        tenant=tenant,
        action="STATUS_TRANSITION",
        resource="incident",
        resource_id=str(incident.id),
        previous_state=old_status,
        new_state=new_status,
        reason=reason,
        ip_address=ip
    )
    db.commit()
    db.refresh(incident)
    return incident


@router.post("/{id}/acknowledge", response_model=schemas.IncidentOut)
def acknowledge_incident(id: int, request: Request, transition: schemas.IncidentTransition = None, db: Session = Depends(get_db), tenant: TenantContext = Depends(require_permission(Permissions.INCIDENT_ACKNOWLEDGE))):
    incident = db.query(models.Incident).filter(
        models.Incident.id == id,
        models.Incident.organization_id == tenant.organization_id
    ).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    # Quick jump logic (NEW -> OPEN -> ACKNOWLEDGED) to simplify UI flows if needed, but strict logic requires sequence.
    # To satisfy strict sequence, UI must send the proper requests, but here we enforce it purely.
    if incident.status == "NEW":
        _transition_incident(db, incident, "OPEN", tenant, request.client.host if request.client else None, "Auto-opened for ack")
    return _transition_incident(db, incident, "ACKNOWLEDGED", tenant, request.client.host if request.client else None, transition.reason if transition else None)


@router.post("/{id}/assign", response_model=schemas.IncidentOut)
def assign_incident(id: int, request: Request, payload: schemas.IncidentAssign, db: Session = Depends(get_db), tenant: TenantContext = Depends(require_permission(Permissions.INCIDENT_ASSIGN))):
    incident = db.query(models.Incident).filter(
        models.Incident.id == id,
        models.Incident.organization_id == tenant.organization_id
    ).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
        
    old_analyst = incident.assigned_analyst
    incident.assigned_analyst = payload.username
    
    audit_service.log_from_context(
        db=db,
        tenant=tenant,
        action="INCIDENT_ASSIGNMENT",
        resource="incident",
        resource_id=str(id),
        previous_state=old_analyst,
        new_state=payload.username,
        details=f"Assigned to {payload.username}",
        ip_address=request.client.host if request.client else None
    )
    db.commit()
    db.refresh(incident)
    return incident


@router.post("/{id}/resolve", response_model=schemas.IncidentOut)
def resolve_incident(id: int, request: Request, transition: schemas.IncidentTransition = None, db: Session = Depends(get_db), tenant: TenantContext = Depends(require_permission(Permissions.INCIDENT_RESOLVE))):
    incident = db.query(models.Incident).filter(
        models.Incident.id == id,
        models.Incident.organization_id == tenant.organization_id
    ).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return _transition_incident(db, incident, "RESOLVED", tenant, request.client.host if request.client else None, transition.reason if transition else None)

@router.post("/{id}/close", response_model=schemas.IncidentOut)
def close_incident(id: int, request: Request, transition: schemas.IncidentTransition = None, db: Session = Depends(get_db), tenant: TenantContext = Depends(require_permission(Permissions.INCIDENT_CLOSE))):
    incident = db.query(models.Incident).filter(
        models.Incident.id == id,
        models.Incident.organization_id == tenant.organization_id
    ).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return _transition_incident(db, incident, "CLOSED", tenant, request.client.host if request.client else None, transition.reason if transition else None)


@router.get("/audit/logs", response_model=list[schemas.AuditLogOut])
def get_audit_logs(
    limit: int = Query(100, le=500),
    skip: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(require_permission(Permissions.AUDIT_READ))
):
    """Get immutable audit trail logs (scoped to tenant's organization)."""
    return db.query(models.AuditLog).filter(
        models.AuditLog.organization_id == tenant.organization_id
    ).order_by(
        models.AuditLog.created_at.desc()
    ).offset(skip).limit(limit).all()
