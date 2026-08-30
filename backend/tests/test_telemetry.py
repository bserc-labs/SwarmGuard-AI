"""Telemetry storage against the real TimescaleDB hypertable.

The insert carries an owning organization. It used to omit one, which wrote a
row with organization_id NULL -- invisible to every tenant-scoped read and still
occupying the hypertable. Nineteen such rows had accumulated by the time
migration d4e5f6a7b8c9 made the column NOT NULL.
"""

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql import text

import models


@pytest.fixture
def organization(db_session):
    """A throwaway organization owning this test's rows, removed afterwards."""
    suffix = uuid.uuid4().hex[:8]
    org = models.Organization(name=f"pytest telemetry {suffix}", slug=f"pytest-tlm-{suffix}")
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)

    yield org

    db_session.rollback()
    db_session.query(models.TelemetryLog).filter(
        models.TelemetryLog.organization_id == org.id
    ).delete(synchronize_session=False)
    db_session.query(models.Organization).filter(
        models.Organization.id == org.id
    ).delete(synchronize_session=False)
    db_session.commit()


def test_insert_and_read_telemetry(db_session, organization):
    drone_id = f"test_drone_{uuid.uuid4().hex[:6]}"

    db_session.add(
        models.TelemetryLog(
            organization_id=organization.id,
            drone_id=drone_id,
            latitude=37.7749,
            longitude=-122.4194,
            altitude=100.5,
            speed=15.2,
            battery=98.0,
            packet_sequence=1,
        )
    )
    db_session.commit()

    # Read back through raw SQL to confirm it landed in the hypertable rather
    # than only in the session's identity map.
    result = db_session.execute(
        text(
            "SELECT drone_id, latitude, organization_id FROM telemetry_logs "
            "WHERE drone_id = :d ORDER BY created_at DESC LIMIT 1"
        ),
        {"d": drone_id},
    ).fetchone()

    assert result is not None
    assert result[0] == drone_id
    assert result[1] == 37.7749
    assert result[2] == organization.id


def test_telemetry_without_an_organization_is_refused(db_session):
    """The hypertable enforces ownership too, chunks included."""
    db_session.add(
        models.TelemetryLog(
            drone_id=f"orphan_{uuid.uuid4().hex[:6]}",
            latitude=37.7749,
            longitude=-122.4194,
            altitude=100.5,
            speed=15.2,
            battery=98.0,
            packet_sequence=1,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
