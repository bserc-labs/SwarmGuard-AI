import json
from datetime import datetime
from typing import Any, ClassVar

import pandas as pd

from config import get_settings
from models_ml.explainability import ExplainabilityEngine
from models_ml.preprocess import undefined_features
from services.ai_service import ai_service
from utils.logger import logger

settings = get_settings()

class AIExplanationService:
    def __init__(self):
        self.engine = None
        self.last_model_version = None
        
    def _lazy_load_engine(self):
        """Initializes the ExplainabilityEngine. Automatically reloads if AI inference model changes."""
        # Ensure ai_service has loaded its model
        ai_service._lazy_load_model()
        
        if ai_service.model is None or ai_service.scaler is None:
            raise RuntimeError("Underlying AI Inference Service failed to load model.")
            
        current_version = settings.MODEL_VERSION
        if self.engine is None or self.last_model_version != current_version:
            logger.info("Loading Explainability Engine...")
            self.engine = ExplainabilityEngine(ai_service.model, ai_service.scaler, ai_service.metadata)
            self.last_model_version = current_version
            
    def _generate_analyst_summary(self, ranked_features: list[dict]) -> dict[str, str]:
        """Converts raw SHAP feature rankings into a structured SOC analyst summary template."""
        if not ranked_features:
            return {
                "Primary Cause": "Unknown",
                "Secondary Cause": "None",
                "Supporting Indicators": "None",
                "Recommended Action": "Investigate raw telemetry logs manually."
            }
            
        # Map technical feature names to human-readable names. Covers both the
        # v1 synthetic family and the v2 deployable family, so switching
        # MODEL_VERSION does not leave the analyst summary printing raw column
        # names at an operator.
        human_names = {
            # v1 synthetic family
            "speed_variance": "Erratic Speed Changes",
            "gps_drift": "Abnormal GPS Drift (Spoofing Indicator)",
            "altitude_deviation": "Altitude Instability",
            "battery_discharge_rate": "Rapid Battery Drain",
            "heading_deviation": "Erratic Heading Changes",
            "flight_mode_transitions": "Frequent Flight Mode Switches",
            "satellite_variation": "GPS Signal Jamming/Loss",
            "velocity_consistency": "Inconsistent Velocity",
            # v2 deployable family
            "gps_speed_error_abs": "Reported Speed Contradicts GPS Track (Spoofing Indicator)",
            "gps_speed_error_ratio": "Relative GPS/Airframe Speed Mismatch (Spoofing Indicator)",
            "gps_acceleration": "Physically Implausible GPS Acceleration (Position Jump)",
            "vertical_speed": "Abnormal Climb/Descent Rate",
            "speed_change": "Abrupt Speed Change",
            "yaw_change": "Abrupt Heading Change",
            "yaw": "Heading",
            "altitude": "Altitude",
            "time_delta": "Irregular Telemetry Interval",
        }
        
        # Only consider features with positive absolute contribution > 0
        significant_features = [f for f in ranked_features if f["magnitude"] > 0]
        
        if len(significant_features) == 0:
            return {
                "Primary Cause": "Complex multi-variable interaction (No single dominant cause)",
                "Secondary Cause": "None",
                "Supporting Indicators": "None",
                "Recommended Action": "Review full telemetry payload for subtle deviations."
            }
            
        primary = human_names.get(significant_features[0]["feature"], significant_features[0]["feature"])
        secondary = human_names.get(significant_features[1]["feature"], significant_features[1]["feature"]) if len(significant_features) > 1 else "None"
        
        supporting = "None"
        if len(significant_features) > 2:
            supporting_list = [human_names.get(f["feature"], f["feature"]) for f in significant_features[2:5]]
            supporting = ", ".join(supporting_list)
            
        # Recommend action based on primary cause
        recommendation = "Investigate drone status immediately."
        if "GPS" in primary or "Satellite" in primary:
            recommendation = "Review GPS integrity and signal jamming before issuing commands. Consider switching to manual ATTI mode."
        elif "Battery" in primary:
            recommendation = "Command immediate Return-to-Launch (RTL) or emergency landing. Battery drain suggests physical payload interference."
        elif "Speed" in primary or "Altitude" in primary or "Heading" in primary:
            recommendation = "Check for adverse weather/wind conditions or autopilot malfunction."
            
        return {
            "Attack Type": self._classify_attack_type(significant_features),
            "Primary Cause": primary,
            "Secondary Cause": secondary,
            "Supporting Indicators": supporting,
            "Recommended Action": recommendation
        }

    # Feature -> attack family. Used to give an incident a short, filterable
    # label instead of storing a full sentence in `attack_type`, which is what
    # the dashboard groups and the operator scans.
    _ATTACK_FAMILIES: ClassVar[dict[str, str]] = {
        "gps_speed_error_abs": "GPS_SPOOFING",
        "gps_speed_error_ratio": "GPS_SPOOFING",
        "gps_acceleration": "GPS_SPOOFING",
        "gps_drift": "GPS_SPOOFING",
        "satellite_variation": "SIGNAL_JAMMING",
        "time_delta": "SIGNAL_JAMMING",
        "battery_discharge_rate": "POWER_ANOMALY",
        "vertical_speed": "FLIGHT_INSTABILITY",
        "altitude_deviation": "FLIGHT_INSTABILITY",
        "speed_change": "FLIGHT_INSTABILITY",
        "speed_variance": "FLIGHT_INSTABILITY",
        "velocity_consistency": "FLIGHT_INSTABILITY",
        "yaw_change": "FLIGHT_INSTABILITY",
        "heading_deviation": "FLIGHT_INSTABILITY",
        "flight_mode_transitions": "CONTROL_ANOMALY",
    }

    def _classify_attack_type(self, significant_features: list[dict]) -> str:
        """Derive a short attack label from the top-weighted SHAP features.

        Votes across the top three rather than trusting the single highest
        feature: on a genuine spoof, several GPS features light up together,
        and letting one marginally-larger unrelated feature name the incident
        produced labels that contradicted the explanation printed beneath them.
        """
        votes: dict[str, float] = {}
        for f in significant_features[:3]:
            family = self._ATTACK_FAMILIES.get(f["feature"])
            if family:
                votes[family] = votes.get(family, 0.0) + f["magnitude"]

        if not votes:
            return "UNCLASSIFIED_ANOMALY"
        return max(votes.items(), key=lambda kv: kv[1])[0]

    def _insufficient_data(self, nan_features: list[str]) -> dict[str, Any]:
        """Explicit refusal for a window whose feature vector is not fully defined.

        Carries the {"error": ...} key detection_pipeline and the router already
        check, a status the router maps to a client error, and the undefined
        columns so the caller can tell a short window from packets without
        usable timestamps.
        """
        return {
            "error": (
                "Insufficient data: the feature vector is undefined for "
                f"{', '.join(nan_features) or 'one or more features'}. Delta and rate "
                "features need more packets with distinct, increasing timestamps "
                "(`timestamp` on /ai/explain; `created_at` from the telemetry store) "
                "than this window provides."
            ),
            "status": "insufficient_data",
            "nan_features": nan_features,
        }

    def explain_prediction(self, telemetry_history: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Executes full inference and SHAP explainability pipeline.
        Returns prediction, SHAP values, and structured analyst summary.
        """
        try:
            self._lazy_load_engine()
        except Exception as e:
            return {"error": f"Explanation Service failed to initialize: {e}"}
            
        # 1. Get Inference Result
        inference_result = ai_service.predict(telemetry_history)
        if "error" in inference_result:
            return {"error": f"Inference failed: {inference_result['error']}"}

        # predict() reports an undefined feature vector as status "warmup", with
        # no "error" key -- so the check above sailed past it, and this method
        # went on to recompute the same NaN row and hand it to SHAP, which
        # treats NaN as "missing" and attributes anyway. That is how /ai/explain
        # returned a confident GPS_SPOOFING attribution for a window in which
        # none of the GPS features existed.
        if inference_result.get("status") == "warmup":
            return self._insufficient_data(inference_result.get("nan_features") or [])
            
        # 2. Reconstruct Scaled Features (since inference service doesn't expose them directly to avoid tight coupling)
        try:
            df = pd.DataFrame(telemetry_history)
            df_features = ai_service.engineer.transform(df)
            feature_cols = ai_service.engineer.get_feature_columns()
            latest_features = df_features[feature_cols].iloc[[-1]].values
            # Defensive re-check, not the primary guard: this row is recomputed
            # independently of predict(), and the two must never be allowed to
            # disagree about whether the window is defined.
            nan_features = undefined_features(feature_cols, latest_features)
            if nan_features:
                return self._insufficient_data(nan_features)
            scaled_features = ai_service.scaler.transform(latest_features)
        except Exception as e:
            logger.error(json.dumps({"event": "explain_feature_prep_failed", "error": str(e)}))
            return {"error": "Failed to prepare features for explanation."}

        # 3. Generate SHAP Explanation
        shap_response = self.engine.explain(scaled_features)
        if "error" in shap_response:
            return {"error": shap_response["error"]}
            
        explanation = shap_response["explanations"][0]
        
        # 4. Generate Analyst Summary
        summary = self._generate_analyst_summary(explanation["ranked_features"])
        
        # 5. Add Metadata
        explanation["metadata"]["model_version"] = settings.MODEL_VERSION
        explanation["metadata"]["feature_engineering_version"] = "v1.0"
        explanation["metadata"]["generation_timestamp"] = datetime.utcnow().isoformat()
        
        # Verify explanation stability (Confidence check)
        confidence = explanation["metadata"]["explanation_confidence_percent"]
        if confidence < 50.0:
            summary["Warning"] = "Explanation confidence is low. Anomaly is highly distributed across many minor features."
            
        return {
            "prediction": {
                "is_anomaly": inference_result["is_anomaly"],
                "anomaly_score": inference_result["anomaly_score"],
                "threat_level": inference_result["threat_level"]
            },
            "explanation": {
                "ranked_features": explanation["ranked_features"],
                "summary": summary,
                "metadata": explanation["metadata"]
            }
        }

explanation_service = AIExplanationService()
