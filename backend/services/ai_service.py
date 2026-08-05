import os
import joblib
import numpy as np
from models_ml.preprocess import extract_features
from typing import Dict, Any, Tuple
from utils.logger import logger

class AIInferenceService:
    def __init__(self):
        self.scaler = None
        self.anomaly_detector = None
        self.attack_classifier = None
        self.models_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "models_ml"))

    def load_models(self):
        """Load trained scikit-learn models and scaler from disk."""
        scaler_path = os.path.join(self.models_dir, "scaler.joblib")
        iso_path = os.path.join(self.models_dir, "isolation_forest.joblib")
        clf_path = os.path.join(self.models_dir, "attack_classifier.joblib")

        if os.path.exists(scaler_path) and os.path.exists(iso_path) and os.path.exists(clf_path):
            try:
                self.scaler = joblib.load(scaler_path)
                self.anomaly_detector = joblib.load(iso_path)
                self.attack_classifier = joblib.load(clf_path)
                logger.info("✅ Trained ML models (IsolationForest, RandomForest, Scaler) loaded successfully.")
            except Exception as e:
                logger.error(f"❌ Error loading ML models: {e}")
        else:
            logger.warning("⚠️ Trained ML models not found on disk. Run python backend/scripts/train_model.py first.")

    def analyze_telemetry(self, telemetry: Dict[str, Any]) -> Tuple[bool, float, str]:
        """
        Runs real ML inference on telemetry packet.
        Returns: (is_anomaly, anomaly_score, predicted_attack_type)
        """
        if not self.anomaly_detector or not self.attack_classifier or not self.scaler:
            self.load_models()

        if not self.anomaly_detector or not self.scaler:
            # Fallback if models failed to load
            return False, 0.0, None

        # Preprocess & scale features (8 features)
        features = extract_features(telemetry)
        features_scaled = self.scaler.transform(features)

        # Predict anomaly using Isolation Forest (-1 = anomaly, 1 = normal)
        anomaly_prediction = self.anomaly_detector.predict(features_scaled)[0]
        is_anomaly = bool(anomaly_prediction == -1)

        # Decision score: negative means anomalous, positive means normal
        # Map decision score to normalized anomaly score in [0.0, 1.0]
        raw_score = float(self.anomaly_detector.decision_function(features_scaled)[0])
        # Sigmoidal/clamped normalization for score: raw_score typically spans [-0.3, +0.3]
        anomaly_score = max(0.0, min(1.0, float(0.5 - (raw_score * 2.0))))

        predicted_attack_type = None
        if is_anomaly:
            predicted_attack_type = str(self.attack_classifier.predict(features_scaled)[0])

        return is_anomaly, anomaly_score, predicted_attack_type

ai_service = AIInferenceService()

