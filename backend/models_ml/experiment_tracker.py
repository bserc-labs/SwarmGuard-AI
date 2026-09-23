import json
import os
import subprocess
from datetime import UTC, datetime

from config import get_settings
from utils.logger import logger

settings = get_settings()

def get_git_commit():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"]).decode("utf-8").strip()
    except Exception:
        return "unknown"

class ExperimentTracker:
    def __init__(self):
        self.experiments_file = os.path.normpath(os.path.join(
            os.path.dirname(__file__), "..", settings.MODELS_DIR, "experiments.json"
        ))
        if not os.path.exists(self.experiments_file):
            os.makedirs(os.path.dirname(self.experiments_file), exist_ok=True)
            with open(self.experiments_file, "w") as f:
                json.dump([], f)

    def record_experiment(
        self, 
        dataset_source: str, 
        feature_list: list[str],
        contamination: float,
        random_seed: int,
        evaluation_metrics: dict,
        model_version: str,
        execution_time_seconds: float
    ):
        experiment_id = f"EXP-{datetime.now(UTC).strftime('%Y%md%H%M%S')}"
        
        record = {
            "experiment_id": experiment_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "git_commit": get_git_commit(),
            "execution_time_seconds": execution_time_seconds,
            "dataset_source": dataset_source,
            "feature_list": feature_list,
            "hyperparameters": {
                "contamination": contamination,
                "random_seed": random_seed
            },
            "evaluation_metrics": evaluation_metrics,
            "generated_model_version": model_version,
            "hardware": {
                "cpu_count": os.cpu_count()
            }
        }
        
        with open(self.experiments_file) as f:
            try:
                history = json.load(f)
            except json.JSONDecodeError:
                history = []
                
        history.append(record)
        with open(self.experiments_file, "w") as f:
            json.dump(history, f, indent=4)
            
        logger.info(f"Experiment {experiment_id} successfully recorded.")
        return experiment_id

experiment_tracker = ExperimentTracker()
