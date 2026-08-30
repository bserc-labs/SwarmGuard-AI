from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

import models
from database import get_db
from middleware.auth_middleware import TenantContext, require_permission
from middleware.rbac import Permissions
from services.audit_service import audit_service
from utils.logger import logger

router = APIRouter(prefix="/geofence", tags=["geofence"])

class GeofenceCreate(BaseModel):
    name: str
    zone_type: str  # POLYGON, CIRCLE
    coordinates: Any
    severity: str = "CRITICAL"
    is_active: bool = True

class GeofenceResponse(BaseModel):
    id: int
    name: str
    zone_type: str
    coordinates: Any
    severity: str
    is_active: bool
    organization_id: int | None = None

    class Config:
        from_attributes = True

@router.get("/zones", response_model=list[GeofenceResponse])
def get_zones(
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(require_permission(Permissions.GEOFENCE_READ))
):
    """Fetch all active geofence zones for the current tenant."""
    return db.query(models.GeofenceZone).filter(
        models.GeofenceZone.organization_id == tenant.organization_id,
        models.GeofenceZone.is_active
    ).all()

@router.post("/zones", response_model=GeofenceResponse)
def create_zone(
    zone: GeofenceCreate,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(require_permission(Permissions.GEOFENCE_MANAGE))
):
    """Create a new restricted geofence zone."""
    try:
        new_zone = models.GeofenceZone(
            **zone.model_dump(),
            organization_id=tenant.organization_id
        )
        db.add(new_zone)

        audit_service.log_from_context(
            db=db, tenant=tenant,
            action="CREATE_GEOFENCE",
            resource="geofence_zone", resource_id=zone.name,
            new_state="ACTIVE",
            details=f"Type: {zone.zone_type}"
        )
        db.commit()
        db.refresh(new_zone)

        return new_zone
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating geofence zone: {e}")
        raise HTTPException(
            status_code=400, detail="Failed to create geofence zone. Name may already exist."
        ) from e

@router.delete("/zones/{zone_id}")
def delete_zone(
    zone_id: int,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(require_permission(Permissions.GEOFENCE_MANAGE))
):
    """Deactivate or remove a geofence zone (tenant-scoped)."""
    zone = db.query(models.GeofenceZone).filter(
        models.GeofenceZone.id == zone_id,
        models.GeofenceZone.organization_id == tenant.organization_id
    ).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")

    zone.is_active = False

    audit_service.log_from_context(
        db=db, tenant=tenant,
        action="DEACTIVATE_GEOFENCE",
        resource="geofence_zone", resource_id=str(zone_id),
        target=zone.name,
        previous_state="ACTIVE", new_state="INACTIVE",
    )
    db.commit()

    return {"status": "success", "message": f"Zone {zone.name} deactivated."}
