from models_ml.sample_model import DummyIsolationForest, DummyClassifier
from models_ml.preprocess import extract_features
from typing import Dict, Any, Tuple

class AIInferenceService:
    def __init__(self):
        self.anomaly_detector = None
        self.attack_classifier = None

    def load_models(self):
        """Model loading abstraction"""
        # In a real scenario, this would load models from disk or cloud
        self.anomaly_detector = DummyIsolationForest().load()
        self.attack_classifier = DummyClassifier().load()

    def analyze_telemetry(self, telemetry: Dict[str, Any]) -> Tuple[bool, float, str]:
        """
        Sample telemetry inference.
        Returns: (is_anomaly, anomaly_score, predicted_attack_type)
        """
        if not self.anomaly_detector or not self.attack_classifier:
            self.load_models()

        # Preprocess data
        features = extract_features(telemetry)

        # Predict anomaly
        # Isolation forest returns 1 for normal, -1 for anomaly
        anomaly_prediction = self.anomaly_detector.predict(features)[0]
        is_anomaly = bool(anomaly_prediction == -1)

        # Get anomaly score (convert to a positive score for easier interpretation)
        # Assuming score from mock is between -0.5 and +0.5, we normalize it to 0.0 - 1.0
        raw_score = self.anomaly_detector.decision_function(features)[0]
        # Inverting so higher = more anomalous
        anomaly_score = float((0.5 - raw_score)) 
        
        predicted_attack_type = None
        if is_anomaly:
            predicted_attack_type = str(self.attack_classifier.predict(features)[0])

        return is_anomaly, anomaly_score, predicted_attack_type

ai_service = AIInferenceService()
