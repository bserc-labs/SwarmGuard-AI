from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import timedelta
from slowapi import Limiter
from slowapi.util import get_remote_address
import models
import schemas
from database import get_db
from services.auth_service import verify_password, create_access_token, ACCESS_TOKEN_EXPIRE_MINUTES
from middleware.auth_middleware import get_current_user, get_admin_user

limiter = Limiter(key_func=get_remote_address)
router = APIRouter(prefix="/auth", tags=["auth"])


def _log_audit(db: Session, username: str, action: str, ip: str = None):
    audit = models.AuditLog(username=username, action=action, ip_address=ip)
    db.add(audit)
    db.commit()


@router.post("/login", response_model=schemas.TokenResponse)
@limiter.limit("60/minute")
def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    client_ip = request.client.host if request.client else None
    user = db.query(models.User).filter(models.User.username == form_data.username).first()
    if not user:
        _log_audit(db, form_data.username, "LOGIN_FAILED", client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    if not verify_password(form_data.password, user.password):
        _log_audit(db, form_data.username, "LOGIN_FAILED", client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username, "role": user.role}, expires_delta=access_token_expires
    )
    
    _log_audit(db, user.username, "LOGIN_SUCCESS", client_ip)
    
    return {"access_token": access_token, "token_type": "bearer", "role": user.role}

