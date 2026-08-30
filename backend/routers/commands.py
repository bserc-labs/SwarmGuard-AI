"""
Secure Command Framework — DRY-RUN / OBSERVER MODE

Sprint 7: This module receives, validates, and records command requests.
It does NOT transmit any physical drone commands.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models
import schemas
from database import get_db
from middleware.auth_middleware import TenantContext, require_permission
from middleware.rbac import Permissions
from services.audit_service import audit_service
from utils.logger import logger

router = APIRouter(prefix="/drones", tags=["commands"])

VALID_COMMANDS = ["RETURN_TO_HOME", "LAND", "HOLD", "EMERGENCY_LAND", "SWITCH_SAFE_MODE", "RESUME_MISSION"]
# KILL_MOTOR is explicitly excluded from Sprint 7.


@router.get("", response_model=list[schemas.DroneOut])
def get_all_drones(
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(require_permission(Permissions.DRONE_READ))
):
    """List all drones belonging to the current tenant."""
    return db.query(models.Drone).filter(
        models.Drone.organization_id == tenant.organization_id
    ).all()


@router.post("/{drone_id}/command", response_model=schemas.CommandRequestOut)
def request_command(
    drone_id: str,
    cmd_in: schemas.CommandRequestCreate,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(require_permission(Permissions.DRONE_COMMAND_REQUEST))
):
    """
    Submit a command request (DRY-RUN ONLY).

    This endpoint:
    1. Validates authorization (RBAC).
    2. Validates drone ownership (tenant isolation).
    3. Validates command type.
    4. Records the request with status=PENDING.
    5. Creates an audit event.

    It does NOT transmit any physical command.
    """
    if cmd_in.command_type not in VALID_COMMANDS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid command type. Must be one of: {', '.join(VALID_COMMANDS)}"
        )

    # Validate drone belongs to this tenant
    drone = db.query(models.Drone).filter(
        models.Drone.drone_id == drone_id,
        models.Drone.organization_id == tenant.organization_id
    ).first()
    if not drone:
        raise HTTPException(status_code=404, detail="Drone not found in your organization.")

    # Safety: Do NOT change drone status. This is a request, not an execution.
    cmd_record = models.CommandRequest(
        organization_id=tenant.organization_id,
        drone_id=drone_id,
        requested_by=tenant.username,
        command_type=cmd_in.command_type,
        reason=cmd_in.reason,
        status="PENDING"  # Always PENDING in dry-run mode
    )
    db.add(cmd_record)

    audit_service.log_from_context(
        db=db, tenant=tenant,
        action="COMMAND_REQUESTED",
        resource="command_request",
        target=drone_id,
        new_state="PENDING",
        details=f"Type: {cmd_in.command_type}, Reason: {cmd_in.reason}"
    )

    db.commit()
    db.refresh(cmd_record)

    logger.info(f"[DRY-RUN] Command request '{cmd_in.command_type}' for drone '{drone_id}' by {tenant.username} (org:{tenant.organization_id})")

    return cmd_record


@router.post("/{drone_id}/command/{command_id}/approve", response_model=schemas.CommandRequestOut)
def approve_command(
    drone_id: str,
    command_id: int,
    approval: schemas.CommandApproval,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(require_permission(Permissions.DRONE_COMMAND_APPROVE))
):
    """
    Approve or reject a command request (DRY-RUN ONLY).

    This validates:
    - The command exists and belongs to the current tenant.
    - The command is in PENDING status.
    - Records approval/rejection and audit event.

    It does NOT transmit any physical command, even if approved.
    """
    cmd = db.query(models.CommandRequest).filter(
        models.CommandRequest.command_id == command_id,
        models.CommandRequest.drone_id == drone_id,
        models.CommandRequest.organization_id == tenant.organization_id
    ).first()

    if not cmd:
        raise HTTPException(status_code=404, detail="Command request not found.")

    if cmd.status != "PENDING":
        raise HTTPException(status_code=400, detail=f"Command is already {cmd.status}. Cannot modify.")

    previous_state = cmd.status
    cmd.status = "APPROVED" if approval.approved else "REJECTED"
    cmd.approved_by = tenant.username
    cmd.approved_at = datetime.utcnow()

    audit_service.log_from_context(
        db=db, tenant=tenant,
        action="COMMAND_APPROVAL",
        resource="command_request", resource_id=str(command_id),
        target=drone_id,
        previous_state=previous_state, new_state=cmd.status,
        reason=approval.reason,
        details=f"DRY-RUN: Command {cmd.command_type} {'approved' if approval.approved else 'rejected'}. No physical execution."
    )

    db.commit()
    db.refresh(cmd)

    logger.info(f"[DRY-RUN] Command {command_id} {cmd.status} by {tenant.username}")

    return cmd


@router.get("/{drone_id}/commands", response_model=list[schemas.CommandRequestOut])
def get_drone_command_history(
    drone_id: str,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(require_permission(Permissions.DRONE_READ))
):
    """Get command history for a drone (tenant-scoped)."""
    return db.query(models.CommandRequest).filter(
        models.CommandRequest.drone_id == drone_id,
        models.CommandRequest.organization_id == tenant.organization_id
    ).order_by(models.CommandRequest.created_at.desc()).all()
