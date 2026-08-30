from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

import models
import schemas
from database import get_db
from middleware.auth_middleware import TenantContext, require_permission
from middleware.rbac import Permissions
from services.audit_service import audit_service

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
    """Update this organization's settings. Never another organization's.

    The row is looked up by the tenant context derived from the JWT, so there is
    no path by which a client can name the organization it is writing to.
    """
    settings = get_or_create_settings(db, tenant.organization_id)

    update_data = settings_update.model_dump(exclude_unset=True)

    # Validate the *resulting* band ordering, not just the fields that arrived.
    # A partial update carrying only one threshold can still invert the bands
    # against the stored value of the other.
    if "critical_threshold" in update_data or "high_threshold" in update_data:
        try:
            schemas.SystemSettingsOrdering(
                critical_threshold=update_data.get(
                    "critical_threshold", settings.critical_threshold
                ),
                high_threshold=update_data.get("high_threshold", settings.high_threshold),
            )
        except ValidationError as exc:
            # A ValidationError raised inside a handler is not the one FastAPI
            # turns into a 422 -- that conversion happens only while parsing the
            # request. Left to propagate, this reaches the global handler and
            # the caller sees a 500 for what is plainly a bad request.
            raise HTTPException(
                # Literal rather than the starlette constant, whose name changed
                # between versions and now emits a deprecation warning.
                status_code=422,
                detail=exc.errors(include_url=False, include_input=False),
            ) from exc

    for key, value in update_data.items():
        setattr(settings, key, value)

    audit_service.log_from_context(
        db=db,
        tenant=tenant,
        action="SETTINGS_UPDATED",
        resource="system_settings",
        resource_id=str(settings.id),
        details=", ".join(f"{k}={v}" for k, v in sorted(update_data.items())),
    )

    db.commit()
    db.refresh(settings)
    return settings
