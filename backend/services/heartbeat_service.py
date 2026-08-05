from datetime import datetime, timedelta
from sqlalchemy.orm import Session
import models
from services.ws_manager import ws_manager
from utils.logger import logger

SILENCE_THRESHOLD_SECONDS = 30

def check_drone_heartbeats(db: Session):
    """
    Check all drones. If last_seen is older than SILENCE_THRESHOLD_SECONDS,
    mark drone status as SILENT_POSSIBLE_JAMMING and broadcast an alert.
    """
    now = datetime.utcnow()
    cutoff_time = now - timedelta(seconds=SILENCE_THRESHOLD_SECONDS)

    # Query drones that were active but haven't been seen since cutoff_time
    silent_drones = db.query(models.Drone).filter(
        models.Drone.status.in_(["ACTIVE", "SAFE_MODE"]),
        models.Drone.last_seen < cutoff_time
    ).all()

    alert_count = 0
    for drone in silent_drones:
        drone.status = "SILENT_POSSIBLE_JAMMING"
        
        # Log incident
        incident = models.Incident(
            drone_id=drone.drone_id,
            attack_type="SIGNAL_LOSS_JAMMING",
            anomaly_score=0.95,
            threat_level=90,
            severity="CRITICAL",
            shap_values=[{"feature": "signal_loss_duration", "importance": 0.95}],
            explanation=f"CRITICAL: Drone '{drone.drone_id}' has gone SILENT for >{SILENCE_THRESHOLD_SECONDS} seconds. Possible RF Jamming or communication loss."
        )
        db.add(incident)
        alert_count += 1

        # Broadcast emergency WebSocket event
        alert_payload = {
            "event_type": "SILENT_DRONE_ALERT",
            "is_anomaly": True,
            "drone_id": drone.drone_id,
            "attack_type": "SIGNAL_LOSS_JAMMING",
            "threat_level": 90,
            "severity": "CRITICAL",
            "explanation": f"CRITICAL: Drone '{drone.drone_id}' has gone SILENT for >{SILENCE_THRESHOLD_SECONDS}s. Possible RF Jamming or Crash!",
            "timestamp": now.isoformat()
        }
        
        # Since this runs in async background context (via to_thread), we schedule the broadcast
        try:
            import asyncio
            asyncio.run(ws_manager.broadcast(alert_payload))
        except Exception as err:
            logger.error(f"Failed to broadcast heartbeat alert for {drone.drone_id}: {err}")


        logger.warning(f"🚨 HEARTBEAT ALERT: Drone '{drone.drone_id}' is SILENT since {drone.last_seen}")

    if alert_count > 0:
        db.commit()

    return alert_count
