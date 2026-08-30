"""
Autonomous Kill-Chain Engine — OBSERVER / DRY-RUN MODE (Sprint 7)

Sprint 7 CRITICAL: This engine evaluates threat conditions but does NOT
execute physical drone commands. All actions are recorded as PENDING
CommandRequests for human review.
"""
from datetime import datetime

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

import models
from services.audit_service import audit_service
from services.ws_manager import ws_manager
from utils.logger import logger


class AutonomousKillChainEngine:
    # Sprint 7: OBSERVER MODE — no physical commands transmitted.
    EXECUTION_MODE = "DRY_RUN"

    @staticmethod
    def evaluate_and_intercept(
        db: Session,
        drone_id: str,
        threat_level: int,
        violated_zones: list,
        background_tasks: BackgroundTasks,
        is_silent: bool = False,
        organization_id: int | None = None
    ) -> dict:
        """
        Evaluates a drone's state against autonomous defense rules.
        Records a CommandRequest in DRY-RUN mode. Does NOT execute.
        """
        mitigation_action = None
        reason = None

        # Rule 1: CRITICAL Threat + Inside Restricted Geofence
        if threat_level >= 85 and len(violated_zones) > 0:
            mitigation_action = "EMERGENCY_LAND"  # Changed from HARD_KILL
            zone_names = ", ".join([z.name for z in violated_zones])
            reason = f"Critical threat ({threat_level}%) inside restricted zones: {zone_names}"

        # Rule 2: Signal loss (Silent drone)
        elif is_silent:
            mitigation_action = "RETURN_TO_HOME"
            reason = "Drone lost signal / possible jamming detected > 30s"

        if mitigation_action:
            # DRY-RUN: Record as a PENDING CommandRequest, NOT execute
            command = models.CommandRequest(
                organization_id=organization_id,
                drone_id=drone_id,
                requested_by="SYSTEM_AUTONOMOUS",
                command_type=mitigation_action,
                reason=reason,
                status="PENDING"  # DRY-RUN: Always PENDING, never EXECUTED
            )
            db.add(command)

            audit_service.log(
                db=db,
                actor="SYSTEM_AUTONOMOUS",
                organization_id=organization_id,
                action=f"AUTONOMOUS_INTERCEPT_REQUESTED_{mitigation_action}",
                resource="command_request",
                target=drone_id,
                new_state="PENDING",
                details=f"DRY-RUN: {reason}. Awaiting human approval."
            )

            try:
                db.commit()
                logger.warning(
                    f"🤖 [DRY-RUN KILL-CHAIN] Intercept REQUESTED (not executed): "
                    f"{mitigation_action} on {drone_id}. Reason: {reason}"
                )
            except Exception as e:
                db.rollback()
                logger.error(f"Failed to log autonomous kill-chain request: {e}")

            # Broadcast alert to UI (informational only)
            background_tasks.add_task(
                ws_manager.broadcast,
                {
                    "type": "AUTONOMOUS_INTERCEPT_REQUEST",
                    "mode": "DRY_RUN",
                    "drone_id": drone_id,
                    "action": mitigation_action,
                    "reason": reason,
                    "status": "PENDING_APPROVAL",
                    "timestamp": datetime.utcnow().isoformat()
                },
                organization_id,
            )

            return {
                "intercepted": False,  # Not actually intercepted in DRY-RUN
                "action_requested": mitigation_action,
                "status": "PENDING_APPROVAL",
                "reason": reason,
                "mode": "DRY_RUN"
            }

        return {"intercepted": False, "mode": "DRY_RUN"}

killchain_engine = AutonomousKillChainEngine()
