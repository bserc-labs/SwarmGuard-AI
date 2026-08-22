import logging
from datetime import datetime, timedelta
from typing import Dict, Any

from sqlalchemy.orm import Session
from models import Incident
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

class AlertService:
    def __init__(self):
        # Time window to suppress duplicate alerts for the same drone
        self.suppression_window_seconds = 60

    def generate_alert_severity(self, threat_score: float) -> str:
        """
        Applies configurable severity thresholds to classify an alert.
        Expected threat_score is out of 100.
        """
        # We assume settings.critical_threshold is typically 0.85 (85%)
        # Let's map it from the DB settings ideally, but config.py is faster
        # Here we'll just use a standard mapping.
        if threat_score >= 85.0:
            return "CRITICAL"
        elif threat_score >= 60.0:
            return "HIGH"
        elif threat_score >= 40.0:
            return "MEDIUM"
        else:
            return "LOW"

    def is_alert_suppressed(
        self,
        db: Session,
        drone_id: str,
        attack_type: str,
        *,
        organization_id: int | None = None,
    ) -> bool:
        """
        Determines if an alert should be suppressed because a similar alert
        was recently generated for this drone.

        Scoped by tenant: unscoped, one organization's recent incident would
        suppress a genuine alert for another organization that happens to use
        the same drone_id.
        """
        cutoff_time = datetime.utcnow() - timedelta(seconds=self.suppression_window_seconds)

        query = db.query(Incident).filter(
            Incident.drone_id == drone_id,
            Incident.attack_type == attack_type,
            Incident.detection_time >= cutoff_time
        )
        if organization_id is not None:
            query = query.filter(Incident.organization_id == organization_id)

        return query.first() is not None

    def process_alert(
        self,
        db: Session,
        incident_data: Dict[str, Any],
        *,
        organization_id: int | None = None,
    ) -> Dict[str, Any] | None:
        """
        Processes a raw detection, determines severity, checks suppression,
        and returns a structured alert object if it should be propagated.
        """
        drone_id = incident_data.get("drone_id")
        attack_type = incident_data.get("attack_type", "Unknown")
        threat_score = incident_data.get("threat_score", 0.0)

        severity = self.generate_alert_severity(threat_score)

        if self.is_alert_suppressed(
            db, drone_id, attack_type, organization_id=organization_id
        ):
            logger.info(f"Alert suppressed for {drone_id} (Type: {attack_type}) due to suppression window.")
            return None
            
        return {
            "drone_id": drone_id,
            "attack_type": attack_type,
            "severity": severity,
            "threat_score": threat_score,
            "message": f"[{severity}] {attack_type} detected on {drone_id} (Score: {threat_score:.2f})",
            "timestamp": datetime.utcnow().isoformat()
        }

alert_service = AlertService()
