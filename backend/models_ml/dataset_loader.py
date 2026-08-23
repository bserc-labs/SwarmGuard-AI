import os
import pandas as pd
from utils.logger import logger
from config import get_settings

settings = get_settings()

class DatasetLoader:
    def __init__(self, filepath: str = None):
        # We allow overriding filepath, otherwise fall back to config
        self.filepath = filepath or os.path.normpath(os.path.join(
            os.path.dirname(__file__), "..", settings.DATASET_PATH
        ))
        
    def load_and_clean(self) -> pd.DataFrame:
        """Loads telemetry dataset, verifies schema, handles missing values and duplicates."""
        logger.info(f"Loading dataset from: {self.filepath}")
        if not os.path.exists(self.filepath):
            raise FileNotFoundError(f"Dataset not found at {self.filepath}")
            
        df = pd.read_csv(self.filepath)
        initial_count = len(df)
        
        # 1. Schema Validation (ensure core columns exist)
        required_columns = [
            "drone_id", "packet_sequence", "latitude", "longitude", 
            "altitude", "speed", "heading", "battery", "flight_mode",
            "armed_status", "satellites"
        ]
        missing = [col for col in required_columns if col not in df.columns]
        if missing:
            raise ValueError(f"Dataset is missing required columns: {missing}")
            
        # 2. Handle missing values
        df = df.dropna(subset=required_columns)
        
        # 3. Remove exact duplicates
        df = df.drop_duplicates()
        
        # Sort chronologically per drone
        df = df.sort_values(by=["drone_id", "packet_sequence"]).reset_index(drop=True)
        
        final_count = len(df)
        logger.info(f"Dataset loaded. Dropped {initial_count - final_count} invalid/duplicate records. Total: {final_count}")
        return df
