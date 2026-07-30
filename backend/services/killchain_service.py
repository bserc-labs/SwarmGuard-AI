from sqlalchemy.orm import Session
from fastapi import BackgroundTasks
from datetime import datetime
import models
from utils.logger import logger
from services.ws_manager import ws_manager

class AutonomousKillChainEngine:
    @staticmethod
    def evaluate_and_intercept(
        db: Session, 
        drone_id: str, 
        threat_level: int, 
        violated_zones: list, 
        background_tasks: BackgroundTasks,
        is_silent: bool = False
    ) -> dict:
        """
        Evaluates a drone's state against autonomous defense rules.
        Executes mitigation if conditions are met.
        """
        mitigation_action = None
        reason = None

        # Rule 1: CRITICAL Threat + Inside Restricted Geofence -> HARD_KILL
        if threat_level >= 85 and len(violated_zones) > 0:
            mitigation_action = "HARD_KILL"
            zone_names = ", ".join([z.name for z in violated_zones])
            reason = f"Critical threat ({threat_level}%) inside restricted zones: {zone_names}"
        
        # Rule 2: Signal loss (Silent drone) -> RETURN_TO_HOME
        elif is_silent:
            mitigation_action = "RETURN_TO_HOME"
            reason = "Drone lost signal / possible jamming detected > 30s"

        if mitigation_action:
            # 1. Log Command to DroneCommand table
            command = models.DroneCommand(
                drone_id=drone_id,
                command_type=mitigation_action,
                reason=reason,
                issued_by="SYSTEM_AUTONOMOUS",
                status="EXECUTED"
            )
            db.add(command)

            # 2. Log to AuditLog
            audit = models.AuditLog(
                username="SYSTEM_AUTONOMOUS",
                action=f"AUTONOMOUS_INTERCEPT_{mitigation_action}",
                target=drone_id,
                details=reason
            )
            db.add(audit)
            
            # Commit to DB
            try:
                db.commit()
                logger.warning(f"🤖 [AUTONOMOUS KILL-CHAIN] Intercept executed: {mitigation_action} on {drone_id}. Reason: {reason}")
            except Exception as e:
                db.rollback()
                logger.error(f"Failed to log autonomous kill-chain action: {e}")

            # 3. Broadcast Alert to UI
            background_tasks.add_task(
                ws_manager.broadcast, 
                {
                    "type": "AUTONOMOUS_INTERCEPT",
                    "drone_id": drone_id,
                    "action": mitigation_action,
                    "reason": reason,
                    "timestamp": datetime.utcnow().isoformat()
                }
            )

            return {
                "intercepted": True,
                "action": mitigation_action,
                "reason": reason
            }

        return {"intercepted": False}

killchain_engine = AutonomousKillChainEngine()

