from typing import Any
import time
import pandas as pd
from config import get_settings
from utils.logger import logger
from models_ml.registry import model_registry
from models_ml.preprocess import FeatureEngineer
import json

settings = get_settings()

class AIInferenceService:
    def __init__(self):
        self.model = None
        self.scaler = None
        self.metadata = None
        self.engineer = FeatureEngineer()
        
    def _lazy_load_model(self):
        if not self.model:
            try:
                t0 = time.perf_counter()
                self.model, self.scaler, self.metadata = model_registry.load_model(settings.MODEL_VERSION)

                # Rebind the feature engineer to the columns this model was
                # actually trained on, in the order the scaler expects.
                trained_features = (self.metadata or {}).get("feature_list")
                if trained_features:
                    self.engineer = FeatureEngineer(feature_columns=trained_features)

                t_load = time.perf_counter() - t0
                logger.info(json.dumps({
                    "event": "model_loaded",
                    "version": settings.MODEL_VERSION,
                    "algorithm": self.metadata.get("algorithm", "unknown"),
                    "latency_ms": round(t_load * 1000, 2)
                }))
            except Exception as e:
                logger.error(json.dumps({
                    "event": "model_load_failure",
                    "version": settings.MODEL_VERSION,
                    "error": str(e)
                }))
                
    def _score(self, scaled_features) -> tuple[bool, float]:
        """Return (is_anomaly, score_0_to_100) for one scaled feature row.

        Two model families reach this code and they disagree about what their
        output means, so the branch is on capability rather than on a version
        string:

        * **Supervised classifier** (v2, RandomForest on real flight data).
          `predict_proba` gives P(attack) directly, which is already a
          calibrated-ish 0-1 confidence -- scale it and use it.
        * **Unsupervised outlier detector** (v1, IsolationForest). `predict`
          returns -1 for outliers and `decision_function` returns a signed
          margin around zero, which has to be squashed into 0-100 by hand.

        Reading an IsolationForest's -1 out of a classifier (or vice versa)
        silently inverts the verdict, so neither path is a fallback for the
        other.
        """
        if hasattr(self.model, "predict_proba"):
            proba = self.model.predict_proba(scaled_features)[0]
            # Column order follows model.classes_; positive class is label 1.
            classes = list(getattr(self.model, "classes_", [0, 1]))
            positive_idx = classes.index(1) if 1 in classes else len(classes) - 1
            p_attack = float(proba[positive_idx])
            return p_attack >= 0.5, p_attack * 100.0

        pred_raw = self.model.predict(scaled_features)[0]
        is_anomaly = bool(pred_raw == -1)

        if hasattr(self.model, "decision_function"):
            decision = float(self.model.decision_function(scaled_features)[0])
            return is_anomaly, 50.0 - (decision * 166.67)

        # Fallback if model doesn't support decision_function (e.g., novelty=False LOF)
        return is_anomaly, 100.0 if is_anomaly else 0.0

    def _compute_threat_level(self, anomaly_score: float) -> str:
        """Maps an anomaly score (0-100) to a threat level string using config thresholds."""
        if anomaly_score <= settings.THREAT_SCORE_LOW:
            return "LOW"
        elif anomaly_score <= settings.THREAT_SCORE_MED:
            return "MEDIUM"
        elif anomaly_score <= settings.THREAT_SCORE_HIGH:
            return "HIGH"
        else:
            return "CRITICAL"

    def predict(self, telemetry_history: list[dict[str, Any]]) -> dict[str, Any]:
        self._lazy_load_model()
        t0 = time.perf_counter()
        
        if not self.model or not self.scaler:
            return {
                "is_anomaly": False, 
                "anomaly_score": 0.0, 
                "threat_level": "UNKNOWN",
                "error": "Model not loaded"
            }
            
        try:
            df = pd.DataFrame(telemetry_history)
            df_features = self.engineer.transform(df)
            feature_cols = self.engineer.get_feature_columns()
            
            latest_features = df_features[feature_cols].iloc[[-1]].values
            
            if pd.isna(latest_features).any():
                logger.warning(json.dumps({"event": "invalid_feature_vector", "reason": "NaNs in features"}))
                return {
                    "is_anomaly": False, 
                    "anomaly_score": 0.0, 
                    "threat_level": "LOW",
                    "status": "warmup"
                }
                
            scaled_features = self.scaler.transform(latest_features)

            is_anomaly, score = self._score(scaled_features)
            anomaly_score = max(0.0, min(100.0, score))
            threat_level = self._compute_threat_level(anomaly_score)
            
            t_infer = time.perf_counter() - t0
            logger.info(json.dumps({
                "event": "prediction",
                "is_anomaly": is_anomaly,
                "score": round(anomaly_score, 2),
                "threat_level": threat_level,
                "latency_ms": round(t_infer * 1000, 2)
            }))
            
            return {
                "is_anomaly": is_anomaly,
                "anomaly_score": round(anomaly_score, 2),
                "threat_level": threat_level,
                "model_version": settings.MODEL_VERSION
            }
            
        except Exception as e:
            logger.error(json.dumps({"event": "inference_failure", "error": str(e)}))
            return {
                "is_anomaly": False, 
                "anomaly_score": 0.0, 
                "threat_level": "UNKNOWN",
                "error": str(e)
            }

ai_service = AIInferenceService()
