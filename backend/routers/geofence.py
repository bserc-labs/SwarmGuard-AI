from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
import models
from middleware.auth_middleware import get_operator_user
from pydantic import BaseModel
from typing import List, Optional, Any
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

    class Config:
        from_attributes = True

@router.get("/zones", response_model=List[GeofenceResponse])
def get_zones(db: Session = Depends(get_db), current_user: models.User = Depends(get_operator_user)):
    """Fetch all active geofence zones."""
    return db.query(models.GeofenceZone).filter(models.GeofenceZone.is_active == True).all()

@router.post("/zones", response_model=GeofenceResponse)
def create_zone(zone: GeofenceCreate, db: Session = Depends(get_db), current_user: models.User = Depends(get_operator_user)):
    """Create a new restricted geofence zone."""
    try:
        new_zone = models.GeofenceZone(**zone.model_dump())
        db.add(new_zone)
        db.commit()
        db.refresh(new_zone)
        
        # Audit log
        audit = models.AuditLog(
            username=current_user.username,
            action="CREATE_GEOFENCE",
            target=zone.name,
            details=f"Type: {zone.zone_type}"
        )
        db.add(audit)
        db.commit()
        
        return new_zone
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating geofence zone: {e}")
        raise HTTPException(status_code=400, detail="Failed to create geofence zone. Name may already exist.")

@router.delete("/zones/{zone_id}")
def delete_zone(zone_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_operator_user)):
    """Deactivate or remove a geofence zone."""
    zone = db.query(models.GeofenceZone).filter(models.GeofenceZone.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")
    
    zone.is_active = False
    
    # Audit log
    audit = models.AuditLog(
        username=current_user.username,
        action="DEACTIVATE_GEOFENCE",
        target=zone.name,
        details=""
    )
    db.add(audit)
    db.commit()
    
    return {"status": "success", "message": f"Zone {zone.name} deactivated."}
