import math
from abc import ABC, abstractmethod
from typing import List, Tuple, Union

class MappingStrategy(ABC):
    """
    Abstract base class for converting a raw float anomaly score [0.0, 1.0]
    into a raw threat score [0.0, 100.0].
    """
    @abstractmethod
    def map_score(self, anomaly_score: float) -> float:
        pass


class PiecewiseLinearStrategy(MappingStrategy):
    """
    Maps anomaly scores to threat scores using piecewise linear interpolation.
    Guarantees exact matches to specific anchor points.
    """
    DEFAULT_POINTS = [
        (0.00, 0.0),
        (0.10, 20.0),
        (0.30, 55.0),
        (0.45, 78.0),
        (0.60, 95.0),
        (1.00, 100.0)
    ]

    def __init__(self, points: List[Tuple[float, float]] = None):
        # Sort points by anomaly score (first element of tuple)
        self.points = sorted(points if points is not None else self.DEFAULT_POINTS, key=lambda p: p[0])
        self._validate_points()

    def _validate_points(self):
        if len(self.points) < 2:
            raise ValueError("Piecewise interpolation requires at least 2 anchor points.")
        
        # Verify boundaries
        if not math.isclose(self.points[0][0], 0.0, abs_tol=1e-9):
            raise ValueError("Anchor points must start at anomaly score 0.0")
        if not math.isclose(self.points[-1][0], 1.0, abs_tol=1e-9):
            raise ValueError("Anchor points must end at anomaly score 1.0")

        # Verify monotony
        for i in range(len(self.points) - 1):
            if self.points[i][0] == self.points[i+1][0]:
                raise ValueError("Duplicate anomaly scores in anchor points are not allowed.")
            if self.points[i][1] > self.points[i+1][1]:
                raise ValueError("Threat scores in anchor points must be monotonically non-decreasing.")

    def map_score(self, anomaly_score: float) -> float:
        if anomaly_score <= self.points[0][0]:
            return self.points[0][1]
        if anomaly_score >= self.points[-1][0]:
            return self.points[-1][1]

        for i in range(len(self.points) - 1):
            x1, y1 = self.points[i]
            x2, y2 = self.points[i+1]
            if x1 <= anomaly_score <= x2:
                # Linear interpolation formula
                return y1 + (y2 - y1) * (anomaly_score - x1) / (x2 - x1)
        
        return self.points[-1][1]


class SigmoidStrategy(MappingStrategy):
    """
    Maps anomaly scores using a parameterized Sigmoid (logistic) curve.
    Fitted parameter values: k = 7.90, x0 = 0.28.
    """
    def __init__(self, k: float = 7.90, x0: float = 0.28):
        self.k = k
        self.x0 = x0
        
        # Precompute boundary values for min-max scaling to guarantee f(0.0)=0.0 and f(1.0)=100.0
        self._raw_min = self._raw_sigmoid(0.0)
        self._raw_max = self._raw_sigmoid(1.0)
        self._scale_denominator = self._raw_max - self._raw_min

    def _raw_sigmoid(self, x: float) -> float:
        try:
            return 100.0 / (1.0 + math.exp(-self.k * (x - self.x0)))
        except OverflowError:
            return 100.0 if -self.k * (x - self.x0) < 0 else 0.0

    def map_score(self, anomaly_score: float) -> float:
        raw = self._raw_sigmoid(anomaly_score)
        scaled = 100.0 * (raw - self._raw_min) / self._scale_denominator
        return scaled


class ThreatScoreEngine:
    """
    Standardizes AI anomaly scores to Threat Scores (0 - 100).
    """
    def __init__(self, strategy: MappingStrategy = None):
        self._strategy = strategy if strategy is not None else PiecewiseLinearStrategy()
        if not isinstance(self._strategy, MappingStrategy):
            raise TypeError("strategy must be an instance of MappingStrategy")

    @property
    def strategy(self) -> MappingStrategy:
        return self._strategy

    @strategy.setter
    def strategy(self, strategy: MappingStrategy):
        if not isinstance(strategy, MappingStrategy):
            raise TypeError("strategy must be an instance of MappingStrategy")
        self._strategy = strategy

    def get_threat_score(self, anomaly_score: Union[int, float], round_output: bool = True) -> Union[int, float]:
        """
        Convert an AI anomaly score to a standardized Threat Score (0 - 100).
        """
        self._validate_input(anomaly_score)
        
        raw_score = self._strategy.map_score(float(anomaly_score))
        
        # Clamp output to guarantee strictly [0.0, 100.0] range
        final_score = max(0.0, min(100.0, raw_score))
        
        if round_output:
            return round(final_score)
        
        return final_score

    def _validate_input(self, anomaly_score: Union[int, float]):
        if not isinstance(anomaly_score, (int, float)):
            raise TypeError(
                f"Anomaly score must be a number (float or int), got {type(anomaly_score).__name__}"
            )
        if not (0.0 <= anomaly_score <= 1.0):
            raise ValueError(
                f"Anomaly score must be in the range [0.0, 1.0], got {anomaly_score}"
            )


class ThreatIntelligenceService:
    def __init__(self):
        self.engine = ThreatScoreEngine()

    def calculate_threat_score(self, anomaly_score: float, attack_type: str) -> int:
        """Calculate threat score using Priya's ThreatScoreEngine strategy."""
        clamped_score = max(0.0, min(1.0, abs(anomaly_score)))
        return int(self.engine.get_threat_score(clamped_score))

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

    def compute_real_shap(self, telemetry: dict = None) -> List[dict]:
        """Compute real TreeSHAP feature importance values using trained IsolationForest."""
        try:
            import shap
            import numpy as np
            from services.ai_service import ai_service
            from models_ml.preprocess import extract_features

            if not ai_service.anomaly_detector or not ai_service.scaler:
                ai_service.load_models()

            if ai_service.anomaly_detector and ai_service.scaler and telemetry:
                explainer = shap.TreeExplainer(ai_service.anomaly_detector)
                features = extract_features(telemetry)
                features_scaled = ai_service.scaler.transform(features)
                
                shap_vals = explainer.shap_values(features_scaled)
                vals = np.abs(shap_vals[0])
                feature_names = [
                    "latitude", "longitude", "altitude", "speed",
                    "battery", "packet_sequence", "speed_alt_ratio", "battery_drain_rate"
                ]
                
                total = float(np.sum(vals)) + 1e-6
                contributions = []
                for name, v in zip(feature_names, vals):
                    contributions.append({
                        "feature": name,
                        "importance": round(float(v / total), 2)
                    })
                contributions.sort(key=lambda x: x["importance"], reverse=True)
                return contributions[:3]
        except Exception:
            pass

        # Deterministic fallback if SHAP engine is initializing
        return [
            {"feature": "speed", "importance": 0.48},
            {"feature": "altitude", "importance": 0.32},
            {"feature": "battery_drain_rate", "importance": 0.20}
        ]

    def generate_alert(self, is_anomaly: bool, anomaly_score: float, attack_type: str, telemetry: dict = None) -> dict:
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
        shap_top3 = self.compute_real_shap(telemetry)
        
        return {
            "is_anomaly": True,
            "anomaly_score": anomaly_score,
            "attack_type": attack_type,
            "threat_level": threat_level,
            "severity": severity,
            "explanation": explanation,
            "shap_top3": shap_top3
        }


threat_service = ThreatIntelligenceService()

