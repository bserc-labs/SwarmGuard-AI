import logging
from typing import Dict, Any
from sqlalchemy.orm import Session
from datetime import datetime

from models import Incident
from services.alert_service import alert_service
from services.priority_service import priority_service
from services.recommendation_service import recommendation_service

logger = logging.getLogger(__name__)

# Ordinal encoding for the Integer `threat_level` column. The inference layer
# speaks in band names, the schema stores a rank, and the dashboard sorts on it.
THREAT_LEVEL_ORDINALS = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


def _threat_level_ordinal(threat_level: Any) -> int:
    """Coerce a threat level to the Integer rank the column expects.

    Accepts the band name the inference service emits, an int that is already
    a rank, or None/UNKNOWN from a failed inference (which maps to 0).
    """
    if isinstance(threat_level, int):
        return threat_level
    if isinstance(threat_level, str):
        return THREAT_LEVEL_ORDINALS.get(threat_level.upper(), 0)
    return 0


class IncidentEngine:
    """
    Orchestrates the conversion of AI anomaly detections into fully qualified Incidents.
    Delegates alerting, prioritization, and recommendations to decoupled sub-services.
    """
    
    def process_ai_detection(
        self,
        db: Session,
        detection: Dict[str, Any],
        mission_id: str | None = None,
        *,
        organization_id: int | None = None,
    ) -> Incident | None:
        """
        Takes raw output from the Explainable AI layer and determines if a new
        Incident should be created or an existing one updated.

        `organization_id` is required for tenant isolation: without it the
        suppression check and repeat count read across every tenant's
        incidents, and the created row is invisible to the org that owns the
        drone. It is keyword-only so an existing positional caller cannot pass
        a mission_id into it by accident.
        """
        drone_id = detection.get("drone_id")
        # Extract inference outputs
        prediction = detection.get("prediction", {})
        explanation = detection.get("explanation", {})

        is_anomaly = prediction.get("is_anomaly", False)

        if not is_anomaly:
            return None # Do nothing for normal telemetry

        anomaly_score = prediction.get("anomaly_score", 0.0)
        # Using threat_level logic for basic mapping or passing threat_score
        # For simplicity we assume threat_score is same as anomaly_score internally for now if missing
        threat_score = prediction.get("threat_score", anomaly_score)

        # Short, filterable label ("GPS_SPOOFING") derived from the dominant
        # SHAP feature family. Falls back to the prose primary cause only when
        # the explanation layer could not classify it.
        summary = explanation.get("summary", {})
        attack_type = summary.get("Attack Type") or summary.get("Primary Cause", "Unknown Anomaly")

        incident_data = {
            "drone_id": drone_id,
            "attack_type": attack_type,
            "threat_score": threat_score
        }

        # 1. Alerting & Suppression
        alert = alert_service.process_alert(
            db, incident_data, organization_id=organization_id
        )
        if not alert:
            # Suppressed, but we might want to update the existing incident's last detection time.
            self._update_existing_incident(
                db, drone_id, attack_type, threat_score,
                organization_id=organization_id,
            )
            return None

        severity = alert["severity"]

        # 2. Priority Calculation
        # Count repeat incidents for this drone
        repeat_query = db.query(Incident).filter(
            Incident.drone_id == drone_id,
            Incident.status.in_(["NEW", "OPEN"])
        )
        if organization_id is not None:
            repeat_query = repeat_query.filter(Incident.organization_id == organization_id)
        repeat_count = repeat_query.count()
        
        priority = priority_service.calculate_priority(
            threat_score=threat_score,
            anomaly_score=anomaly_score,
            repeat_incidents_count=repeat_count,
            mission_criticality=None # Will use default
        )
        
        # 3. Recommendations
        recommendation = recommendation_service.generate_recommendation(attack_type, summary)
        
        # 4. JSON Explanation format exactly as requested by user
        metadata = explanation.get("metadata", {})
        structured_json = {
            "primary_cause": summary.get("Primary Cause", ""),
            "secondary_cause": summary.get("Secondary Cause", ""),
            "supporting_indicators": summary.get("Supporting Indicators", "").split(", "),
            "recommended_action": recommendation,
            "model_version": metadata.get("model_version", "v1.0"),
            "explanation_strength": metadata.get("explanation_confidence_percent", 0.0)
        }
        
        # 5. Create Incident
        new_incident = Incident(
            drone_id=drone_id,
            organization_id=organization_id,
            mission_id=mission_id,
            attack_type=attack_type,
            threat_score=threat_score,
            anomaly_score=anomaly_score,
            # The inference service reports threat_level as a band name; the
            # column is an Integer. Passing the string straight through raised
            # a DataError on insert.
            threat_level=_threat_level_ordinal(prediction.get("threat_level")),
            severity=severity,
            priority=priority,
            shap_values=explanation.get("ranked_features", []),
            explanation=str(summary), # Deprecated flat string, keeping for schema compat
            explanation_summary=structured_json,
            recommended_action=recommendation,
            model_version=structured_json["model_version"],
            feature_version=metadata.get("feature_engineering_version", "v1.0"),
            status="NEW"
        )
        
        db.add(new_incident)
        db.commit()
        db.refresh(new_incident)
        
        logger.info(f"Generated new Incident #{new_incident.id} for Drone {drone_id} (Severity: {severity}, Priority: {priority})")
        return new_incident

    def _update_existing_incident(
        self,
        db: Session,
        drone_id: str,
        attack_type: str,
        threat_score: float,
        *,
        organization_id: int | None = None,
    ):
        """
        Updates the threat score and updated_at timestamp of an ongoing incident
        to prevent duplicate spam while keeping the active incident fresh.
        """
        query = db.query(Incident).filter(
            Incident.drone_id == drone_id,
            Incident.attack_type == attack_type,
            Incident.status.in_(["NEW", "OPEN", "ACKNOWLEDGED", "INVESTIGATING", "CONTAINED"])
        )
        if organization_id is not None:
            query = query.filter(Incident.organization_id == organization_id)
        incident = query.order_by(Incident.created_at.desc()).first()
        
        if incident:
            # Escalate threat score if the new one is higher
            if threat_score > incident.threat_score:
                incident.threat_score = threat_score
                # Re-evaluate severity
                incident.severity = alert_service.generate_alert_severity(threat_score)
                # Re-evaluate priority
                incident.priority = priority_service.calculate_priority(incident.threat_score, incident.anomaly_score, 1)
            
            incident.updated_at = datetime.utcnow()
            db.commit()

incident_engine = IncidentEngine()
