from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

import models
import schemas
from database import get_db
from middleware.auth_middleware import get_tenant_context, TenantContext, require_permission
from middleware.rbac import Permissions

router = APIRouter(prefix="/settings", tags=["settings"])

def get_or_create_settings(db: Session, organization_id: int):
    settings = db.query(models.SystemSettings).filter(
        models.SystemSettings.organization_id == organization_id
    ).first()
    if not settings:
        settings = models.SystemSettings(organization_id=organization_id)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings

@router.get("/", response_model=schemas.SystemSettingsOut)
def read_settings(
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(require_permission(Permissions.SETTINGS_READ))
):
    return get_or_create_settings(db, tenant.organization_id)

@router.patch("/", response_model=schemas.SystemSettingsOut)
def update_settings(
    settings_update: schemas.SystemSettingsUpdate,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(require_permission(Permissions.SETTINGS_MANAGE))
):
    settings = get_or_create_settings(db, tenant.organization_id)

    update_data = settings_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(settings, key, value)

    db.commit()
    db.refresh(settings)
    return settings
