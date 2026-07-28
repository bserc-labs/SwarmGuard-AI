from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from database import get_db
import models
import schemas
from middleware.auth_middleware import get_admin_user, get_current_user
from services.auth_service import get_password_hash

router = APIRouter(prefix="/users", tags=["users"])

@router.post("/", response_model=schemas.UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    user: schemas.UserCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_admin_user)
):
    db_user = db.query(models.User).filter(models.User.username == user.username).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")
        
    hashed_password = get_password_hash(user.password)
    new_user = models.User(
        username=user.username,
        email=user.email,
        password=hashed_password,
        role="operator"
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    return new_user

@router.get("/me", response_model=schemas.UserOut)
def read_users_me(current_user: models.User = Depends(get_current_user)):
    return current_user

@router.patch("/me", response_model=schemas.UserOut)
def update_user_me(
    user_update: schemas.UserUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Update current user's email classification."""
    if user_update.email is not None:
        current_user.email = user_update.email
        db.commit()
        db.refresh(current_user)
    return current_user

@router.post("/me/password")
def change_password(
    pwd_data: schemas.PasswordUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Securely change current user's password."""
    from services.auth_service import verify_password, get_password_hash
    if not verify_password(pwd_data.current_password, current_user.password):
        raise HTTPException(status_code=400, detail="Current authorization key is incorrect")
    
    current_user.password = get_password_hash(pwd_data.new_password)
    db.commit()
    return {"message": "Authorization key updated successfully"}
