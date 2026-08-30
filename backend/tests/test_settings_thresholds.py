"""Per-organization severity thresholds.

These were persisted but never read: `generate_alert_severity` hardcoded
85/60/40, so the Settings screen's two controls had no effect on anything. The
tests below pin the behaviour that replaces that, and in particular that one
tenant's configuration cannot reach another's incidents.
"""

import os
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from database import Base
from models import Incident, Organization, SystemSettings
from services.alert_service import (
    DEFAULT_CRITICAL_THRESHOLD,
    DEFAULT_HIGH_THRESHOLD,
    MEDIUM_FLOOR_SCORE,
    alert_service,
    resolve_thresholds,
)
from services.incident_engine import incident_engine

ORG_STRICT = 1   # tightened bands: more things are critical
ORG_RELAXED = 2  # loosened bands: fewer things are critical
ORG_DEFAULT = 3  # never opened the Settings screen

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

if "telemetry_logs" in Base.metadata.tables:
    Base.metadata.remove(Base.metadata.tables["telemetry_logs"])


@pytest.fixture
def db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    for org_id in (ORG_STRICT, ORG_RELAXED, ORG_DEFAULT):
        session.add(Organization(id=org_id, name=f"Org {org_id}", slug=f"org-{org_id}"))
    # Strict: anything at or above 50 is critical.
    session.add(
        SystemSettings(
            organization_id=ORG_STRICT, critical_threshold=0.50, high_threshold=0.30
        )
    )
    # Relaxed: it takes 95 to be critical.
    session.add(
        SystemSettings(
            organization_id=ORG_RELAXED, critical_threshold=0.95, high_threshold=0.90
        )
    )
    session.commit()
    try:
        yield session
    finally:
        session.close()


def detection(drone_id, threat_score, *, severity=None):
    """A score-only detection, i.e. one with no detector-declared severity.

    The ML tier looks like this. The kinematic guard and the geofence engine
    declare their own severity, which is covered separately.
    """
    prediction = {
        "is_anomaly": True,
        "anomaly_score": threat_score,
        "threat_score": threat_score,
    }
    if severity is not None:
        prediction["severity"] = severity
    return {
        "drone_id": drone_id,
        "prediction": prediction,
        "explanation": {"summary": {"Attack Type": "TEST_ANOMALY"}, "ranked_features": []},
    }


# ------------------------------------------------------------- resolution

class TestResolution:
    def test_defaults_when_the_organization_has_no_row(self, db):
        bands = resolve_thresholds(db, ORG_DEFAULT)
        assert bands.critical == DEFAULT_CRITICAL_THRESHOLD * 100
        assert bands.high == DEFAULT_HIGH_THRESHOLD * 100
        assert bands.source == "default"

    def test_defaults_when_there_is_no_organization_at_all(self, db):
        assert resolve_thresholds(db, None).source == "default"

    def test_stored_values_are_converted_to_the_score_scale(self, db):
        bands = resolve_thresholds(db, ORG_STRICT)
        # Stored as fractions, applied against a 0-100 threat score.
        assert bands.critical == 50.0
        assert bands.high == 30.0
        assert bands.source == "organization"

    def test_resolution_does_not_create_a_settings_row(self, db):
        """Detection runs in a background thread, several packets at a time.

        A resolver that INSERTed on a miss would have those packets racing to
        create the same row for a new organization.
        """
        before = db.query(SystemSettings).count()
        resolve_thresholds(db, ORG_DEFAULT)
        assert db.query(SystemSettings).count() == before

    def test_unusable_stored_values_fall_back_rather_than_misclassify(self, db):
        """A row written before validation existed, or edited in the database."""
        row = (
            db.query(SystemSettings)
            .filter(SystemSettings.organization_id == ORG_STRICT)
            .first()
        )
        row.high_threshold = 0.9
        row.critical_threshold = 0.5  # inverted: nothing could be HIGH
        db.commit()

        assert resolve_thresholds(db, ORG_STRICT).source == "default"


# ----------------------------------------------------------------- banding

class TestBanding:
    def test_defaults_reproduce_the_previous_hardcoded_behaviour(self):
        assert alert_service.generate_alert_severity(90.0) == "CRITICAL"
        assert alert_service.generate_alert_severity(70.0) == "HIGH"
        assert alert_service.generate_alert_severity(50.0) == "MEDIUM"
        assert alert_service.generate_alert_severity(10.0) == "LOW"

    def test_boundaries_are_inclusive(self):
        assert alert_service.generate_alert_severity(85.0) == "CRITICAL"
        assert alert_service.generate_alert_severity(60.0) == "HIGH"
        assert alert_service.generate_alert_severity(MEDIUM_FLOOR_SCORE) == "MEDIUM"
        assert alert_service.generate_alert_severity(MEDIUM_FLOOR_SCORE - 0.01) == "LOW"

    def test_the_same_score_bands_differently_per_organization(self, db):
        score = 55.0
        strict = alert_service.generate_alert_severity(score, resolve_thresholds(db, ORG_STRICT))
        relaxed = alert_service.generate_alert_severity(score, resolve_thresholds(db, ORG_RELAXED))
        default = alert_service.generate_alert_severity(score, resolve_thresholds(db, ORG_DEFAULT))

        assert strict == "CRITICAL"   # 55 >= 50
        assert relaxed == "MEDIUM"    # 55 < 90
        assert default == "MEDIUM"    # 55 < 60


# ------------------------------------------------------- end-to-end tenancy

class TestTenantIsolation:
    def test_identical_telemetry_yields_different_severities_per_tenant(self, db):
        """The headline property: configuration is per tenant and does not leak."""
        strict = incident_engine.process_ai_detection(
            db, detection("D1", 55.0), organization_id=ORG_STRICT
        )
        relaxed = incident_engine.process_ai_detection(
            db, detection("D2", 55.0), organization_id=ORG_RELAXED
        )
        default = incident_engine.process_ai_detection(
            db, detection("D3", 55.0), organization_id=ORG_DEFAULT
        )

        assert strict.severity == "CRITICAL"
        assert relaxed.severity == "MEDIUM"
        assert default.severity == "MEDIUM"

    def test_one_tenants_settings_do_not_reach_another(self, db):
        """Deleting the relaxed org's row must not change the strict org's result."""
        db.query(SystemSettings).filter(
            SystemSettings.organization_id == ORG_RELAXED
        ).delete()
        db.commit()

        incident = incident_engine.process_ai_detection(
            db, detection("D1", 55.0), organization_id=ORG_STRICT
        )
        assert incident.severity == "CRITICAL"

    def test_severity_source_is_recorded(self, db):
        configured = incident_engine.process_ai_detection(
            db, detection("D1", 55.0), organization_id=ORG_STRICT
        )
        fallback = incident_engine.process_ai_detection(
            db, detection("D2", 55.0), organization_id=ORG_DEFAULT
        )

        assert configured.explanation_summary["severity_source"] == "organization"
        assert fallback.explanation_summary["severity_source"] == "default"


# ------------------------------------------------ detector severity floor

class TestDetectorFloor:
    def test_a_detector_declared_severity_is_never_lowered(self, db):
        """Physics and operator policy act as a floor configuration cannot cross.

        The kinematic guard grades on exceedance and violation count; a geofence
        breach inherits the zone's declared severity. Relaxing thresholds must
        not be able to demote either.
        """
        incident = incident_engine.process_ai_detection(
            db, detection("D1", 55.0, severity="CRITICAL"), organization_id=ORG_RELAXED
        )
        assert incident.severity == "CRITICAL"
        assert incident.explanation_summary["severity_source"] == "detector"

    def test_tightening_thresholds_still_raises_a_detector_severity(self, db):
        """The asymmetry runs the other way: policy may escalate."""
        incident = incident_engine.process_ai_detection(
            db, detection("D1", 55.0, severity="MEDIUM"), organization_id=ORG_STRICT
        )
        # The detector said MEDIUM; the strict org bands 55 as CRITICAL.
        assert incident.severity == "CRITICAL"

    def test_an_unrecognised_detector_severity_is_ignored(self, db):
        incident = incident_engine.process_ai_detection(
            db, detection("D1", 55.0, severity="CATASTROPHIC"), organization_id=ORG_DEFAULT
        )
        assert incident.severity == "MEDIUM"


# -------------------------------------------------------------- durability

class TestExistingIncidentsAreNotRewritten:
    def test_changing_thresholds_leaves_stored_incidents_alone(self, db):
        incident = incident_engine.process_ai_detection(
            db, detection("D1", 55.0), organization_id=ORG_RELAXED
        )
        incident_id = incident.id
        assert incident.severity == "MEDIUM"

        # The operator tightens the bands afterwards.
        row = (
            db.query(SystemSettings)
            .filter(SystemSettings.organization_id == ORG_RELAXED)
            .first()
        )
        row.critical_threshold = 0.50
        row.high_threshold = 0.30
        db.commit()

        db.expire_all()
        stored = db.query(Incident).filter(Incident.id == incident_id).first()
        assert stored.severity == "MEDIUM", "history must not be retroactively re-graded"

    def test_the_next_detection_uses_the_new_bands(self, db):
        row = (
            db.query(SystemSettings)
            .filter(SystemSettings.organization_id == ORG_RELAXED)
            .first()
        )
        row.critical_threshold = 0.50
        row.high_threshold = 0.30
        db.commit()

        incident = incident_engine.process_ai_detection(
            db, detection("FRESH", 55.0), organization_id=ORG_RELAXED
        )
        assert incident.severity == "CRITICAL"
