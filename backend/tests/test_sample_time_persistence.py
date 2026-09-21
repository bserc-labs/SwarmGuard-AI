"""`sample_time_ms` from the ingest schema to the hypertable and back out.

The kinematic guard can only rate motion on the device clock if the value
survives every hop: schema validation, the TimescaleDB hypertable (migration
g7b8c9d0e1f2), and the history window the detector reads back. Each hop is
pinned here against the real database.
"""

import uuid
from datetime import datetime, timedelta

import pydantic
import pytest
from sqlalchemy import text

import models
import schemas
from services import detection_pipeline
from services.telemetry_service import telemetry_service
from tests.conftest import purge_audit_logs

UINT32_MAX = 4_294_967_295  # MAVLink time_boot_ms is a uint32
EPOCH_MS = 1_700_000_000_000  # overflows a 32-bit Integer column


@pytest.fixture
def organization(db_session):
    suffix = uuid.uuid4().hex[:8]
    org = models.Organization(name=f"pytest sample-time {suffix}", slug=f"pytest-st-{suffix}")
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)

    yield org

    # Children first, each step committed before the next: purge_audit_logs
    # opens with a rollback and would discard anything merely staged.
    db_session.rollback()
    db_session.query(models.TelemetryLog).filter(
        models.TelemetryLog.organization_id == org.id
    ).delete(synchronize_session=False)
    db_session.query(models.Drone).filter(
        models.Drone.organization_id == org.id
    ).delete(synchronize_session=False)
    db_session.commit()
    purge_audit_logs(db_session, org.id)
    db_session.query(models.Organization).filter(
        models.Organization.id == org.id
    ).delete(synchronize_session=False)
    db_session.commit()


def _packet(drone_id: str, seq: int, **extra) -> schemas.TelemetryPacket:
    return schemas.TelemetryPacket(
        drone_id=drone_id, latitude=34.0522, longitude=-118.2437, altitude=150.0,
        speed=18.0, heading=90.0, battery=90.0, flight_mode="AUTO",
        armed_status=True, satellites=12, packet_sequence=seq, **extra,
    )


class TestSchema:
    def test_bounds(self):
        assert _packet("d", 1).sample_time_ms is None
        assert _packet("d", 1, sample_time_ms=0).sample_time_ms == 0
        assert _packet("d", 1, sample_time_ms=2**53 - 1).sample_time_ms == 2**53 - 1
        for bad in (-1, 2**53):
            with pytest.raises(pydantic.ValidationError):
                _packet("d", 1, sample_time_ms=bad)


class TestHypertable:
    def test_values_wider_than_int32_round_trip(self, db_session, organization):
        drone_id = f"st-{uuid.uuid4().hex[:6]}"
        for value in (UINT32_MAX, EPOCH_MS, None):
            db_session.add(
                models.TelemetryLog(
                    organization_id=organization.id, drone_id=drone_id,
                    latitude=34.0, longitude=-118.0, altitude=100.0, speed=15.0,
                    battery=90.0, packet_sequence=1, sample_time_ms=value,
                )
            )
        db_session.commit()

        # Compared as a set: rows committed in one transaction share created_at
        # exactly, so ordering on it would be arbitrary.
        rows = db_session.execute(
            text("SELECT sample_time_ms FROM telemetry_logs WHERE drone_id = :d"),
            {"d": drone_id},
        ).fetchall()
        assert {r[0] for r in rows} == {UINT32_MAX, EPOCH_MS, None}


class TestIngest:
    def test_process_telemetry_carries_the_value_to_the_row(self, db_session, organization):
        drone_id = f"st-{uuid.uuid4().hex[:6]}"
        returned = telemetry_service.process_telemetry(
            _packet(drone_id, 1, sample_time_ms=812_345),
            db_session, organization_id=organization.id, actor="pytest",
        )
        assert returned["sample_time_ms"] == 812_345

        stored = (
            db_session.query(models.TelemetryLog)
            .filter(models.TelemetryLog.drone_id == drone_id)
            .one()
        )
        assert stored.sample_time_ms == 812_345

    def test_a_packet_without_it_stores_null(self, db_session, organization):
        drone_id = f"st-{uuid.uuid4().hex[:6]}"
        returned = telemetry_service.process_telemetry(
            _packet(drone_id, 1), db_session, organization_id=organization.id, actor="pytest"
        )
        assert returned["sample_time_ms"] is None
        stored = (
            db_session.query(models.TelemetryLog)
            .filter(models.TelemetryLog.drone_id == drone_id)
            .one()
        )
        assert stored.sample_time_ms is None


class TestHistoryWindow:
    def test_the_device_clock_passes_through_in_arrival_order(self, db_session, organization):
        """Pins a decision: the window is NOT re-sorted by device time.

        A reboot resets time_boot_ms to ~0, so sorting by it would put the
        post-reboot packets before the pre-reboot ones and the guard would keep
        re-evaluating a stale pair. The guard handles a non-monotonic device
        interval itself.
        """
        drone_id = f"st-{uuid.uuid4().hex[:6]}"
        # Relative to now, not a fixed date: the retention sweep that runs at
        # application startup (main.py) purges telemetry older than three days.
        base = datetime.utcnow().replace(microsecond=0) - timedelta(minutes=10)
        for i, sample_ms in enumerate((3000, 1500, 4500)):
            db_session.add(
                models.TelemetryLog(
                    organization_id=organization.id, drone_id=drone_id,
                    latitude=34.0, longitude=-118.0, altitude=100.0, speed=15.0,
                    battery=90.0, packet_sequence=i, sample_time_ms=sample_ms,
                    created_at=base + timedelta(seconds=i),
                )
            )
        db_session.commit()

        history = detection_pipeline._load_history(db_session, drone_id, organization.id)
        assert [h["sample_time_ms"] for h in history] == [3000, 1500, 4500]
