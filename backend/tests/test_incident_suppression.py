"""What suppression folds together, what it must not, and what it reports.

Three defects lived in the same forty lines:

  * suppression matched RESOLVED and CLOSED incidents, so an operator who
    resolved an incident while the attack was still running got nothing
    written and nothing broadcast for the next 60 s;
  * an escalation inside the window -- MEDIUM climbing to CRITICAL -- updated
    the row and returned None, so the dashboard kept the lower severity;
  * the check-then-insert was not atomic (covered against a real database in
    test_incident_concurrency.py).

Runs on in-memory SQLite, creating only the tables it needs. The older SQLite
modules strip `telemetry_logs` out of the shared Base.metadata to get
create_all() past its composite key; that mutates global state for every test
that runs after them, so it is not repeated here.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from services.alert_service import LIVE_INCIDENT_STATUSES
from services.incident_engine import (
    DetectionOutcome,
    _serialize_incident_writes,
    incident_engine,
)

ORG = 1
TABLES = [
    models.Organization.__table__,
    models.SystemSettings.__table__,
    models.Incident.__table__,
]

engine = create_engine(
    "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture
def db():
    models.Base.metadata.drop_all(bind=engine, tables=TABLES)
    models.Base.metadata.create_all(bind=engine, tables=TABLES)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def detection(drone_id: str, score: float, attack_type: str = "GPS_SPOOFING", severity=None):
    prediction = {
        "is_anomaly": True, "anomaly_score": score, "threat_score": score, "threat_level": "HIGH",
    }
    if severity is not None:
        prediction["severity"] = severity
    return {
        "drone_id": drone_id,
        "prediction": prediction,
        "explanation": {
            "summary": {"Attack Type": attack_type, "Primary Cause": f"{attack_type} evidence"},
            "ranked_features": [{"feature": attack_type.lower(), "magnitude": 1.0}],
            "metadata": {},
        },
    }


def rows(db, drone_id: str) -> list[models.Incident]:
    return (
        db.query(models.Incident)
        .filter(models.Incident.drone_id == drone_id)
        .order_by(models.Incident.id)
        .all()
    )


class TestResolvedIncidentsDoNotSuppress:
    @pytest.mark.parametrize("status", ["RESOLVED", "CLOSED"])
    def test_the_next_detection_is_a_new_incident(self, db, status):
        first = incident_engine.process_ai_detection(db, detection("R1", 85), organization_id=ORG)
        assert first is not None
        first.status = status
        db.commit()

        second = incident_engine.process_ai_detection(db, detection("R1", 85), organization_id=ORG)
        assert second is not None, (
            f"a {status} incident suppressed the next detection: an operator who closes "
            "an incident mid-attack would hear nothing for the rest of the window"
        )
        assert second.id != first.id

        stored = rows(db, "R1")
        assert len(stored) == 2
        # History is not rewritten.
        assert stored[0].status == status
        assert stored[0].severity == "CRITICAL"

    @pytest.mark.parametrize("status", LIVE_INCIDENT_STATUSES)
    def test_a_live_incident_still_suppresses(self, db, status):
        first = incident_engine.process_ai_detection(db, detection("L1", 85), organization_id=ORG)
        first.status = status
        db.commit()

        assert incident_engine.process_ai_detection(db, detection("L1", 85), organization_id=ORG) is None
        assert len(rows(db, "L1")) == 1


class TestEscalationIsReported:
    def test_a_rising_severity_comes_back_without_a_new_row(self, db):
        first = incident_engine.process_ai_detection(db, detection("E1", 50), organization_id=ORG)
        assert first.severity == "MEDIUM"

        # The old contract is kept for callers that only want new rows...
        assert incident_engine.process_ai_detection(db, detection("E1", 70), organization_id=ORG) is None
        db.refresh(first)
        assert first.severity == "HIGH"

        # ...and record_detection says what actually happened.
        outcome = incident_engine.record_detection(db, detection("E1", 90), organization_id=ORG)
        assert outcome.created is False
        assert outcome.escalated is True
        assert outcome.incident is not None
        assert outcome.incident.id == first.id
        assert outcome.incident.severity == "CRITICAL"
        assert len(rows(db, "E1")) == 1

    def test_a_repeat_that_does_not_worsen_is_not_an_escalation(self, db):
        first = incident_engine.process_ai_detection(db, detection("S1", 70), organization_id=ORG)
        before = first.updated_at

        outcome = incident_engine.record_detection(db, detection("S1", 70), organization_id=ORG)
        assert outcome == DetectionOutcome(incident=None, created=False)
        assert outcome.escalated is False

        # Still folded in: the live incident is kept fresh.
        db.refresh(first)
        assert first.updated_at is not None
        assert before is None or first.updated_at >= before

    def test_a_worse_reading_within_the_same_band_is_not_broadcast(self, db):
        """61 -> 80 is a higher score and the same HIGH band: nothing for an operator to see."""
        incident_engine.process_ai_detection(db, detection("B1", 61), organization_id=ORG)
        outcome = incident_engine.record_detection(db, detection("B1", 80), organization_id=ORG)
        assert outcome.incident is None
        assert rows(db, "B1")[0].threat_score == 80

    def test_a_relabel_alone_counts(self, db):
        first = incident_engine.process_ai_detection(
            db, detection("G1", 95, "GEOFENCE_BREACH", severity="CRITICAL"), organization_id=ORG
        )
        outcome = incident_engine.record_detection(
            db, detection("G1", 99, "GPS_SPOOFING"), organization_id=ORG
        )
        assert outcome.escalated is True
        assert outcome.incident.id == first.id
        assert outcome.incident.attack_type == "GPS_SPOOFING"
        assert outcome.incident.severity == "CRITICAL"

    def test_a_new_incident_is_created_not_escalated(self, db):
        outcome = incident_engine.record_detection(db, detection("N1", 85), organization_id=ORG)
        assert outcome.created is True
        assert outcome.escalated is False

    def test_normal_telemetry_changes_nothing(self, db):
        quiet = detection("Q1", 5)
        quiet["prediction"]["is_anomaly"] = False
        outcome = incident_engine.record_detection(db, quiet, organization_id=ORG)
        assert outcome == DetectionOutcome(incident=None, created=False)
        assert rows(db, "Q1") == []


class TestTheLockIsPostgresOnly:
    def test_it_is_a_no_op_on_sqlite(self, db, monkeypatch):
        def must_not_run(*args, **kwargs):
            raise AssertionError("pg_advisory_xact_lock was issued against SQLite")

        monkeypatch.setattr(db, "execute", must_not_run)
        assert _serialize_incident_writes(db, ORG, "D1") is None


def test_the_live_status_set_is_the_lifecycle_before_resolved():
    """Three copies of this list exist; this keeps them from drifting apart.

    routers/incidents.py LIFECYCLE is the authority. alert_service mirrors its
    live prefix, and the /incidents/open handler carries a literal copy.
    """
    import inspect

    from routers import incidents as incidents_router

    lifecycle = incidents_router.LIFECYCLE
    expected = lifecycle[: lifecycle.index("RESOLVED")]
    assert list(LIVE_INCIDENT_STATUSES) == expected

    literal = '["NEW", "OPEN", "ACKNOWLEDGED", "INVESTIGATING", "CONTAINED"]'
    if literal in inspect.getsource(incidents_router):
        assert expected == ["NEW", "OPEN", "ACKNOWLEDGED", "INVESTIGATING", "CONTAINED"]
