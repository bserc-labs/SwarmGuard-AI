import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import extract, func, select
from sqlalchemy.orm import Session

import models
import schemas
from config import get_settings
from database import get_db
from middleware.auth_middleware import TenantContext, require_permission
from middleware.rbac import Permissions
from services.audit_service import audit_service

settings = get_settings()

router = APIRouter(prefix="/incidents", tags=["incidents"])

# The incident lifecycle, in order.
#
# The rule this enforces is that an incident's recorded history is a *contiguous
# walk* through this list -- no state is ever skipped in the audit trail. That is
# not the same as requiring an operator to click through every state, and
# conflating the two is what broke the console: the UI exposes acknowledge,
# resolve and close, there was never a route to reach INVESTIGATING or
# CONTAINED, and so `resolve` on an ACKNOWLEDGED incident returned 400 every
# single time. The Resolve button could not succeed from any reachable state.
#
# So a transition request names a *destination*, and `_advance_to` walks every
# intermediate state, writing an audit row for each hop. The record stays
# complete; the operator gets one button.
LIFECYCLE = [
    "NEW",
    "OPEN",
    "ACKNOWLEDGED",
    "INVESTIGATING",
    "CONTAINED",
    "RESOLVED",
    "CLOSED",
]

_ORDER = {status: index for index, status in enumerate(LIFECYCLE)}

# Direct successors. Retained because it states the adjacency rule declaratively,
# and because the walk below is only correct if each step is a legal single hop.
TRANSITIONS = {
    status: [LIFECYCLE[index + 1]] for index, status in enumerate(LIFECYCLE[:-1])
}


def _validate_transition(current_status: str, new_status: str):
    allowed = TRANSITIONS.get(current_status, [])
    if new_status not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid transition from {current_status} to {new_status}. Allowed: {allowed}"
        )


def _load_incident(db: Session, incident_id: int, tenant: TenantContext) -> models.Incident:
    """Fetch one incident within the caller's organization, or 404.

    Tenant-scoped in the query rather than checked afterwards, so a caller
    cannot distinguish "does not exist" from "belongs to another organization".
    """
    incident = db.query(models.Incident).filter(
        models.Incident.id == incident_id,
        models.Incident.organization_id == tenant.organization_id
    ).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident

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
    # Aggregated in SQL. This used to load every incident of the organization
    # -- shap_values JSON, explanation text and all -- and count in a Python
    # loop. Incidents are never deleted, so that request grew without bound.
    #
    # The response is unchanged, key for key. Portable constructs only
    # (func.count + group_by, extract): the SQLite unit suites also reach this
    # route. extract("epoch") renders EXTRACT(epoch FROM ..) on PostgreSQL and
    # CAST(STRFTIME('%s', ..) AS INTEGER) on SQLite.
    scoped = models.Incident.organization_id == tenant.organization_id

    # avg() ignores NULLs and NULL - x is NULL, so an incident missing either
    # timestamp is left out: the same rows the old
    # `if inc.resolution_time and inc.detection_time` skipped.
    resolution_seconds = extract("epoch", models.Incident.resolution_time) - extract(
        "epoch", models.Incident.detection_time
    )
    total, avg_resolution = db.execute(
        select(func.count(models.Incident.id), func.avg(resolution_seconds)).where(scoped)
    ).one()

    if total == 0:
        return {"total": 0}

    def distribution(column) -> dict:
        rows = db.execute(
            select(column, func.count(models.Incident.id)).where(scoped).group_by(column)
        ).all()
        return {value: count for value, count in rows}

    # The four tiers are always present, even at zero; anything else the column
    # holds is appended after them, as before.
    severity_dist = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    severity_dist.update(distribution(models.Incident.severity))

    return {
        "total": total,
        "by_severity": severity_dist,
        "by_status": distribution(models.Incident.status),
        "by_threat_type": distribution(models.Incident.attack_type),
        "by_drone": distribution(models.Incident.drone_id),
        # PostgreSQL returns numeric (Decimal) for EXTRACT/avg; float() so the
        # JSON number is what it always was. Integer 0 when nothing has been
        # resolved: the frontend tests this value for falsiness.
        "avg_resolution_time_seconds": (
            round(float(avg_resolution), 2) if avg_resolution is not None else 0
        ),
    }

@router.get("/{id}", response_model=schemas.IncidentOut)
def get_incident(
    id: int, 
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(require_permission(Permissions.INCIDENT_READ))
):
    return _load_incident(db, id, tenant)


def _apply_transition(
    db: Session,
    incident: models.Incident,
    new_status: str,
    tenant: TenantContext,
    ip: str | None,
    reason: str | None = None,
    correlation_id: str | None = None,
):
    """Move one legal step and record it. Does not commit.

    Committing is the caller's job because a single operator action can span
    several steps, and a partially-walked lifecycle must never reach the table.
    """
    _validate_transition(incident.status, new_status)
    old_status = incident.status
    incident.status = new_status

    if new_status == "RESOLVED":
        incident.resolution_time = datetime.now(UTC)

    audit_service.log_from_context(
        db=db,
        tenant=tenant,
        action="STATUS_TRANSITION",
        resource="incident",
        resource_id=str(incident.id),
        previous_state=old_status,
        new_state=new_status,
        reason=reason,
        ip_address=ip,
        correlation_id=correlation_id,
    )
    return incident


def _advance_to(
    db: Session,
    incident: models.Incident,
    target: str,
    tenant: TenantContext,
    ip: str | None,
    reason: str | None = None,
):
    """Walk the lifecycle forward to `target`, auditing every state entered.

    The operator's note is attached to the hop they actually asked for. The
    intermediate hops are labelled as automatic, so reading the audit trail
    still tells you which state the human chose and which the system passed
    through on the way -- information a single skipping transition would lose.

    Backwards moves are refused rather than silently ignored: reopening a
    resolved incident is a different action with different authorisation, not a
    transition.
    """
    if target not in _ORDER:
        raise HTTPException(status_code=400, detail=f"Unknown incident status '{target}'.")

    current = incident.status
    if current not in _ORDER:
        raise HTTPException(
            status_code=409,
            detail=f"Incident #{incident.id} is in unrecognised state '{current}'.",
        )

    start, end = _ORDER[current], _ORDER[target]

    if start == end:
        raise HTTPException(
            status_code=400, detail=f"Incident #{incident.id} is already {target}."
        )
    if start > end:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Incident #{incident.id} is {current}, which is past {target}. "
                "The lifecycle does not move backwards."
            ),
        )

    # One operator action, one correlation id. Without it each hop gets its own
    # uuid and the audit trail shows five unrelated transitions rather than one
    # decision that passed through five states.
    correlation_id = str(uuid.uuid4())

    for index in range(start + 1, end + 1):
        step = LIFECYCLE[index]
        _apply_transition(
            db,
            incident,
            step,
            tenant,
            ip,
            reason if index == end else f"Auto-advanced en route to {target}",
            correlation_id=correlation_id,
        )

    db.commit()
    db.refresh(incident)
    return incident


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("/{id}/acknowledge", response_model=schemas.IncidentOut)
def acknowledge_incident(id: int, request: Request, transition: schemas.IncidentTransition | None = None, db: Session = Depends(get_db), tenant: TenantContext = Depends(require_permission(Permissions.INCIDENT_ACKNOWLEDGE))):
    """Take ownership of an incident. From NEW this passes through OPEN."""
    incident = _load_incident(db, id, tenant)
    return _advance_to(
        db, incident, "ACKNOWLEDGED", tenant, _client_ip(request),
        transition.reason if transition else None,
    )


# INVESTIGATING and CONTAINED had no route at all, which is why `resolve` was
# unreachable: the lifecycle requires passing through them and nothing could.
# They are gated on INCIDENT_ACKNOWLEDGE rather than a new permission, because
# they are the same tier of work as acknowledging -- an analyst triaging an
# incident -- and adding a permission would have to be mirrored in
# frontend/src/lib/rbac.ts to stay in sync.
@router.post("/{id}/investigate", response_model=schemas.IncidentOut)
def investigate_incident(id: int, request: Request, transition: schemas.IncidentTransition | None = None, db: Session = Depends(get_db), tenant: TenantContext = Depends(require_permission(Permissions.INCIDENT_ACKNOWLEDGE))):
    """Mark an incident as under active investigation."""
    incident = _load_incident(db, id, tenant)
    return _advance_to(
        db, incident, "INVESTIGATING", tenant, _client_ip(request),
        transition.reason if transition else None,
    )


@router.post("/{id}/contain", response_model=schemas.IncidentOut)
def contain_incident(id: int, request: Request, transition: schemas.IncidentTransition | None = None, db: Session = Depends(get_db), tenant: TenantContext = Depends(require_permission(Permissions.INCIDENT_ACKNOWLEDGE))):
    """Record that the threat has been contained but not yet resolved."""
    incident = _load_incident(db, id, tenant)
    return _advance_to(
        db, incident, "CONTAINED", tenant, _client_ip(request),
        transition.reason if transition else None,
    )


@router.post("/{id}/assign", response_model=schemas.IncidentOut)
def assign_incident(id: int, request: Request, payload: schemas.IncidentAssign, db: Session = Depends(get_db), tenant: TenantContext = Depends(require_permission(Permissions.INCIDENT_ASSIGN))):
    incident = _load_incident(db, id, tenant)

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
def resolve_incident(id: int, request: Request, transition: schemas.IncidentTransition | None = None, db: Session = Depends(get_db), tenant: TenantContext = Depends(require_permission(Permissions.INCIDENT_RESOLVE))):
    """Resolve an incident, recording every lifecycle state it passes through."""
    incident = _load_incident(db, id, tenant)
    return _advance_to(
        db, incident, "RESOLVED", tenant, _client_ip(request),
        transition.reason if transition else None,
    )


@router.post("/{id}/close", response_model=schemas.IncidentOut)
def close_incident(id: int, request: Request, transition: schemas.IncidentTransition | None = None, db: Session = Depends(get_db), tenant: TenantContext = Depends(require_permission(Permissions.INCIDENT_CLOSE))):
    """Close an incident. From anything earlier this resolves it on the way."""
    incident = _load_incident(db, id, tenant)
    return _advance_to(
        db, incident, "CLOSED", tenant, _client_ip(request),
        transition.reason if transition else None,
    )


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
