"""Per-device ingest credentials: issue, list, revoke. Admin only.

Paths sit under /drones next to the command routes. Every query is scoped to
the caller's organization; a credential id from another tenant is a 404, the
same answer as one that does not exist.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

import models
import schemas
from database import get_db
from middleware.auth_middleware import TenantContext, require_permission
from middleware.rbac import Permissions
from services import device_credentials
from services.audit_service import audit_service

router = APIRouter(prefix="/drones", tags=["device credentials"])
manage = require_permission(Permissions.DEVICE_CREDENTIALS_MANAGE)


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post(
    "/{drone_id}/credentials",
    response_model=schemas.DeviceCredentialIssued,
    status_code=status.HTTP_201_CREATED,
)
def issue_credential(
    drone_id: str,
    body: schemas.DeviceCredentialCreate,
    request: Request,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(manage),
):
    """Issue a key for one drone. The key is in this response and nowhere else, ever."""
    credential, key = device_credentials.issue(
        db,
        organization_id=tenant.organization_id,
        drone_id=drone_id,
        issued_by=tenant.username,
        label=body.label,
    )
    db.flush()
    audit_service.log_from_context(
        db=db,
        tenant=tenant,
        action="DEVICE_CREDENTIAL_ISSUED",
        resource="DeviceCredential",
        resource_id=str(credential.id),
        target=drone_id,
        details=f"Issued key {credential.key_prefix}... for drone '{drone_id}'"
        + (f" ({body.label})" if body.label else ""),
        ip_address=_client_ip(request),
    )
    db.commit()
    db.refresh(credential)
    return schemas.DeviceCredentialIssued.model_validate(credential).model_copy(update={"key": key})


@router.get("/{drone_id}/credentials", response_model=list[schemas.DeviceCredentialOut])
def list_credentials(
    drone_id: str,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(manage),
):
    """A drone's keys, newest first: prefix, label, last use, revocation. Never the key."""
    return (
        db.query(models.DeviceCredential)
        .filter(
            models.DeviceCredential.organization_id == tenant.organization_id,
            models.DeviceCredential.drone_id == drone_id,
        )
        .order_by(models.DeviceCredential.created_at.desc(), models.DeviceCredential.id.desc())
        .all()
    )


@router.delete("/{drone_id}/credentials/{credential_id}", response_model=schemas.DeviceCredentialOut)
def revoke_credential(
    drone_id: str,
    credential_id: int,
    request: Request,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(manage),
):
    """Revoke one key. Takes effect on the next packet; the drone's other keys are untouched."""
    credential = (
        db.query(models.DeviceCredential)
        .filter(
            models.DeviceCredential.id == credential_id,
            models.DeviceCredential.organization_id == tenant.organization_id,
            models.DeviceCredential.drone_id == drone_id,
        )
        .first()
    )
    if credential is None:
        raise HTTPException(status_code=404, detail="Credential not found")
    if device_credentials.revoke(credential, revoked_by=tenant.username):
        audit_service.log_from_context(
            db=db,
            tenant=tenant,
            action="DEVICE_CREDENTIAL_REVOKED",
            resource="DeviceCredential",
            resource_id=str(credential.id),
            target=drone_id,
            details=f"Revoked key {credential.key_prefix}... for drone '{drone_id}'",
            ip_address=_client_ip(request),
        )
        db.commit()
        db.refresh(credential)
    return credential
