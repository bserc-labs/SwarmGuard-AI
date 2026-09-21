
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import models
import schemas
from database import get_db
from middleware.auth_middleware import TenantContext, get_current_user, require_permission
from middleware.rbac import Permissions
from services.audit_service import audit_service
from services.auth_service import get_password_hash

router = APIRouter(prefix="/users", tags=["users"])

@router.post("/", response_model=schemas.UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    user: schemas.UserCreate,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(require_permission(Permissions.USER_MANAGE))
):
    """Create a new user within the current tenant's organization."""
    if db.query(models.User).filter(models.User.username == user.username).first():
        raise HTTPException(status_code=400, detail="Username already registered")

    # username and email are both globally unique columns. Pre-checking only the
    # username meant a duplicate email surfaced as an IntegrityError and a 500.
    if user.email and db.query(models.User).filter(models.User.email == user.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    new_user = models.User(
        username=user.username,
        email=user.email,
        password=get_password_hash(user.password),
        role=user.role,
        organization_id=tenant.organization_id,
    )
    db.add(new_user)

    audit_service.log_from_context(
        db=db, tenant=tenant,
        action="USER_CREATED",
        resource="user", resource_id=user.username,
        new_state=new_user.role,
    )

    try:
        db.commit()
    except IntegrityError:
        # Still possible under a concurrent create; report it as a conflict
        # rather than an unhandled server error.
        db.rollback()
        raise HTTPException(status_code=409, detail="That username or email is already taken") from None

    db.refresh(new_user)
    return new_user

@router.get("/", response_model=list[schemas.UserOut])
def list_users(
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(require_permission(Permissions.USER_MANAGE))
):
    """List all users within the current tenant's organization."""
    return db.query(models.User).filter(
        models.User.organization_id == tenant.organization_id
    ).all()

@router.get("/me", response_model=schemas.UserOut)
def read_users_me(current_user: models.User = Depends(get_current_user)):
    return current_user

@router.patch("/me", response_model=schemas.UserOut)
def update_user_me(
    user_update: schemas.UserUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Update the current user's email.

    A blank or null email is a no-op: omitting the field and sending null both
    mean "no change", and a blank submission normalises to null. Clearing an
    address is not supported by this route.
    """
    if user_update.email is not None:
        current_user.email = user_update.email
        try:
            db.commit()
        except IntegrityError:
            # The unique email index: another account already holds this
            # address. Unhandled, this was a 500 that also left the session in
            # a failed transaction.
            db.rollback()
            raise HTTPException(status_code=409, detail="That email is already in use") from None
        db.refresh(current_user)
    return current_user

@router.post("/me/password")
def change_password(
    pwd_data: schemas.PasswordUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Change the current user's password and revoke existing sessions."""
    from services.auth_service import get_password_hash, verify_password
    if not verify_password(pwd_data.current_password, current_user.password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    if pwd_data.new_password == pwd_data.current_password:
        raise HTTPException(
            status_code=400, detail="The new password must differ from the current one"
        )

    current_user.password = get_password_hash(pwd_data.new_password)
    # Invalidates every token issued before this moment, including the one used
    # to make this request. Changing a password must end other sessions.
    current_user.token_version = (current_user.token_version or 0) + 1
    db.commit()

    return {
        "message": "Password updated. All sessions have been signed out.",
        "sessions_revoked": True,
    }
