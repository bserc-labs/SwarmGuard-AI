"""Server-side geofence breach detection.

The console evaluates zones in the browser for immediate feedback, but a breach
claim from a client is not evidence. These tests exercise the path that actually
raises an incident: position -> GeofenceEngine -> IncidentEngine.

They use SQLite in memory, like test_incidents.py, because none of this needs
TimescaleDB -- and dependency overrides are installed per test rather than at
import, so they cannot leak into another module's auth assertions.
"""

import os
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from database import Base
from models import GeofenceZone, Incident, Organization, SystemSettings
from services.geofence_service import GeofenceEngine, geofence_engine
from services.incident_engine import incident_engine

ORG_A = 1
ORG_B = 2

# A square over central Los Angeles, given as [lat, lon] to match how the
# backend stores coordinates and how the map reads them.
SQUARE = [
    [34.00, -118.30],
    [34.10, -118.30],
    [34.10, -118.20],
    [34.00, -118.20],
]
INSIDE = (34.05, -118.25)
OUTSIDE = (34.50, -118.25)

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# telemetry_logs has a composite primary key that SQLite cannot autoincrement,
# and nothing here touches it.
if "telemetry_logs" in Base.metadata.tables:
    Base.metadata.remove(Base.metadata.tables["telemetry_logs"])


@pytest.fixture
def db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    for org_id, name in ((ORG_A, "Org A"), (ORG_B, "Org B")):
        session.add(Organization(id=org_id, name=name, slug=name.lower().replace(" ", "-")))
    session.commit()
    try:
        yield session
    finally:
        session.close()


def add_zone(
    db,
    *,
    organization_id,
    name,
    zone_type="POLYGON",
    coordinates=None,
    severity="CRITICAL",
    is_active=True,
):
    zone = GeofenceZone(
        organization_id=organization_id,
        name=name,
        zone_type=zone_type,
        coordinates=SQUARE if coordinates is None else coordinates,
        severity=severity,
        is_active=is_active,
    )
    db.add(zone)
    db.commit()
    db.refresh(zone)
    return zone


# ------------------------------------------------------------------ geometry

class TestZoneMembership:
    def test_position_inside_a_polygon_breaches(self, db):
        add_zone(db, organization_id=ORG_A, name="downtown")
        breached = GeofenceEngine.check_geofence_violations(
            db, *INSIDE, organization_id=ORG_A
        )
        assert [z.name for z in breached] == ["downtown"]

    def test_position_outside_a_polygon_does_not_breach(self, db):
        add_zone(db, organization_id=ORG_A, name="downtown")
        assert (
            GeofenceEngine.check_geofence_violations(db, *OUTSIDE, organization_id=ORG_A)
            == []
        )

    def test_circle_boundary_counts_as_inside(self, db):
        """A no-fly boundary is part of the no-fly zone.

        The circle test is `distance <= radius`, so a position exactly on the
        edge breaches. That is the safe direction to round: an aircraft on the
        line of restricted airspace is in it.
        """
        centre = [34.0522, -118.2437]
        radius = 1000.0
        add_zone(
            db,
            organization_id=ORG_A,
            name="perimeter",
            zone_type="CIRCLE",
            coordinates={"center": centre, "radius": radius},
        )

        # A point placed as close to exactly `radius` metres away as floating
        # point allows, by walking north along a meridian.
        metres_per_degree_lat = 111_320.0
        edge_lat = centre[0] + (radius / metres_per_degree_lat)
        distance = GeofenceEngine.haversine_distance(
            edge_lat, centre[1], centre[0], centre[1]
        )
        assert abs(distance - radius) < 5.0, "test point is not on the boundary"

        just_inside = centre[0] + ((radius - 20) / metres_per_degree_lat)
        just_outside = centre[0] + ((radius + 20) / metres_per_degree_lat)

        assert GeofenceEngine.check_geofence_violations(
            db, just_inside, centre[1], organization_id=ORG_A
        )
        assert not GeofenceEngine.check_geofence_violations(
            db, just_outside, centre[1], organization_id=ORG_A
        )

    def test_inactive_zones_are_ignored(self, db):
        add_zone(db, organization_id=ORG_A, name="retired", is_active=False)
        assert (
            GeofenceEngine.check_geofence_violations(db, *INSIDE, organization_id=ORG_A)
            == []
        )


# ----------------------------------------------------------- tenant isolation

class TestTenantIsolation:
    def test_one_organizations_zone_does_not_breach_for_another(self, db):
        """The defect this closes.

        The query used to select every active zone in the database regardless of
        owner, so Org B's drone would breach Org A's restricted airspace and the
        incident would name a zone Org B cannot see.
        """
        add_zone(db, organization_id=ORG_A, name="org-a-only")

        assert GeofenceEngine.check_geofence_violations(
            db, *INSIDE, organization_id=ORG_A
        )
        assert (
            GeofenceEngine.check_geofence_violations(db, *INSIDE, organization_id=ORG_B)
            == []
        )

    def test_each_organization_sees_only_its_own_overlapping_zone(self, db):
        add_zone(db, organization_id=ORG_A, name="a-zone")
        add_zone(db, organization_id=ORG_B, name="b-zone")

        a = GeofenceEngine.check_geofence_violations(db, *INSIDE, organization_id=ORG_A)
        b = GeofenceEngine.check_geofence_violations(db, *INSIDE, organization_id=ORG_B)

        assert [z.name for z in a] == ["a-zone"]
        assert [z.name for z in b] == ["b-zone"]

    def test_organization_id_is_required(self, db):
        """No caller may evaluate zones without naming the tenant."""
        with pytest.raises(ValueError, match="organization_id is required"):
            GeofenceEngine.check_geofence_violations(db, *INSIDE, organization_id=None)

    def test_evaluate_is_scoped_too(self, db):
        add_zone(db, organization_id=ORG_A, name="org-a-only")
        assert geofence_engine.evaluate(db, "D1", *INSIDE, organization_id=ORG_A)
        assert geofence_engine.evaluate(db, "D1", *INSIDE, organization_id=ORG_B) is None


# --------------------------------------------------------------- detection

class TestDetectionShape:
    def test_no_breach_returns_none(self, db):
        add_zone(db, organization_id=ORG_A, name="downtown")
        assert geofence_engine.evaluate(db, "D1", *OUTSIDE, organization_id=ORG_A) is None

    def test_absent_position_is_not_a_breach(self, db):
        add_zone(db, organization_id=ORG_A, name="downtown")
        assert geofence_engine.evaluate(db, "D1", None, None, organization_id=ORG_A) is None

    def test_detection_matches_the_incident_engine_contract(self, db):
        add_zone(db, organization_id=ORG_A, name="downtown")
        detection = geofence_engine.evaluate(db, "D1", *INSIDE, organization_id=ORG_A)

        assert detection["drone_id"] == "D1"
        assert detection["prediction"]["is_anomaly"] is True
        assert detection["prediction"]["severity"] == "CRITICAL"
        assert detection["explanation"]["summary"]["Attack Type"] == "GEOFENCE_BREACH"
        assert detection["explanation"]["metadata"]["detector"] == "geofence"

        # The console reads these keys off the stored incident.
        for entry in detection["explanation"]["ranked_features"]:
            assert entry["feature"]
            assert isinstance(entry["magnitude"], (int, float))

    def test_warning_zone_is_high_not_critical(self, db):
        add_zone(db, organization_id=ORG_A, name="advisory", severity="WARNING")
        detection = geofence_engine.evaluate(db, "D1", *INSIDE, organization_id=ORG_A)
        assert detection["prediction"]["severity"] == "HIGH"

    def test_worst_zone_leads_when_several_are_breached(self, db):
        add_zone(db, organization_id=ORG_A, name="advisory", severity="WARNING")
        add_zone(db, organization_id=ORG_A, name="no-fly", severity="CRITICAL")

        detection = geofence_engine.evaluate(db, "D1", *INSIDE, organization_id=ORG_A)
        assert detection["prediction"]["severity"] == "CRITICAL"
        assert "no-fly" in detection["explanation"]["summary"]["Primary Cause"]
        assert len(detection["explanation"]["metadata"]["zones"]) == 2


# ------------------------------------------------------- incident lifecycle

class TestIncidentCreation:
    def test_a_breach_becomes_an_incident(self, db):
        add_zone(db, organization_id=ORG_A, name="downtown")
        detection = geofence_engine.evaluate(db, "D1", *INSIDE, organization_id=ORG_A)

        incident = incident_engine.process_ai_detection(
            db, detection, organization_id=ORG_A
        )

        assert incident is not None
        assert incident.attack_type == "GEOFENCE_BREACH"
        assert incident.severity == "CRITICAL"
        assert incident.organization_id == ORG_A
        assert incident.status == "NEW"
        assert incident.shap_values

    def test_incident_is_owned_by_the_breaching_organization(self, db):
        add_zone(db, organization_id=ORG_A, name="downtown")
        detection = geofence_engine.evaluate(db, "D1", *INSIDE, organization_id=ORG_A)
        incident_engine.process_ai_detection(db, detection, organization_id=ORG_A)

        assert db.query(Incident).filter(Incident.organization_id == ORG_B).count() == 0
        assert db.query(Incident).filter(Incident.organization_id == ORG_A).count() == 1

    def test_repeated_breaches_do_not_spam_incidents(self, db):
        """Suppression is inherited from the existing engine, not reimplemented."""
        add_zone(db, organization_id=ORG_A, name="downtown")
        detection = geofence_engine.evaluate(db, "D1", *INSIDE, organization_id=ORG_A)

        first = incident_engine.process_ai_detection(db, detection, organization_id=ORG_A)
        second = incident_engine.process_ai_detection(db, detection, organization_id=ORG_A)

        assert first is not None
        assert second is None, "a repeat breach inside the window must be suppressed"
        assert db.query(Incident).count() == 1

    def test_relabelling_a_suppressed_incident_replaces_its_evidence(self, db):
        """An incident's label and its attribution must describe one event.

        Observed live: a drone sat inside a restricted zone (geofence incident,
        geofence attribution), then its GPS was spoofed a few seconds later.
        Suppression escalated the existing row's attack_type to GPS_SPOOFING but
        left the geofence attribution in place, producing a record headed
        "GPS spoofing" whose evidence was a zone breach.
        """
        add_zone(db, organization_id=ORG_A, name="downtown")
        breach = geofence_engine.evaluate(db, "D1", *INSIDE, organization_id=ORG_A)
        incident = incident_engine.process_ai_detection(
            db, breach, organization_id=ORG_A
        )
        assert incident.attack_type == "GEOFENCE_BREACH"
        assert incident.shap_values[0]["feature"] == "geofence_breach"

        # A worse, differently-classified detection inside the suppression window.
        spoof = {
            "drone_id": "D1",
            "prediction": {
                "is_anomaly": True,
                "anomaly_score": 99.0,
                "threat_score": 99.0,
                "severity": "CRITICAL",
            },
            "explanation": {
                "ranked_features": [
                    {
                        "feature": "gps_airframe_speed_mismatch",
                        "magnitude": 128.0,
                        "shap_value": 128.0,
                        "observed": 3194.0,
                        "threshold": 25.0,
                        "unit": "m/s",
                    }
                ],
                "summary": {"Attack Type": "GPS_SPOOFING", "Primary Cause": "spoofed track"},
            },
        }
        assert incident_engine.process_ai_detection(
            db, spoof, organization_id=ORG_A
        ) is None, "must be suppressed as a repeat for this drone"

        db.expire_all()
        updated = db.query(Incident).filter(Incident.id == incident.id).first()
        assert updated.attack_type == "GPS_SPOOFING"
        assert updated.shap_values[0]["feature"] == "gps_airframe_speed_mismatch", (
            "evidence must follow the label"
        )

    def test_the_same_drone_breaching_in_two_orgs_yields_two_incidents(self, db):
        """Suppression is per tenant, so one org cannot mask another's alert."""
        add_zone(db, organization_id=ORG_A, name="a-zone")
        add_zone(db, organization_id=ORG_B, name="b-zone")

        for org in (ORG_A, ORG_B):
            detection = geofence_engine.evaluate(db, "SHARED-ID", *INSIDE, organization_id=org)
            assert incident_engine.process_ai_detection(
                db, detection, organization_id=org
            ) is not None

        assert db.query(Incident).count() == 2


# --------------------------------------------------- thresholds interaction

class TestThresholdInteraction:
    def test_operator_zone_severity_survives_relaxed_thresholds(self, db):
        """Configuration must not be able to quieten a violated no-fly zone.

        IncidentEngine takes the more serious of the detector's declared
        severity and the organization's configured band, so raising thresholds
        cannot demote a CRITICAL zone breach.
        """
        db.add(
            SystemSettings(
                organization_id=ORG_A, critical_threshold=0.99, high_threshold=0.98
            )
        )
        db.commit()
        add_zone(db, organization_id=ORG_A, name="downtown", severity="CRITICAL")

        detection = geofence_engine.evaluate(db, "D1", *INSIDE, organization_id=ORG_A)
        incident = incident_engine.process_ai_detection(
            db, detection, organization_id=ORG_A
        )

        assert incident.severity == "CRITICAL"
