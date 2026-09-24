from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

import models
import schemas
from config import get_settings
from database import get_db
from middleware.auth_middleware import get_current_user, oauth2_scheme
from services import ws_tickets
from services.audit_service import audit_service
from services.auth_service import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    decode_access_token,
    verify_password,
)

# The shared, Redis-backed limiter. This module previously constructed its own
# in-memory Limiter, so the login limit was counted separately from every other
# rate-limited route and was lost on restart.
from utils.limiter import limiter

router = APIRouter(prefix="/auth", tags=["auth"])

# Defaults to 5/minute, the production value. Configurable only so the live
# integration suite can be given room to run -- see Settings.LOGIN_RATE_LIMIT.
LOGIN_RATE_LIMIT = get_settings().LOGIN_RATE_LIMIT


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
@limiter.limit(LOGIN_RATE_LIMIT)
def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):

    client_ip = request.client.host if request.client else None
    # Resolve the identifier deterministically. `username` and `email` are each
    # unique, but nothing stops one account's email equalling another account's
    # username. The previous `or_(...)` + `.first()` had no ORDER BY, so which of
    # the two rows came back was a matter of heap order -- an operator in one
    # organization could shadow an admin in another by setting their email to
    # that admin's username, and the admin was locked out, with the failed
    # logins audited against the wrong organization. An exact username match
    # always wins; email is consulted only when no username matches.
    identifier = form_data.username
    user = db.query(models.User).filter(models.User.username == identifier).first()
    if user is None:
        user = db.query(models.User).filter(models.User.email == identifier).first()
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


@router.post("/ws-ticket", response_model=schemas.WebSocketTicket)
@limiter.limit("60/minute")
def websocket_ticket(
    request: Request,
    token: str = Depends(oauth2_scheme),
    current_user: models.User = Depends(get_current_user),
):
    """A single-use ticket for opening the telemetry socket.

    A browser cannot set headers on a WebSocket handshake, so the credential
    travels in the URL, where proxy logs and browser history keep it. The client
    used to send the session token itself. A ticket opens one socket, lives half
    a minute, and is worthless once spent or logged.

    Rate limited because it is a credential factory: a stolen session should not
    also be an unbounded supply of them.
    """
    claims = decode_access_token(token) or {}
    return {
        "ticket": ws_tickets.issue(
            username=current_user.username,
            organization_id=current_user.organization_id,
            token_version=current_user.token_version or 0,
            # The socket must not outlive the session it was opened from.
            session_expires_at=int(claims.get("exp", 0)),
        ),
        "expires_in": int(ws_tickets.TICKET_LIFETIME.total_seconds()),
    }
