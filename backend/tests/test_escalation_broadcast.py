"""An escalated incident has to reach the socket, not just the database.

`IncidentEngine` used to return None for a detection that was folded into a
live incident -- including one that raised it from MEDIUM to CRITICAL. The
pipeline treated None as "nothing to send", so the row escalated and the
operator's dashboard kept showing the severity it had first been told.

Driven with stubs so that what is asserted is the pipeline's decision -- which
outcomes produce a frame, and what that frame looks like -- not the engine's.
"""

import asyncio

import pytest

import models
from services import detection_pipeline
from services.incident_engine import DetectionOutcome


class _Session:
    def close(self) -> None:
        pass


def _incident(**overrides) -> models.Incident:
    fields = {
        "id": 7, "drone_id": "D1", "organization_id": 1, "attack_type": "GPS_SPOOFING",
        "severity": "CRITICAL", "anomaly_score": 90.0, "threat_level": 4, "threat_score": 90.0,
        "priority": 90, "shap_values": [{"feature": "gps_implied_speed", "shap_value": 61.7}],
        "explanation": "x", "recommended_action": "Verify GNSS integrity.",
        "explanation_summary": {"primary_cause": "jump"}, "model_version": "physics-v1",
    }
    fields.update(overrides)
    return models.Incident(**fields)


@pytest.fixture
def pipeline(monkeypatch):
    """`_detect_sync` with everything upstream of the engine stubbed out."""
    monkeypatch.setattr(detection_pipeline, "SessionLocal", _Session)
    monkeypatch.setattr(detection_pipeline, "_load_history", lambda *a, **k: [{}, {}])
    monkeypatch.setattr(detection_pipeline, "_run_detectors", lambda *a, **k: {"drone_id": "D1"})

    def run(outcome: DetectionOutcome):
        monkeypatch.setattr(
            detection_pipeline.incident_engine, "record_detection", lambda *a, **k: outcome
        )
        return detection_pipeline._detect_sync("D1", 1)

    return run


class TestWhichOutcomesProduceAFrame:
    def test_a_created_incident(self, pipeline):
        frame = pipeline(DetectionOutcome(incident=_incident(), created=True))
        assert frame["event_type"] == "AI_DETECTION"
        assert frame["incident_id"] == 7

    def test_an_escalated_incident(self, pipeline):
        frame = pipeline(DetectionOutcome(incident=_incident(), created=False))
        assert frame is not None, "an escalation must be broadcast, not dropped"
        assert frame["event_type"] == "INCIDENT_ESCALATED"
        # Same incident_id as the frame that announced it, so a client keyed on
        # the incident updates in place rather than showing a second alert.
        assert frame["incident_id"] == 7
        assert frame["severity"] == "CRITICAL"

    def test_a_repeat_that_did_not_worsen(self, pipeline):
        assert pipeline(DetectionOutcome(incident=None, created=False)) is None


def test_both_frames_have_the_shape_the_console_reads(pipeline):
    """frontend WebSocketContext.isAlertFrame keys on is_anomaly / attack_type."""
    created = pipeline(DetectionOutcome(incident=_incident(), created=True))
    escalated = pipeline(DetectionOutcome(incident=_incident(), created=False))

    assert set(created) == set(escalated)
    for frame in (created, escalated):
        assert frame["type"] == "incident"
        assert frame["is_anomaly"] is True
        assert isinstance(frame["attack_type"], str)
        assert frame["shap_top3"] == [{"feature": "gps_implied_speed", "importance": 61.7}]


def test_run_detection_delivers_the_escalation(monkeypatch):
    payload = {
        "event_type": "INCIDENT_ESCALATED", "incident_id": 7,
        "severity": "CRITICAL", "attack_type": "GPS_SPOOFING",
    }
    monkeypatch.setattr(detection_pipeline, "_detect_sync", lambda *a, **k: payload)

    class Recorder:
        def __init__(self):
            self.calls = []

        async def broadcast(self, message, organization_id):
            self.calls.append((message, organization_id))

    recorder = Recorder()
    monkeypatch.setattr(detection_pipeline, "ws_manager", recorder)

    asyncio.run(detection_pipeline.run_detection("D1", 1))
    assert recorder.calls == [(payload, 1)]
