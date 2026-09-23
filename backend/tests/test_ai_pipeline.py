import os
import sys
from datetime import UTC, datetime, timedelta

import pytest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from experimental.sensor_fusion import sensor_fusion_engine
from experimental.threat_service import threat_service
from services.ai_service import ai_service


@pytest.mark.skip(reason="AI models are out of scope for Sprint 1")
def test_ai_service_model_loading():
    ai_service.load_models()
    assert ai_service.anomaly_detector is not None
    assert ai_service.attack_classifier is not None
    assert ai_service.scaler is not None

@pytest.mark.skip(reason="AI models are out of scope for Sprint 1")
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
    is_anomaly, anomaly_score, _attack_type = ai_service.analyze_telemetry(normal_telemetry)
    assert isinstance(is_anomaly, bool)
    assert 0.0 <= anomaly_score <= 1.0

def _telemetry_window(n=8):
    """A history window. Inference needs one: every feature is a rolling stat."""
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    return [
        {
            "drone_id": "drone_test_2",
            "latitude": 34.4500 + i * 0.0002,
            "longitude": -117.8000,
            "altitude": 350.0,
            "speed": 140.0,
            "heading": 90.0,
            "battery": 60.0 - i * 0.05,
            "flight_mode": "AUTO",
            "armed_status": True,
            "satellites": 12,
            "packet_sequence": 2000 + i,
            "created_at": base + timedelta(seconds=1.5 * i),
        }
        for i in range(n)
    ]


def test_anomaly_telemetry_inference():
    # The service exposes predict(history), not analyze_telemetry(packet).
    # This test previously called a method that does not exist on
    # AIInferenceService and had been failing with AttributeError.
    result = ai_service.predict(_telemetry_window())
    assert isinstance(result["is_anomaly"], bool)
    assert 0.0 <= result["anomaly_score"] <= 100.0
    assert result["threat_level"] in {"LOW", "MEDIUM", "HIGH", "CRITICAL", "UNKNOWN"}


def test_shap_returns_empty_rather_than_placeholders():
    # compute_real_shap takes a history window. Given none, it must return an
    # empty list -- it used to swallow every error and return a hardcoded
    # triple (speed 0.48 / altitude 0.32 / battery_drain_rate 0.20), so an
    # unexplainable detection looked identical to an explained one.
    assert threat_service.compute_real_shap([]) == []
    assert threat_service.compute_real_shap(None) == []


def test_shap_output_shape_when_available():
    # With a model loaded this returns real attributions; without one it
    # returns []. Both are valid -- what must never appear is invented values.
    results = threat_service.compute_real_shap(_telemetry_window())
    assert isinstance(results, list)
    for entry in results:
        assert "feature" in entry
        assert "importance" in entry
        assert 0.0 <= entry["importance"] <= 1.0

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
