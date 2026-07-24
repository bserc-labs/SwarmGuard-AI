from fastapi import APIRouter, Depends
import models
from middleware.auth_middleware import (
    get_current_user,
    get_admin_user,
    get_operator_user,
)

router = APIRouter(
    prefix="/protected",
    tags=["Protected"]
)

@router.get("/me")
def read_current_user(
    current_user: models.User = Depends(get_current_user)
):
    return {
        "username": current_user.username,
        "email": current_user.email,
        "role": current_user.role,
    }


@router.get("/admin")
def admin_only(
    current_user: models.User = Depends(get_admin_user)
):
    return {
        "message": "Welcome Admin!"
    }


@router.get("/operator")
def operator_only(
    current_user: models.User = Depends(get_operator_user)
):
    return {
        "message": f"Hello {current_user.username}"
    }