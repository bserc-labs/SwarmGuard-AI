from pathlib import Path

# Root of model_train
MODEL_ROOT = Path(__file__).resolve().parent

# Directories
DATASET_DIR = MODEL_ROOT / "dataset"
REPORT_DIR = MODEL_ROOT / "reports"
MODELS_DIR = MODEL_ROOT / "models"
FEATURE_DIR = MODEL_ROOT / "feature_engineering"

# Files
RAW_DATASET = DATASET_DIR / "raw_dataset.csv"
FEATURE_DATASET = DATASET_DIR / "feature_dataset.csv"