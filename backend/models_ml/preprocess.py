import numpy as np
from typing import Dict, Any

def extract_features(telemetry: Dict[str, Any]) -> np.ndarray:
    """
    Extract 8 features from telemetry data for model inference:
    [latitude, longitude, altitude, speed, battery, packet_sequence, speed_alt_ratio, battery_drain_rate]
    """
    lat = float(telemetry.get('latitude', 0.0))
    lon = float(telemetry.get('longitude', 0.0))
    alt = float(telemetry.get('altitude', 0.0))
    speed = float(telemetry.get('speed', 0.0))
    battery = float(telemetry.get('battery', 100.0))
    pkt_seq = float(telemetry.get('packet_sequence', 0.0))
    
    speed_alt_ratio = round(speed / (alt + 1.0), 4)
    battery_drain_rate = round(100.0 - battery, 2)

    features = [lat, lon, alt, speed, battery, pkt_seq, speed_alt_ratio, battery_drain_rate]
    return np.array([features])

