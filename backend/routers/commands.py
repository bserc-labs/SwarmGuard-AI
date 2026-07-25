from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List
import models
import schemas
from database import get_db
from middleware.auth_middleware import get_operator_user
from services.ws_manager import ws_manager
from utils.logger import logger

router = APIRouter(prefix="/drones", tags=["commands"])

VALID_COMMANDS = ["RETURN_TO_HOME", "EMERGENCY_LAND", "SWITCH_SAFE_MODE", "KILL_MOTOR", "RESUME_MISSION"]

@router.get("", response_model=List[schemas.DroneOut])
def get_all_drones(db: Session = Depends(get_db), current_user: models.User = Depends(get_operator_user)):
    return db.query(models.Drone).all()

@router.post("/{drone_id}/command", response_model=schemas.CommandOut)
def issue_drone_command(
    drone_id: str,
    cmd_in: schemas.CommandCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_operator_user)
):
    if cmd_in.command_type not in VALID_COMMANDS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid command type. Must be one of: {', '.join(VALID_COMMANDS)}"
        )

    # Find or register drone
    drone = db.query(models.Drone).filter(models.Drone.drone_id == drone_id).first()
    if not drone:
        drone = models.Drone(drone_id=drone_id, status="ACTIVE")
        db.add(drone)
        db.commit()
        db.refresh(drone)

    # Update drone status based on command
    if cmd_in.command_type == "RETURN_TO_HOME":
        drone.status = "RETURNING"
    elif cmd_in.command_type in ["EMERGENCY_LAND", "KILL_MOTOR"]:
        drone.status = "GROUNDED"
    elif cmd_in.command_type == "RESUME_MISSION":
        drone.status = "ACTIVE"
    elif cmd_in.command_type == "SWITCH_SAFE_MODE":
        drone.status = "SAFE_MODE"
        
    drone.last_command = cmd_in.command_type

    # Log command
    cmd_record = models.DroneCommand(
        drone_id=drone_id,
        command_type=cmd_in.command_type,
        reason=cmd_in.reason,
        issued_by=current_user.username,
        status="EXECUTED"
    )
    
    db.add(cmd_record)
    db.commit()
    db.refresh(cmd_record)

    # Broadcast command alert via WebSocket
    command_broadcast = {
        "event_type": "DRONE_COMMAND",
        "drone_id": drone_id,
        "command_type": cmd_in.command_type,
        "reason": cmd_in.reason,
        "issued_by": current_user.username,
        "status": drone.status
    }
    background_tasks.add_task(ws_manager.broadcast, command_broadcast)
    logger.info(f"Command '{cmd_in.command_type}' issued to drone '{drone_id}' by {current_user.username}")

    return cmd_record

@router.get("/{drone_id}/commands", response_model=List[schemas.CommandOut])
def get_drone_command_history(
    drone_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_operator_user)
):
    return db.query(models.DroneCommand).filter(models.DroneCommand.drone_id == drone_id).all()

from services.heartbeat_service import check_drone_heartbeats

@router.post("/check-heartbeats")
def trigger_heartbeat_check(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_operator_user)
):
    alerts = check_drone_heartbeats(db)
    return {"status": "ok", "silent_drones_detected": alerts}
