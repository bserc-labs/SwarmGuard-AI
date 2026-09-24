"""Telemetry the detector cannot rate is refused at the door, not stored.

Under overload packets are stored tens of seconds after they were sampled, out
of order. The kinematic guard declines to rate such a packet rather than file a
false alert over it, which is honest and still leaves detection quiet exactly
when the system is stressed. Ingest now asks the guard's question before the
insert and answers 503 with Retry-After, so the backlog is visible to the
sender instead of hidden in `swarmguard_guard_declined_total`.

The last class ties the two together: the packet refused here is exactly one
the guard would otherwise have declined.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import models
from main import app
from middleware.auth_middleware import TenantContext, get_tenant_context
from services import kinematic_guard
from tests.conftest import TestingSessionLocal, purge_audit_logs
from utils.metrics import GUARD_DECLINED, INGEST

SHARED = "s" * 64
# The guard's tolerance for a late packet (GUARD_DEVICE_CLOCK_MAX_REORDER_S).
TOLERANCE_MS = 10_000


@pytest.fixture
def db():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def org(db):
    suffix = uuid.uuid4().hex[:8]
    o = models.Organization(name=f"pytest stale {suffix}", slug=f"pytest-stale-{suffix}")
    db.add(o)
    db.commit()
    db.refresh(o)
    yield o
    db.rollback()
    for table in (models.Incident, models.TelemetryLog, models.Drone):
        db.query(table).filter(table.organization_id == o.id).delete(synchronize_session=False)
    db.commit()
    purge_audit_logs(db, o.id)
    db.query(models.Organization).filter(models.Organization.id == o.id).delete(synchronize_session=False)
    db.commit()


@pytest.fixture
def client(org, monkeypatch):
    from routers import telemetry

    monkeypatch.setattr(telemetry.settings, "DRONE_API_KEY", SHARED)
    monkeypatch.setattr(telemetry.settings, "DEVICE_SHARED_KEY_ENABLED", True)
    monkeypatch.setattr(telemetry.settings, "INGEST_REJECT_STALE", True)
    app.dependency_overrides[get_tenant_context] = lambda: TenantContext(
        user_id=1, username="pytest.operator", organization_id=org.id, role="admin",
    )
    yield TestClient(app)
    app.dependency_overrides.pop(get_tenant_context, None)


def _send(client, drone_id: str, sample_ms: int | None, sequence: int = 1):
    packet = {
        "drone_id": drone_id, "latitude": 34.0522, "longitude": -118.2437, "altitude": 120.0,
        "speed": 15.0, "heading": 90.0, "battery": 90.0, "flight_mode": "AUTO",
        "armed_status": True, "satellites": 12, "packet_sequence": sequence,
    }
    if sample_ms is not None:
        packet["sample_time_ms"] = sample_ms
    return client.post("/telemetry/ingest", json=packet, headers={"X-Drone-API-Key": SHARED})


def _stored(db, org_id: int, drone_id: str) -> list[int | None]:
    db.expire_all()
    rows = (
        db.query(models.TelemetryLog.sample_time_ms)
        .filter_by(organization_id=org_id, drone_id=drone_id)
        .all()
    )
    return sorted((r[0] for r in rows), key=lambda v: -1 if v is None else v)


def _drone() -> str:
    return f"stale-{uuid.uuid4().hex[:6]}"


class TestTheRule:
    def test_in_order_telemetry_is_accepted(self, client, db, org):
        drone = _drone()
        for i, ms in enumerate((100_000, 101_000, 102_000), start=1):
            assert _send(client, drone, ms, i).status_code == 200
        assert _stored(db, org.id, drone) == [100_000, 101_000, 102_000]

    def test_a_packet_a_minute_behind_is_refused_with_503_and_not_stored(self, client, db, org):
        drone = _drone()
        assert _send(client, drone, 100_000).status_code == 200
        before = INGEST.labels("rejected_stale")._value.get()

        late = _send(client, drone, 40_000, 2)

        assert late.status_code == 503, late.text
        assert late.headers["retry-after"] == "1", "a 503 without Retry-After gives the sender nothing to act on"
        assert "do not resend" in late.json()["detail"]
        assert INGEST.labels("rejected_stale")._value.get() == before + 1
        assert _stored(db, org.id, drone) == [100_000]

    def test_reordering_the_guard_can_rate_is_accepted(self, client, db, org):
        # A few seconds out of order is ordinary jitter; the guard pairs such a
        # packet with its real neighbour on the device clock.
        drone = _drone()
        assert _send(client, drone, 100_000).status_code == 200
        assert _send(client, drone, 100_000 - TOLERANCE_MS + 500, 2).status_code == 200

    def test_a_reboot_is_not_refused(self, client, db, org):
        """A reset steps the clock back by the whole uptime, and takes time.

        Measured against packets delivered moments ago, a step back is a late
        packet. Against packets delivered a while ago it may be a reboot, and
        refusing it would lock a restarted drone out.
        """
        drone = _drone()
        db.add(
            models.TelemetryLog(
                organization_id=org.id, drone_id=drone, latitude=34.0, longitude=-118.0,
                altitude=120.0, speed=15.0, battery=90.0, packet_sequence=1,
                sample_time_ms=3_600_000, created_at=datetime.now(UTC) - timedelta(seconds=5),
            )
        )
        db.commit()
        assert _send(client, drone, 1_200, 2).status_code == 200

    def test_a_late_packet_after_a_pause_is_refused(self, client, db, org):
        """The drain: fresh traffic has stopped, the backlog is still arriving.

        Four seconds since the drone's last delivery is long enough for a
        reboot by the gap alone, but this clock shows two minutes of uptime; a
        restarted clock would show at most four seconds and change. Let
        through, the detector rated exactly this on arrival time and filed a
        false GPS_SPOOFING incident per drone (load test, 2026-09-24).
        """
        drone = _drone()
        db.add(
            models.TelemetryLog(
                organization_id=org.id, drone_id=drone, latitude=34.0, longitude=-118.0,
                altitude=120.0, speed=15.0, battery=90.0, packet_sequence=1,
                sample_time_ms=180_000, created_at=datetime.now(UTC) - timedelta(seconds=4),
            )
        )
        db.commit()
        assert _send(client, drone, 120_000, 2).status_code == 503

    def test_a_packet_without_a_device_clock_is_not_judged(self, client, db, org):
        drone = _drone()
        assert _send(client, drone, 100_000).status_code == 200
        assert _send(client, drone, None, 2).status_code == 200

    def test_the_first_packet_has_nothing_to_be_late_against(self, client, db, org):
        assert _send(client, _drone(), 5).status_code == 200

    def test_only_the_same_drone_counts(self, client, db, org):
        ahead, behind = _drone(), _drone()
        assert _send(client, ahead, 500_000).status_code == 200
        assert _send(client, behind, 1_000).status_code == 200

    def test_another_organizations_drone_of_the_same_name_does_not_count(self, client, db, org):
        drone = _drone()
        suffix = uuid.uuid4().hex[:8]
        other = models.Organization(name=f"pytest stale other {suffix}", slug=f"pytest-stale-o-{suffix}")
        db.add(other)
        db.commit()
        try:
            db.add(
                models.TelemetryLog(
                    organization_id=other.id, drone_id=drone, latitude=34.0, longitude=-118.0,
                    altitude=120.0, speed=15.0, battery=90.0, packet_sequence=1, sample_time_ms=900_000,
                )
            )
            db.commit()
            assert _send(client, drone, 1_000).status_code == 200
        finally:
            db.rollback()
            db.query(models.TelemetryLog).filter_by(organization_id=other.id).delete()
            db.query(models.Organization).filter_by(id=other.id).delete()
            db.commit()

    def test_it_can_be_turned_off(self, client, db, org, monkeypatch):
        from routers import telemetry

        monkeypatch.setattr(telemetry.settings, "INGEST_REJECT_STALE", False)
        drone = _drone()
        assert _send(client, drone, 100_000).status_code == 200
        assert _send(client, drone, 40_000, 2).status_code == 200


class TestItIsTheGuardsOwnQuestion:
    def _declined(self) -> float:
        return GUARD_DECLINED.labels(kinematic_guard.NOTE_ARRIVAL_UNUSABLE)._value.get()

    def test_without_it_the_guard_declines_that_packet_and_with_it_the_guard_never_sees_it(
        self, client, db, org, monkeypatch
    ):
        from routers import telemetry

        # Stored, it costs a detection cycle that returns no verdict.
        monkeypatch.setattr(telemetry.settings, "INGEST_REJECT_STALE", False)
        drone = _drone()
        assert _send(client, drone, 100_000, 1).status_code == 200
        assert _send(client, drone, 101_000, 2).status_code == 200
        before = self._declined()
        assert _send(client, drone, 40_000, 3).status_code == 200
        assert self._declined() == before + 1, "the guard should have declined the late packet"

        # Refused, the declined count stays where it was.
        monkeypatch.setattr(telemetry.settings, "INGEST_REJECT_STALE", True)
        drone = _drone()
        assert _send(client, drone, 100_000, 1).status_code == 200
        assert _send(client, drone, 101_000, 2).status_code == 200
        before = self._declined()
        assert _send(client, drone, 40_000, 3).status_code == 503
        assert self._declined() == before
