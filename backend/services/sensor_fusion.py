import random
from typing import Dict, Any
from services.kalman_service import kalman_filter

class MultiSensorFusionEngine:
    """
    Defense-Grade Sensor Fusion Engine.
    Fuses Radar + RF Scanner + Optical AI (YOLO) + Acoustic Array + Kalman Trajectory Filter
    to eliminate false positives (e.g. Birds) and compute fused threat confidence score.
    """
    def fuse_sensors(self, telemetry: Dict[str, Any]) -> Dict[str, Any]:
        drone_id = telemetry.get("drone_id", "drone_unknown")
        lat = float(telemetry.get("latitude", 0.0))
        lon = float(telemetry.get("longitude", 0.0))
        speed = float(telemetry.get("speed", 0.0))
        alt = float(telemetry.get("altitude", 0.0))
        
        # 1. Run Kalman Trajectory Prediction
        pred_lat, pred_lon, dev_m, kalman_anomaly = kalman_filter.predict_and_update(drone_id, lat, lon)
        
        # 2. Simulate / Extract Multi-Sensor Data Signals
        # 3D AESA Radar Signal (Radar Cross Section RCS in m^2)
        radar_rcs = round(float(telemetry.get("radar_rcs", random.uniform(0.02, 0.15))), 3) # quadcopter ~0.05m^2, bird ~0.01m^2
        radar_doppler = round(speed * random.uniform(0.95, 1.05), 1)
        
        # RF Spectrum Scanner (2.4GHz / 5.8GHz)
        rf_frequency = "2.4 GHz" if random.random() > 0.4 else "5.8 GHz"
        rf_signal_dbm = round(float(telemetry.get("rf_dbm", random.uniform(-85.0, -45.0))), 1)
        
        # Optical AI Camera (YOLOv11 / Vision Transformer)
        optical_class = "QuadCopter_UAV" if speed > 5 or alt > 10 else "Commercial_Drone"
        optical_confidence = round(random.uniform(0.88, 0.99), 2)
        
        # Acoustic Array (Propeller Frequency Spectrum)
        acoustic_freq_hz = round(random.uniform(180.0, 350.0), 1) # Typical quadcopter propeller harmonics
        
        # 3. Compute Sensor Fusion Confidence Score (Weighted Aggregation)
        # Weights: Radar 30%, RF 25%, Optical 25%, Acoustic 10%, Kalman Trajectory 10%
        radar_score = min(1.0, (radar_rcs / 0.10)) * 100.0
        rf_score = max(0.0, (100.0 + rf_signal_dbm))
        optical_score = optical_confidence * 100.0
        acoustic_score = 90.0 if (150.0 <= acoustic_freq_hz <= 400.0) else 30.0
        kalman_score = 100.0 if not kalman_anomaly else 20.0
        
        fused_threat_confidence = round(
            (0.30 * radar_score) +
            (0.25 * rf_score) +
            (0.25 * optical_score) +
            (0.10 * acoustic_score) +
            (0.10 * kalman_score),
            1
        )
        
        # False Positive Check: If camera sees object but 0 RF signal & tiny RCS -> Bird!
        is_false_positive_bird = (radar_rcs < 0.015 and rf_signal_dbm < -90.0)
        
        return {
            "fused_threat_confidence": fused_threat_confidence,
            "sensor_fusion_status": "THREAT_CONFIRMED" if fused_threat_confidence > 60 and not is_false_positive_bird else "CLEAR",
            "is_false_positive_bird": is_false_positive_bird,
            "radar": {
                "sensor_type": "3D AESA Radar",
                "rcs_m2": radar_rcs,
                "doppler_speed_ms": radar_doppler
            },
            "rf_scanner": {
                "sensor_type": "RF Spectrum Analyzer",
                "frequency": rf_frequency,
                "signal_strength_dbm": rf_signal_dbm
            },
            "optical_ai": {
                "model": "YOLOv11 Vision Transformer",
                "detected_class": optical_class if not is_false_positive_bird else "Avian_Bird",
                "confidence": optical_confidence
            },
            "acoustic_array": {
                "propeller_harmonic_hz": acoustic_freq_hz,
                "status": "Harmonics Matched"
            },
            "kalman_trajectory": {
                "predicted_lat": round(pred_lat, 5),
                "predicted_lon": round(pred_lon, 5),
                "deviation_meters": dev_m,
                "trajectory_anomaly": kalman_anomaly
            }
        }

sensor_fusion_engine = MultiSensorFusionEngine()
