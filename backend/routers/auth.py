from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import or_
from sqlalchemy.orm import Session

import models
import schemas
from database import get_db
from middleware.auth_middleware import get_current_user
from services.audit_service import audit_service
from services.auth_service import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    verify_password,
)

# The shared, Redis-backed limiter. This module previously constructed its own
# in-memory Limiter, so the login limit was counted separately from every other
# rate-limited route and was lost on restart.
from utils.limiter import limiter

router = APIRouter(prefix="/auth", tags=["auth"])


def _log_audit(db: Session, username: str, action: str, ip: str | None = None, organization_id: int | None = None):
    """Log an authentication audit event with the new expanded schema."""
    audit_service.log(
        db=db,
        actor=username,
        action=action,
        organization_id=organization_id,
        resource="auth",
        resource_id=username,
        ip_address=ip,
    )
    db.commit()


@router.post("/login", response_model=schemas.TokenResponse)
@limiter.limit("5/minute")
def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):

    client_ip = request.client.host if request.client else None
    user = db.query(models.User).filter(
        or_(models.User.username == form_data.username, models.User.email == form_data.username)
    ).first()
    if not user:
        _log_audit(db, form_data.username, "LOGIN_FAILED", client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not verify_password(form_data.password, user.password):
        _log_audit(db, form_data.username, "LOGIN_FAILED", client_ip, organization_id=user.organization_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={
            "sub": user.username,
            "role": user.role,
            "org_id": user.organization_id,
            # Compared against the DB on every request; see get_current_user.
            "tv": user.token_version,
        },
        expires_delta=access_token_expires
    )

    _log_audit(db, user.username, "LOGIN_SUCCESS", client_ip, organization_id=user.organization_id)

    return {"access_token": access_token, "token_type": "bearer", "role": user.role}


@router.post("/logout")
def logout(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Sign out everywhere.

    JWTs are stateless, so discarding the client copy alone leaves the token
    valid until it expires. Incrementing token_version invalidates every token
    issued to this user — including any an attacker already holds — which is the
    behaviour "sign out" should have on a security console.
    """
    current_user.token_version = (current_user.token_version or 0) + 1

    _log_audit(
        db,
        current_user.username,
        "LOGOUT",
        request.client.host if request.client else None,
        organization_id=current_user.organization_id,
    )

    return {"message": "Signed out. All sessions for this account are now invalid."}
