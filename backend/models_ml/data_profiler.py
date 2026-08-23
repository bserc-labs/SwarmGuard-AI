import pandas as pd
import json
import os
from datetime import datetime
from config import get_settings
from models_ml.dataset_loader import DatasetLoader
from utils.logger import logger

settings = get_settings()

class DataProfiler:
    def __init__(self):
        self.output_dir = os.path.normpath(os.path.join(
            os.path.dirname(__file__), "..", settings.MODELS_DIR
        ))
        os.makedirs(self.output_dir, exist_ok=True)
        
    def profile(self):
        logger.info("Running Data Quality Profiler...")
        
        loader = DatasetLoader()
        df = loader.load_and_clean()
        
        # 1. Missing Values
        missing_values = df.isnull().sum().to_dict()
        
        # 2. Duplicate Rows
        duplicate_count = int(df.duplicated().sum())
        
        # 3. Class Distribution
        class_distribution = {}
        if "label" in df.columns:
            class_distribution = df["label"].value_counts().to_dict()
            
        # 4. Feature Distributions & Outliers (using 1.5 IQR rule for simple numeric outliers)
        feature_dists = {}
        outliers = {}
        numeric_cols = df.select_dtypes(include=['float64', 'int64']).columns
        
        for col in numeric_cols:
            if col in ["drone_id", "packet_sequence", "label"]:
                continue
                
            desc = df[col].describe()
            feature_dists[col] = {
                "mean": float(desc["mean"]),
                "std": float(desc["std"]),
                "min": float(desc["min"]),
                "25%": float(desc["25%"]),
                "50%": float(desc["50%"]),
                "75%": float(desc["75%"]),
                "max": float(desc["max"])
            }
            
            # Outliers
            Q1 = desc["25%"]
            Q3 = desc["75%"]
            IQR = Q3 - Q1
            lower_bound = Q1 - 1.5 * IQR
            upper_bound = Q3 + 1.5 * IQR
            outlier_count = int(((df[col] < lower_bound) | (df[col] > upper_bound)).sum())
            outliers[col] = outlier_count

        # 5. Correlation Matrix
        corr_matrix = df[numeric_cols].corr().fillna(0).to_dict()
        
        report = {
            "timestamp": datetime.utcnow().isoformat(),
            "dataset_source": settings.DATASET_PATH,
            "dataset_summary": {
                "total_rows": len(df),
                "total_columns": len(df.columns)
            },
            "missing_values": missing_values,
            "duplicate_rows": duplicate_count,
            "class_distribution": class_distribution,
            "feature_distributions": feature_dists,
            "outliers": outliers,
            "correlation_matrix": corr_matrix
        }
        
        output_path = os.path.join(self.output_dir, "data_quality_report.json")
        with open(output_path, "w") as f:
            json.dump(report, f, indent=4)
            
        logger.info(f"Data Quality Report generated at {output_path}")
        return report

if __name__ == "__main__":
    profiler = DataProfiler()
    profiler.profile()
