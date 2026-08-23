from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from dataclasses import dataclass

import models
from database import get_db
from services.auth_service import decode_access_token
from middleware.rbac import has_permission, Permissions

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


@dataclass
class TenantContext:
    """
    Immutable context resolved from the authenticated request.
    All protected services receive this to enforce tenant isolation.
    """
    user_id: int
    username: str
    organization_id: int
    role: str

    def has_permission(self, permission: str) -> bool:
        return has_permission(self.role, permission)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> models.User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception

    username: str = payload.get("sub")
    if username is None:
        raise credentials_exception

    user = db.query(models.User).filter(models.User.username == username).first()
    if user is None:
        raise credentials_exception

    # Session revocation. A token minted before the user's password or role
    # changed carries a stale version and is rejected. Tokens issued before this
    # column existed have no claim at all, so they are treated as revoked.
    if payload.get("tv") != user.token_version:
        raise credentials_exception

    return user


def get_tenant_context(current_user: models.User = Depends(get_current_user)) -> TenantContext:
    """
    Resolves tenant identity from authenticated user.
    Organization ID is derived server-side — never trusted from client input.
    """
    if current_user.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not assigned to any organization."
        )

    return TenantContext(
        user_id=current_user.id,
        username=current_user.username,
        organization_id=current_user.organization_id,
        role=current_user.role.lower(),
    )


def require_permission(permission: str):
    """
    FastAPI dependency that checks if the current user's role
    grants them a specific permission.
    """
    def checker(tenant: TenantContext = Depends(get_tenant_context)):
        if not tenant.has_permission(permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: requires '{permission}'"
            )
        return tenant
    return checker


# --- Convenience Dependencies (backward-compatible) ---
def require_role(allowed_roles: list[str]):
    def role_checker(current_user: models.User = Depends(get_current_user)):
        if current_user.role.lower() not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Operation not permitted"
            )
        return current_user
    return role_checker


get_admin_user = require_role(["admin", "commander"])
get_commander_user = require_role(["admin", "commander"])
get_analyst_user = require_role(["admin", "commander", "analyst"])
get_operator_user = require_role(["admin", "commander", "analyst", "observer", "operator"])
