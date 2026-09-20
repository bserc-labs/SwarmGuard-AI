"""The audit trail has to actually reach the database.

Every assertion here reads back through a *second* session. That is the whole
point: the defect this file exists to prevent was invisible to any check made
on the session that wrote the row. `audit_service.log()` staged an INSERT, the
route returned without committing, `get_db`'s `finally: db.close()` rolled it
back -- and a test that queried the writing session would have found the row
sitting in the identity map and passed.

Measured on the compose stack before the fix: 315 telemetry rows ingested,
0 audit rows. `tests/test_audit.py`-style coverage existed and was green
throughout, because nothing asserted durability.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError, InternalError, ProgrammingError

import models
from services.audit_service import audit_service
from tests.conftest import TestingSessionLocal, purge_audit_logs

# The trigger raises with SQLSTATE 23001 (restrict_violation). psycopg surfaces
# that as one of these depending on driver version; accept any of them rather
# than pinning a class the driver is free to change.
TRIGGER_ERRORS = (DatabaseError, InternalError, ProgrammingError)


@pytest.fixture
def organization(db_session):
    """A throwaway organization to own this test's audit rows."""
    suffix = uuid.uuid4().hex[:8]
    org = models.Organization(name=f"pytest audit {suffix}", slug=f"pytest-aud-{suffix}")
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)

    yield org

    purge_audit_logs(db_session, org.id)
    db_session.query(models.Drone).filter(
        models.Drone.organization_id == org.id
    ).delete(synchronize_session=False)
    db_session.query(models.TelemetryLog).filter(
        models.TelemetryLog.organization_id == org.id
    ).delete(synchronize_session=False)
    db_session.query(models.Organization).filter(
        models.Organization.id == org.id
    ).delete(synchronize_session=False)
    db_session.commit()


def _rows(organization_id: int, action: str | None = None) -> list[models.AuditLog]:
    """Read audit rows through a session that did not write them."""
    fresh = TestingSessionLocal()
    try:
        q = fresh.query(models.AuditLog).filter(
            models.AuditLog.organization_id == organization_id
        )
        if action is not None:
            q = q.filter(models.AuditLog.action == action)
        return q.all()
    finally:
        fresh.close()


class TestTheCommitContract:
    """`log()` stages by default and commits only when told to."""

    def test_a_staged_row_does_not_survive_a_closed_session(self, organization):
        """This is the exact shape of the ingest bug, pinned as a test."""
        writer = TestingSessionLocal()
        try:
            audit_service.log(
                db=writer,
                actor="pytest",
                action="PYTEST_STAGED_ONLY",
                organization_id=organization.id,
            )
            # No commit -- exactly what routers/telemetry.py used to do.
        finally:
            writer.close()

        assert _rows(organization.id, "PYTEST_STAGED_ONLY") == [], (
            "a staged audit row must not appear to persist; if this fails the "
            "contract changed and the ingest fix needs revisiting"
        )

    def test_commit_true_persists(self, organization):
        writer = TestingSessionLocal()
        try:
            audit_service.log(
                db=writer,
                actor="pytest",
                action="PYTEST_COMMITTED",
                organization_id=organization.id,
                commit=True,
            )
        finally:
            writer.close()

        assert len(_rows(organization.id, "PYTEST_COMMITTED")) == 1

    def test_a_caller_that_commits_afterwards_persists(self, organization):
        """The default path: the accompanying write carries the audit row."""
        writer = TestingSessionLocal()
        try:
            audit_service.log(
                db=writer,
                actor="pytest",
                action="PYTEST_CALLER_COMMITS",
                organization_id=organization.id,
            )
            writer.commit()
        finally:
            writer.close()

        assert len(_rows(organization.id, "PYTEST_CALLER_COMMITS")) == 1


class TestIngestPolicy:
    """Security events are recorded; routine traffic is not."""

    def test_a_first_seen_drone_is_recorded_once(self, db_session, organization):
        import schemas
        from services.telemetry_service import telemetry_service

        drone_id = f"pytest-{uuid.uuid4().hex[:6]}"

        def packet(seq: int) -> schemas.TelemetryPacket:
            return schemas.TelemetryPacket(
                drone_id=drone_id, latitude=34.0, longitude=-118.0, altitude=100.0,
                speed=15.0, heading=90.0, battery=90.0, flight_mode="AUTO",
                armed_status=True, satellites=12, packet_sequence=seq,
            )

        telemetry_service.process_telemetry(
            packet(1), db_session, organization_id=organization.id, actor="pytest"
        )
        telemetry_service.process_telemetry(
            packet(2), db_session, organization_id=organization.id, actor="pytest"
        )

        first_seen = _rows(organization.id, "DRONE_FIRST_SEEN")
        assert len(first_seen) == 1, (
            f"a drone should be announced once, not once per packet; got {len(first_seen)}"
        )
        assert first_seen[0].resource_id == drone_id

    def test_routine_ingest_writes_no_per_packet_audit_row(self, db_session, organization):
        """Deliberate: 50 req/s x a row per packet is ~4.3M rows a day."""
        import schemas
        from services.telemetry_service import telemetry_service

        drone_id = f"pytest-{uuid.uuid4().hex[:6]}"
        for seq in range(3):
            telemetry_service.process_telemetry(
                schemas.TelemetryPacket(
                    drone_id=drone_id, latitude=34.0, longitude=-118.0, altitude=100.0,
                    speed=15.0, heading=90.0, battery=90.0, flight_mode="AUTO",
                    armed_status=True, satellites=12, packet_sequence=seq,
                ),
                db_session,
                organization_id=organization.id,
                actor="pytest",
            )

        assert _rows(organization.id, "TELEMETRY_INGEST") == []


class TestDeviceAuthFailureIsRecorded:
    """The security event that matters most, through the real request lifecycle.

    This is the one that would have caught the original bug. It goes through the
    route, so `get_db`'s `finally: db.close()` runs exactly as it does in
    production -- which is what discarded the row before. A service-level test
    cannot see that, because it never closes the session the way the framework
    does.
    """

    @pytest.fixture
    def acting_client(self, organization):
        from fastapi.testclient import TestClient

        from main import app
        from middleware.auth_middleware import TenantContext, get_tenant_context

        # require_permission's checker resolves the tenant through
        # get_tenant_context, so overriding that is enough to authenticate.
        app.dependency_overrides[get_tenant_context] = lambda: TenantContext(
            user_id=1,
            username="pytest.device.auth",
            organization_id=organization.id,
            role="admin",
        )
        with TestClient(app) as c:
            yield c
        app.dependency_overrides.pop(get_tenant_context, None)

    def _packet(self, drone_id: str) -> dict:
        return {
            "drone_id": drone_id, "latitude": 34.0, "longitude": -118.0,
            "altitude": 100.0, "speed": 15.0, "heading": 90.0, "battery": 90.0,
            "flight_mode": "AUTO", "armed_status": True, "satellites": 12,
            "packet_sequence": 1,
        }

    def test_a_wrong_device_key_is_rejected_and_recorded(self, acting_client, organization):
        drone_id = f"pytest-{uuid.uuid4().hex[:6]}"
        response = acting_client.post(
            "/telemetry/ingest",
            json=self._packet(drone_id),
            headers={"X-Drone-Api-Key": "definitely-not-the-key"},
        )
        assert response.status_code == 403

        rows = _rows(organization.id, "TELEMETRY_DEVICE_AUTH_FAILED")
        assert len(rows) == 1, (
            "a rejected device key must leave a durable audit row; the request "
            "ends in a 403 and no later write would carry it, so this is the "
            "case that needs commit=True"
        )
        assert rows[0].resource_id == drone_id
        assert rows[0].reason == "invalid_api_key"

    def test_a_missing_device_key_is_rejected_and_recorded(self, acting_client, organization):
        drone_id = f"pytest-{uuid.uuid4().hex[:6]}"
        response = acting_client.post("/telemetry/ingest", json=self._packet(drone_id))
        assert response.status_code == 403

        rows = _rows(organization.id, "TELEMETRY_DEVICE_AUTH_FAILED")
        assert len(rows) == 1
        assert rows[0].reason == "missing_api_key"


class TestAppendOnlyEnforcement:
    """migration e5f6a7b8c9d0 -- the "immutable" claim, made true."""

    @pytest.fixture
    def a_row(self, organization):
        writer = TestingSessionLocal()
        try:
            entry = audit_service.log(
                db=writer,
                actor="pytest",
                action="PYTEST_IMMUTABLE",
                organization_id=organization.id,
                commit=True,
            )
            return entry.id
        finally:
            writer.close()

    def test_update_is_rejected(self, a_row):
        session = TestingSessionLocal()
        try:
            with pytest.raises(TRIGGER_ERRORS):
                session.execute(
                    text("UPDATE audit_logs SET action = 'TAMPERED' WHERE id = :i"),
                    {"i": a_row},
                )
                session.commit()
        finally:
            session.rollback()
            session.close()

    def test_delete_is_rejected_without_the_maintenance_flag(self, a_row):
        session = TestingSessionLocal()
        try:
            with pytest.raises(TRIGGER_ERRORS):
                session.execute(
                    text("DELETE FROM audit_logs WHERE id = :i"), {"i": a_row}
                )
                session.commit()
        finally:
            session.rollback()
            session.close()

    def test_delete_is_permitted_for_a_declared_maintenance_pass(self, a_row):
        """Retention has to remain possible, or the table becomes its own outage."""
        session = TestingSessionLocal()
        try:
            session.execute(text("SET LOCAL swarmguard.audit_maintenance = 'on'"))
            session.execute(text("DELETE FROM audit_logs WHERE id = :i"), {"i": a_row})
            session.commit()
        finally:
            session.close()

        check = TestingSessionLocal()
        try:
            assert check.get(models.AuditLog, a_row) is None
        finally:
            check.close()


def test_the_duplicate_actor_index_is_gone():
    """Two identical btree(actor) indexes were maintained on every insert."""
    session = TestingSessionLocal()
    try:
        names = {
            r[0]
            for r in session.execute(
                text("SELECT indexname FROM pg_indexes WHERE tablename = 'audit_logs'")
            )
        }
    finally:
        session.close()

    assert "ix_audit_logs_actor" in names
    assert "ix_audit_logs_username" not in names, (
        "ix_audit_logs_username is the pre-rename fossil of ix_audit_logs_actor"
    )
    assert "ix_audit_logs_created_at" in names, (
        "created_at is what routers/incidents.py orders by; it needs the index "
        "that the dropped `timestamp` column used to carry"
    )
