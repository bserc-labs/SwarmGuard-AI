import time

import numpy as np
import shap

from models_ml.dataset_loader import DatasetLoader
from models_ml.preprocess import FeatureEngineer
from utils.logger import logger


class ExplainabilityEngine:
    def __init__(self, model, scaler, metadata):
        self.model = model
        self.scaler = scaler
        self.metadata = metadata
        self.explainer = None
        self.explainer_type = "None"
        
        # Feature names must match the model's training columns, not whatever
        # config currently says, or the SHAP values get labelled with the wrong
        # feature names -- plausible output, wrong attribution.
        engineer = FeatureEngineer(feature_columns=(metadata or {}).get("feature_list"))
        self.feature_names = engineer.get_feature_columns()
        self.feature_mapping = engineer.get_feature_mapping()
        
        self._initialize_explainer()
        
    def _initialize_explainer(self):
        """Initializes and caches the appropriate SHAP Explainer for the loaded model."""
        t0 = time.perf_counter()
        
        try:
            # 1. Try TreeExplainer directly (IsolationForest)
            self.explainer = shap.TreeExplainer(self.model)
            self.explainer_type = "TreeExplainer"
            logger.info("Successfully initialized SHAP TreeExplainer.")
        except Exception as e_tree:
            logger.warning(f"TreeExplainer failed or unsupported: {e_tree}. Attempting KernelExplainer fallback.")
            try:
                # 2. Fallback to KernelExplainer using a small background dataset
                loader = DatasetLoader()
                df = loader.load_and_clean()
                engineer = FeatureEngineer()
                df_features = engineer.transform(df)
                # Drop rows with NaN (due to rolling windows)
                df_features = df_features.dropna(subset=self.feature_names)
                X_background = self.scaler.transform(df_features[self.feature_names].values[:100]) # 100 samples
                
                # Predict function for KernelExplainer
                predict_fn = lambda x: self.model.decision_function(x) if hasattr(self.model, 'decision_function') else self.model.predict(x)
                
                self.explainer = shap.KernelExplainer(predict_fn, X_background)
                self.explainer_type = "KernelExplainer"
                logger.info("Successfully initialized SHAP KernelExplainer.")
            except Exception as e_kernel:
                logger.error(f"KernelExplainer fallback failed: {e_kernel}. Explainability Engine disabled.")
                self.explainer = None
                
        t_init = time.perf_counter() - t0
        logger.info(f"SHAP explainer initialization took {t_init*1000:.2f} ms")

    def _to_2d(self, shap_values) -> np.ndarray:
        """Normalise SHAP output to (n_samples, n_features).

        The shape depends on the model, and getting this wrong is silent
        rather than loud -- you get numbers, just the wrong ones:

        * IsolationForest / single-output -> already (n_samples, n_features).
        * Binary classifier under shap >= 0.45 -> a 3D ndarray
          (n_samples, n_features, n_classes). The last axis is selected down to
          the positive class, because attributions for "this is normal" are the
          negation of what an analyst asked for.
        * Older shap or multi-output -> a list, one array per class.
        """
        if isinstance(shap_values, list):
            # Positive class when binary, else the single output present.
            return np.asarray(shap_values[-1] if len(shap_values) > 1 else shap_values[0])

        arr = np.asarray(shap_values)
        if arr.ndim == 3:
            return arr[:, :, -1]
        return arr

    def explain(self, scaled_features: np.ndarray) -> dict:
        """
        Generates SHAP explanations for a given scaled feature vector.
        Supports both single prediction and batch predictions.
        """
        if self.explainer is None:
            return {"error": "Explainability Engine is disabled or model unsupported."}
            
        t0 = time.perf_counter()
        
        try:
            # Generate SHAP values
            shap_values = self.explainer.shap_values(scaled_features)
            shap_values = self._to_2d(shap_values)

            # If batch request, process each sample
            explanations = []
            for i in range(len(scaled_features)):
                sample_shap = shap_values[i]
                
                # Rank features by absolute contribution magnitude
                feature_contributions = []
                for j, feature_name in enumerate(self.feature_names):
                    contribution = float(sample_shap[j])
                    feature_contributions.append({
                        "feature": feature_name,
                        "raw_sources": self.feature_mapping.get(feature_name, []),
                        "shap_value": contribution,
                        "magnitude": abs(contribution)
                    })
                    
                # Sort descending by magnitude
                feature_contributions.sort(key=lambda x: x["magnitude"], reverse=True)
                
                # Calculate explanation confidence (heuristic: ratio of top 3 features to total magnitude)
                total_magnitude = sum(fc["magnitude"] for fc in feature_contributions)
                top_3_magnitude = sum(fc["magnitude"] for fc in feature_contributions[:3])
                confidence = round((top_3_magnitude / total_magnitude) * 100, 2) if total_magnitude > 0 else 0.0
                
                explanations.append({
                    "ranked_features": feature_contributions,
                    "metadata": {
                        "explainer_type": self.explainer_type,
                        "shap_version": shap.__version__,
                        "explanation_confidence_percent": confidence,
                        "generation_time_ms": 0 # Filled below
                    }
                })
                
            t_exp = time.perf_counter() - t0
            
            for exp in explanations:
                exp["metadata"]["generation_time_ms"] = round(t_exp * 1000 / len(scaled_features), 2)
                
            return {"explanations": explanations}
            
        except Exception as e:
            logger.error(f"Failed to generate SHAP values: {e}")
            return {"error": str(e)}
