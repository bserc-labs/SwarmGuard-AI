from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import get_db
import models
import schemas
from middleware.auth_middleware import get_admin_user, get_operator_user

router = APIRouter(prefix="/settings", tags=["settings"])

def get_or_create_settings(db: Session):
    settings = db.query(models.SystemSettings).first()
    if not settings:
        settings = models.SystemSettings()
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings

@router.get("/", response_model=schemas.SystemSettingsOut)
def read_settings(db: Session = Depends(get_db), current_user: models.User = Depends(get_operator_user)):
    return get_or_create_settings(db)

@router.patch("/", response_model=schemas.SystemSettingsOut)
def update_settings(
    settings_update: schemas.SystemSettingsUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_admin_user)
):
    settings = get_or_create_settings(db)
    
    update_data = settings_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(settings, key, value)
        
    db.commit()
    db.refresh(settings)
    return settings
