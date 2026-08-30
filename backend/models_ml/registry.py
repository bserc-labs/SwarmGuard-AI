import hashlib
import json
import os
import sys
from typing import Any

import joblib
import sklearn

from config import get_settings
from utils.logger import logger

settings = get_settings()

def get_file_hash(filepath: str) -> str:
    """Returns SHA256 hash of a file."""
    if not os.path.exists(filepath):
        return ""
    hasher = hashlib.sha256()
    with open(filepath, 'rb') as f:
        buf = f.read()
        hasher.update(buf)
    return hasher.hexdigest()

class ModelRegistry:
    def __init__(self):
        self.base_dir = os.path.normpath(os.path.join(
            os.path.dirname(__file__), "..", settings.MODELS_DIR
        ))
        os.makedirs(self.base_dir, exist_ok=True)

    def _get_version_dir(self, version: str) -> str:
        v_dir = os.path.join(self.base_dir, version)
        os.makedirs(v_dir, exist_ok=True)
        return v_dir

    def save_model(self, version: str, model: Any, scaler: Any, metadata: dict, training_config: dict, evaluation: dict):
        v_dir = self._get_version_dir(version)
        
        # Paths
        model_path = os.path.join(v_dir, "model.joblib")
        scaler_path = os.path.join(v_dir, "scaler.joblib")
        
        # Save Scikit-Learn artifacts
        joblib.dump(model, model_path)
        joblib.dump(scaler, scaler_path)
        
        # Enhance metadata
        metadata["python_version"] = sys.version.split(" ")[0]
        metadata["sklearn_version"] = sklearn.__version__
        metadata["model_hash_sha256"] = get_file_hash(model_path)
        metadata["scaler_hash_sha256"] = get_file_hash(scaler_path)
        metadata["model_size_bytes"] = os.path.getsize(model_path)
        metadata["feature_count"] = len(metadata.get("feature_list", []))
        
        # Save JSON metadata
        with open(os.path.join(v_dir, "metadata.json"), "w") as f:
            json.dump(metadata, f, indent=4)
            
        with open(os.path.join(v_dir, "training_config.json"), "w") as f:
            json.dump(training_config, f, indent=4)
            
        with open(os.path.join(v_dir, "evaluation.json"), "w") as f:
            json.dump(evaluation, f, indent=4)
            
        logger.info(f"Model {version} successfully saved to registry at {v_dir}")

    def _read_json(self, version: str, filename: str) -> dict:
        path = os.path.join(self._get_version_dir(version), filename)
        if not os.path.exists(path):
            return {}
        try:
            with open(path) as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(f"Could not read {filename} for model {version}: {exc}")
            return {}

    def load_evaluation(self, version: str) -> dict:
        """Validation metrics recorded when this version was trained."""
        return self._read_json(version, "evaluation.json")

    def load_investigations(self, version: str) -> dict:
        """What was tried against this model's shortcomings, and what it measured.

        Kept beside the artifacts rather than in a document, so the console can
        state why a tier is disabled instead of only that it is. Absent for a
        version nobody has investigated, which reads as "no record" rather than
        "nothing was wrong".
        """
        return self._read_json(version, "investigations.json")

    def describe(self, version: str) -> dict:
        """Report on a version without deserialising the model.

        `load_model` joblib-loads a 7.8 MB forest, which is the wrong cost for a
        status endpoint that only needs to answer "is the artifact present, and
        what were its numbers". Metadata and evaluation come from their JSON
        files; presence is a stat().
        """
        v_dir = self._get_version_dir(version)
        model_path = os.path.join(v_dir, "model.joblib")
        scaler_path = os.path.join(v_dir, "scaler.joblib")
        present = os.path.exists(model_path) and os.path.exists(scaler_path)

        return {
            "version": version,
            "artifact_status": "present" if present else "missing",
            "metadata": self._read_json(version, "metadata.json") if present else {},
            "evaluation": self.load_evaluation(version) if present else {},
            "investigations": self.load_investigations(version) if present else {},
        }

    def load_model(self, version: str) -> tuple[Any, Any, dict]:
        """Loads model, scaler, and metadata for inference."""
        v_dir = self._get_version_dir(version)
        
        model_path = os.path.join(v_dir, "model.joblib")
        scaler_path = os.path.join(v_dir, "scaler.joblib")
        metadata_path = os.path.join(v_dir, "metadata.json")
        
        if not (os.path.exists(model_path) and os.path.exists(scaler_path)):
            raise FileNotFoundError(f"Model artifacts not found for version {version}")
            
        model = joblib.load(model_path)
        scaler = joblib.load(scaler_path)
        
        metadata = {}
        if os.path.exists(metadata_path):
            with open(metadata_path) as f:
                metadata = json.load(f)
                
        return model, scaler, metadata

model_registry = ModelRegistry()
