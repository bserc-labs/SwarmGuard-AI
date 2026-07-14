import numpy as np
from typing import Dict, Any

def extract_features(telemetry: Dict[str, Any]) -> np.ndarray:
    """
    Extract features from telemetry data for inference.
    In a real scenario, this would handle normalization, scaling,
    and sequence aggregation.
    """
    # Simple placeholder: extract numerical values
    features = [
        float(telemetry.get('latitude', 0.0)),
        float(telemetry.get('longitude', 0.0)),
        float(telemetry.get('altitude', 0.0)),
        float(telemetry.get('speed', 0.0)),
        float(telemetry.get('battery', 0.0)),
        float(telemetry.get('packet_sequence', 0.0))
    ]
    return np.array([features])
