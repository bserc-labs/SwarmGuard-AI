import os
import json
from typing import List, Dict, Any

class RecommendationEngine:
    """
    Generates tailored safety recommendations and mitigation steps based on
    the specific attack type, threat score, and severity level.
    """
    def __init__(self, data_dir: str = None):
        if data_dir is None:
            # Resolve 'backend/data/' relative to the utils folder
            current_dir = os.path.dirname(os.path.abspath(__file__))
            self.data_dir = os.path.normpath(os.path.join(current_dir, "..", "data"))
        else:
            self.data_dir = data_dir

    def load_attack_data(self, attack_type: str) -> Dict[str, Any]:
        """Loads the JSON data file for a specific attack type."""
        sanitized_name = os.path.basename(f"{attack_type}.json")
        file_path = os.path.join(self.data_dir, sanitized_name)
        
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Knowledge base file for attack '{attack_type}' not found.")
            
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def generate_recommendations(self, attack_type: str, threat_score: int, severity: str) -> List[str]:
        """
        Generates mitigation steps combining standard attack playbook instructions
        with dynamic severity-level overrides.
        """
        recommendations = []

        # 1. Fetch baseline action from knowledge base
        try:
            data = self.load_attack_data(attack_type)
            base_action = data.get("Recommended Action")
            if base_action:
                recommendations.append(base_action)
        except Exception:
            recommendations.append("Audit all telemetry interfaces and log suspicious packets.")

        # 2. Add severity-based mitigation directives
        severity_upper = severity.upper()
        if severity_upper == "CRITICAL" or threat_score >= 76:
            recommendations.insert(0, "EMERGENCY: Initiate autopilot Safe Mode / Return-To-Home (RTH) immediately.")
            recommendations.append("EMERGENCY: Trigger red alert warning on operator Ground Control Station (GCS).")
            recommendations.append("EMERGENCY: Enforce secure channel encryption keys or switch to secondary backup link.")
        elif severity_upper == "HIGH" or 51 <= threat_score <= 75:
            recommendations.insert(0, "HIGH THREAT: Engage GPS verification algorithms and cross-reference with inertial sensors.")
            recommendations.append("HIGH THREAT: Command drone to hover in place to isolate flight drift.")
            recommendations.append("HIGH THREAT: Notify operator to prepare for manual telemetry takeover.")
        elif severity_upper == "MEDIUM" or 26 <= threat_score <= 50:
            recommendations.insert(0, "MEDIUM THREAT: Cross-validate active telemetry feeds against companion computer logs.")
            recommendations.append("MEDIUM THREAT: Log warning in the operator diagnostic interface.")
        else:  # LOW
            recommendations.insert(0, "LOW THREAT: Log anomaly event locally on drone computer.")
            recommendations.append("LOW THREAT: Continue current autonomous mission parameters while monitoring stability.")

        return recommendations
