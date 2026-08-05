import sys
import os

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from services.ai_service import ai_service
from services.threat_service import threat_service
from services.sensor_fusion import sensor_fusion_engine

def test_ai_service_model_loading():
    ai_service.load_models()
    assert ai_service.anomaly_detector is not None
    assert ai_service.attack_classifier is not None
    assert ai_service.scaler is not None

def test_normal_telemetry_inference():
    normal_telemetry = {
        "drone_id": "drone_test_1",
        "latitude": 34.0522,
        "longitude": -118.2437,
        "altitude": 100.0,
        "speed": 12.0,
        "battery": 85.0,
        "packet_sequence": 150
    }
    is_anomaly, anomaly_score, attack_type = ai_service.analyze_telemetry(normal_telemetry)
    assert isinstance(is_anomaly, bool)
    assert 0.0 <= anomaly_score <= 1.0

def test_anomaly_telemetry_inference():
    spoofed_telemetry = {
        "drone_id": "drone_test_2",
        "latitude": 34.4500,
        "longitude": -117.8000,
        "altitude": 350.0,
        "speed": 140.0,
        "battery": 60.0,
        "packet_sequence": 2000
    }
    is_anomaly, anomaly_score, attack_type = ai_service.analyze_telemetry(spoofed_telemetry)
    assert isinstance(is_anomaly, bool)
    assert 0.0 <= anomaly_score <= 1.0

def test_real_tree_shap_computation():
    telemetry = {
        "drone_id": "drone_test_3",
        "latitude": 34.0522,
        "longitude": -118.2437,
        "altitude": 10.0,
        "speed": 1.0,
        "battery": 5.0,
        "packet_sequence": 1780
    }
    shap_results = threat_service.compute_real_shap(telemetry)
    assert isinstance(shap_results, list)
    assert len(shap_results) > 0
    assert "feature" in shap_results[0]
    assert "importance" in shap_results[0]

def test_deterministic_sensor_fusion():
    telemetry = {
        "drone_id": "drone_test_4",
        "latitude": 34.0522,
        "longitude": -118.2437,
        "altitude": 150.0,
        "speed": 20.0,
        "battery": 90.0
    }
    res1 = sensor_fusion_engine.fuse_sensors(telemetry)
    res2 = sensor_fusion_engine.fuse_sensors(telemetry)
    assert res1["fused_threat_confidence"] == res2["fused_threat_confidence"]
    assert res1["radar"]["rcs_m2"] == res2["radar"]["rcs_m2"]
    assert res1["rf_scanner"]["signal_strength_dbm"] == res2["rf_scanner"]["signal_strength_dbm"]
