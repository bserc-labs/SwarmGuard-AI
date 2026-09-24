"""A silent drone is an incident like any other, decided by the incident engine.

The heartbeat monitor used to build an `Incident` row and commit it itself. It
was the one detector that skipped suppression, the per-drone advisory lock, the
organization's severity thresholds and the recommended action -- so a drone that
flickered in and out filed a second CRITICAL incident where any other detector
would have escalated the first, and the row an analyst opened had no
recommendation in it.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

import models
from services.heartbeat_service import SILENCE_THRESHOLD_SECONDS, check_drone_heartbeats


@pytest.fixture
def organization(db_session):
    suffix = uuid.uuid4().hex[:8]
    org = models.Organization(name=f"pytest heartbeat {suffix}", slug=f"pytest-hb-{suffix}")
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)

    yield org

    db_session.rollback()
    for table in (models.Incident, models.Drone):
        db_session.query(table).filter(table.organization_id == org.id).delete(
            synchronize_session=False
        )
    db_session.query(models.Organization).filter(models.Organization.id == org.id).delete(
        synchronize_session=False
    )
    db_session.commit()


def _silent_drone(db, organization, *, silent_for: float) -> models.Drone:
    drone = models.Drone(
        drone_id=f"hb-{uuid.uuid4().hex[:6]}",
        status="ACTIVE",
        organization_id=organization.id,
        last_seen=datetime.now(UTC) - timedelta(seconds=silent_for),
    )
    db.add(drone)
    db.commit()
    db.refresh(drone)
    return drone


def _incidents(db, organization, drone_id):
    return (
        db.query(models.Incident)
        .filter(
            models.Incident.organization_id == organization.id,
            models.Incident.drone_id == drone_id,
        )
        .all()
    )


class TestOneSilenceOneIncident:
    def test_a_silent_drone_is_recorded_and_marked(self, db_session, organization):
        drone = _silent_drone(db_session, organization, silent_for=SILENCE_THRESHOLD_SECONDS + 5)

        alerts = check_drone_heartbeats(db_session)

        db_session.refresh(drone)
        assert drone.status == "SILENT_POSSIBLE_JAMMING"
        incidents = _incidents(db_session, organization, drone.drone_id)
        assert len(incidents) == 1
        assert incidents[0].attack_type == "SIGNAL_LOSS_JAMMING"
        assert incidents[0].severity == "CRITICAL"
        # The monitor sweeps every tenant, so other drones may be silent too.
        assert organization.id in [org_id for org_id, _ in alerts]

    def test_the_engine_fills_in_what_the_monitor_used_to_leave_empty(
        self, db_session, organization
    ):
        drone = _silent_drone(db_session, organization, silent_for=SILENCE_THRESHOLD_SECONDS + 5)

        check_drone_heartbeats(db_session)

        incident = _incidents(db_session, organization, drone.drone_id)[0]
        assert incident.recommended_action, "an analyst opens this row and needs a next step"
        assert incident.priority is not None
        assert incident.explanation_summary
        assert incident.status == "NEW"
        # Ordinal rank, comparable with every other detector's incidents.
        assert incident.threat_level == 4

    def test_a_drone_that_flickers_escalates_instead_of_filing_a_second(
        self, db_session, organization
    ):
        drone = _silent_drone(db_session, organization, silent_for=SILENCE_THRESHOLD_SECONDS + 5)
        check_drone_heartbeats(db_session)

        # It reports once, then goes quiet again inside the suppression window.
        drone.status = "ACTIVE"
        drone.last_seen = datetime.now(UTC) - timedelta(seconds=SILENCE_THRESHOLD_SECONDS + 5)
        db_session.commit()

        alerts = check_drone_heartbeats(db_session)

        assert len(_incidents(db_session, organization, drone.drone_id)) == 1, (
            "the same silence must escalate one incident, not stack a second"
        )
        for _, payload in alerts:
            assert payload["event_type"] == "INCIDENT_ESCALATED"

    def test_the_alert_carries_the_incident_the_dashboard_will_open(
        self, db_session, organization
    ):
        drone = _silent_drone(db_session, organization, silent_for=SILENCE_THRESHOLD_SECONDS + 5)

        alerts = check_drone_heartbeats(db_session)

        _, payload = alerts[0]
        incident = _incidents(db_session, organization, drone.drone_id)[0]
        assert payload["incident_id"] == incident.id
        assert payload["type"] == "incident"
        assert payload["drone_id"] == drone.drone_id
        assert payload["severity"] == "CRITICAL"
        assert payload["recommended_action"]

    def test_a_drone_still_reporting_is_left_alone(self, db_session, organization):
        drone = _silent_drone(db_session, organization, silent_for=SILENCE_THRESHOLD_SECONDS - 10)

        alerts = check_drone_heartbeats(db_session)

        assert drone.drone_id not in [p["drone_id"] for _, p in alerts]
        db_session.refresh(drone)
        assert drone.status == "ACTIVE"
        assert _incidents(db_session, organization, drone.drone_id) == []


class TestEveryIncidentHasAnOwner:
    def test_a_drone_cannot_exist_without_an_organization(self, db_session):
        # Why the monitor has no orgless branch: the column is NOT NULL, so the
        # incident it records always has a tenant to be visible to. It used to
        # write incidents with a NULL organization, which no tenant-scoped read
        # could return -- alerts that fired and reached nobody.
        from sqlalchemy.exc import IntegrityError

        db_session.add(
            models.Drone(
                drone_id=f"hb-orphan-{uuid.uuid4().hex[:6]}",
                status="ACTIVE",
                organization_id=None,
                last_seen=datetime.now(UTC) - timedelta(seconds=SILENCE_THRESHOLD_SECONDS + 5),
            )
        )
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()
