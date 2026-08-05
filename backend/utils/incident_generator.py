import os
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any

try:
    from services.threat_service import ThreatScoreEngine
    from utils.severity_mapper import map_severity
    from utils.explanation_engine import ExplanationEngine
    from utils.recommendation_engine import RecommendationEngine
except ImportError:
    # Enable fallback path routing for standalone script executions
    import sys
    # Parent of backend/utils is backend/ (one level up)
    sys.path.append(os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))
    from services.threat_service import ThreatScoreEngine
    from utils.severity_mapper import map_severity
    from utils.explanation_engine import ExplanationEngine
    from utils.recommendation_engine import RecommendationEngine


class IncidentGenerator:
    """
    Orchestrates the entire Threat Intelligence pipeline to generate complete,
    database-ready and UI-ready incident objects, and aggregates histories.
    """
    def __init__(self, data_dir: str = None):
        self.threat_engine = ThreatScoreEngine()
        self.explanation_engine = ExplanationEngine(data_dir=data_dir)
        self.recommendation_engine = RecommendationEngine(data_dir=data_dir)

    def generate_incident(
        self,
        drone_id: str,
        attack_type: str,
        anomaly_score: float,
        status: str = "Active"
    ) -> Dict[str, Any]:
        """
        Generates a complete incident object containing:
        - Incident ID (UUID)
        - Drone ID
        - Attack Type
        - Threat Score (standardized 0-100)
        - Severity (LOW, MEDIUM, HIGH, CRITICAL)
        - Timestamp (ISO 8601)
        - Explanation (Operator friendly)
        - Recommendation (Dynamic safety steps)
        - Status (Active, Resolved, False Positive)
        """
        # 1. Input sanity check
        if not drone_id:
            raise ValueError("drone_id must be a non-empty string.")
        if not attack_type:
            raise ValueError("attack_type must be a non-empty string.")

        # 2. Threat Score Calculation (Feature 1)
        threat_score = self.threat_engine.get_threat_score(anomaly_score)

        # 3. Severity Mapping (Feature 2)
        severity = map_severity(threat_score)

        # 4. Generate Explanations and Recommendations (Features 4 & 5)
        explanation = self.explanation_engine.generate_explanation(attack_type)
        recommendations = self.recommendation_engine.generate_recommendations(
            attack_type=attack_type,
            threat_score=threat_score,
            severity=severity
        )

        # 5. Timestamp and Unique ID
        incident_id = f"INC-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"
        timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        incident = {
            "incident_id": incident_id,
            "drone_id": drone_id,
            "attack_type": attack_type,
            "threat_score": threat_score,
            "severity": severity,
            "timestamp": timestamp,
            "explanation": explanation,
            "recommendation": recommendations,
            "status": status
        }
        return incident

    @staticmethod
    def prepare_timeline(incidents: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Aggregates a list of incidents into a dashboard-ready timeline object,
        grouped by status and featuring high-level threat telemetry.
        """
        # Sort by timestamp descending (newest first)
        sorted_incidents = sorted(
            incidents,
            key=lambda x: x.get("timestamp", ""),
            reverse=True
        )

        active = [i for i in sorted_incidents if i.get("status") == "Active"]
        resolved = [i for i in sorted_incidents if i.get("status") == "Resolved"]
        false_positives = [i for i in sorted_incidents if i.get("status") == "False Positive"]

        summary = {
            "total_incidents": len(incidents),
            "active_count": len(active),
            "resolved_count": len(resolved),
            "false_positive_count": len(false_positives),
            "severity_distribution": {
                "LOW": sum(1 for i in incidents if i.get("severity") == "LOW"),
                "MEDIUM": sum(1 for i in incidents if i.get("severity") == "MEDIUM"),
                "HIGH": sum(1 for i in incidents if i.get("severity") == "HIGH"),
                "CRITICAL": sum(1 for i in incidents if i.get("severity") == "CRITICAL"),
            }
        }

        return {
            "summary": summary,
            "timeline": {
                "active": active,
                "resolved": resolved,
                "false_positive": false_positives
            }
        }
