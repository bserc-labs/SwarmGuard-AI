import random
from typing import Dict, Any, List

class ThreatIntelligenceService:
    def calculate_threat_score(self, anomaly_score: float, attack_type: str) -> int:
        """Calculate threat score from 0 to 100 based on anomaly."""
        return min(100, max(0, int(abs(anomaly_score) * 200)))

    def map_severity(self, threat_score: int) -> str:
        """Severity mapping based on score."""
        if threat_score <= 25:
            return "LOW"
        elif threat_score <= 50:
            return "MEDIUM"
        elif threat_score <= 75:
            return "HIGH"
        else:
            return "CRITICAL"

    def get_human_readable_explanation(self, attack_type: str, severity: str) -> str:
        """Generate human readable explanation."""
        explanations = {
            "GPS_SPOOFING": "Drone is reporting geographically impossible movements, indicative of GPS signal manipulation.",
            "JAMMING": "Sudden loss of communication fidelity coupled with erratic telemetry patterns.",
            "DOS": "Overwhelming number of network packets detected targeting the drone's communication interface.",
            "REPLAY_ATTACK": "Identical telemetry sequences are being replayed, suggesting communication interception."
        }
        base_exp = explanations.get(attack_type, "Unusual anomalous behavior detected in telemetry data.")
        return f"{severity} severity alert: {base_exp} Immediate operator review recommended."

    def generate_shap_placeholder(self) -> List[Dict[str, Any]]:
        """SHAP placeholder for feature importance."""
        features = ["speed", "altitude", "gps_variance", "signal_strength", "battery_drain"]
        
        shap_values = []
        for _ in range(3):  # Top 3 features
            feat = random.choice(features)
            features.remove(feat)
            shap_values.append({
                "feature": feat,
                "importance": round(random.uniform(0.1, 0.9), 2)
            })
            
        return sorted(shap_values, key=lambda x: x["importance"], reverse=True)

    def generate_alert(self, is_anomaly: bool, anomaly_score: float, attack_type: str) -> Dict[str, Any]:
        """Alert generation combining all components."""
        if not is_anomaly:
            return {
                "is_anomaly": False,
                "anomaly_score": anomaly_score,
                "attack_type": None,
                "threat_level": 0,
                "severity": "NONE",
                "explanation": "No anomalies detected.",
                "shap_top3": []
            }
            
        threat_level = self.calculate_threat_score(anomaly_score, attack_type)
        severity = self.map_severity(threat_level)
        explanation = self.get_human_readable_explanation(attack_type, severity)
        shap_top3 = self.generate_shap_placeholder()
        
        return {
            "is_anomaly": True,
            "anomaly_score": anomaly_score,
            "attack_type": attack_type,
            "threat_level": threat_level,
            "severity": severity,
            "explanation": explanation,
            "shap_top3": shap_top3
        }

    def generate_incident_summary(self, alert_data: Dict[str, Any], drone_id: str) -> Dict[str, Any]:
        """Incident summary generator for database insertion or notification."""
        return {
            "drone_id": drone_id,
            "incident_type": alert_data.get("attack_type"),
            "severity": alert_data.get("severity"),
            "threat_level": alert_data.get("threat_level"),
            "summary": f"Incident on {drone_id}: {alert_data.get('explanation')}",
            "requires_action": alert_data.get("severity") in ["HIGH", "CRITICAL"]
        }

threat_service = ThreatIntelligenceService()
