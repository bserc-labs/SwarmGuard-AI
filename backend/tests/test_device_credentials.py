"""Per-device ingest credentials.

One shared DRONE_API_KEY used to authenticate every drone in every
organization: one lost airframe was the whole fleet's key, with no way to
revoke it short of re-keying everything at once. These tests pin the
replacement -- a key per drone, stored as a digest, bound to one drone in one
organization, revocable on its own -- and that the shared key keeps working
until it is deliberately turned off.
"""

import inspect
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import models
from main import app
from middleware.auth_middleware import TenantContext, get_tenant_context
from services import device_credentials as dc
from tests.conftest import TestingSessionLocal, purge_audit_logs
from utils.metrics import DEVICE_AUTH

SHARED = "s" * 64


def _new_org(db, tag: str) -> models.Organization:
    suffix = uuid.uuid4().hex[:8]
    org = models.Organization(name=f"pytest {tag} {suffix}", slug=f"pytest-{tag}-{suffix}")
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def _drop_org(db, org_id: int) -> None:
    db.rollback()
    db.query(models.DeviceCredential).filter(models.DeviceCredential.organization_id == org_id).delete()
    db.query(models.TelemetryLog).filter(models.TelemetryLog.organization_id == org_id).delete()
    db.query(models.Drone).filter(models.Drone.organization_id == org_id).delete()
    db.commit()
    purge_audit_logs(db, org_id)
    db.query(models.Organization).filter(models.Organization.id == org_id).delete()
    db.commit()


@pytest.fixture
def db():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def org(db):
    o = _new_org(db, "devkey")
    yield o
    _drop_org(db, o.id)


@pytest.fixture
def other_org(db):
    o = _new_org(db, "devkey-other")
    yield o
    _drop_org(db, o.id)


def _auth(db, key, org_id, drone="D1", *, enabled=True, now=None):
    return dc.authenticate(db, key, organization_id=org_id, drone_id=drone,
                           shared_key=SHARED, shared_key_enabled=enabled, now=now)


class TestTheKey:
    def test_it_is_long_random_and_recognisable(self):
        a, b = dc.generate_key(), dc.generate_key()
        assert a != b and a.startswith("sgd_") and len(a) >= 40

    def test_only_its_digest_is_stored(self, db, org):
        credential, key = dc.issue(db, organization_id=org.id, drone_id="D1", issued_by="t", label=None)
        db.commit()
        row = db.get(models.DeviceCredential, credential.id)
        stored = [str(v) for v in vars(row).values()]
        assert key not in stored, "the plaintext key reached the database"
        assert row.key_hash == dc.digest(key) and len(row.key_hash) == 64
        assert row.key_prefix == key[:12]


class TestAuthenticate:
    def test_a_drones_own_key_is_accepted(self, db, org):
        _, key = dc.issue(db, organization_id=org.id, drone_id="D1", issued_by="t", label=None)
        db.commit()
        result = _auth(db, key, org.id, "D1")
        assert result.ok and result.method == "device_key"

    def test_it_is_refused_for_another_drone(self, db, org):
        """A key is bound to one airframe; it cannot vouch for a neighbour."""
        _, key = dc.issue(db, organization_id=org.id, drone_id="D1", issued_by="t", label=None)
        db.commit()
        assert _auth(db, key, org.id, "D2").reason == dc.WRONG_DRONE

    def test_another_organizations_key_looks_exactly_like_an_unknown_one(self, db, org, other_org):
        _, key = dc.issue(db, organization_id=other_org.id, drone_id="D1", issued_by="t", label=None)
        db.commit()
        assert _auth(db, key, org.id, "D1").reason == dc.UNKNOWN
        assert _auth(db, "sgd_" + "x" * 43, org.id, "D1").reason == dc.UNKNOWN

    def test_a_revoked_key_stops_working_and_the_drones_other_key_does_not(self, db, org):
        old, old_key = dc.issue(db, organization_id=org.id, drone_id="D1", issued_by="t", label="old")
        _, new_key = dc.issue(db, organization_id=org.id, drone_id="D1", issued_by="t", label="new")
        db.commit()
        assert dc.revoke(old, revoked_by="t") is True
        db.commit()
        assert _auth(db, old_key, org.id).reason == dc.REVOKED
        assert _auth(db, new_key, org.id).ok, "rotation with overlap: the new key must keep working"
        assert dc.revoke(old, revoked_by="t") is False, "revoking twice does not re-date it"

    def test_missing(self, db, org):
        assert _auth(db, None, org.id).reason == dc.MISSING
        assert _auth(db, "", org.id).reason == dc.MISSING

    def test_the_shared_key_still_works_until_it_is_turned_off(self, db, org):
        assert _auth(db, SHARED, org.id).method == "shared_key"
        assert _auth(db, "wrong", org.id).reason == dc.SHARED_MISMATCH
        assert _auth(db, SHARED, org.id, enabled=False).reason == dc.SHARED_DISABLED

    def test_turning_the_shared_key_off_does_not_affect_device_keys(self, db, org):
        _, key = dc.issue(db, organization_id=org.id, drone_id="D1", issued_by="t", label=None)
        db.commit()
        assert _auth(db, key, org.id, enabled=False).ok

    def test_the_shared_key_is_compared_in_constant_time(self):
        source = inspect.getsource(dc.authenticate)
        assert "compare_digest" in source and "!= shared_key" not in source

    def test_last_used_is_recorded_at_most_once_a_minute(self, db, org):
        """A write per packet at 50 packets/s would be its own load problem."""
        credential, key = dc.issue(db, organization_id=org.id, drone_id="D1", issued_by="t", label=None)
        db.commit()
        t0 = datetime(2026, 9, 22, 12, 0, 0, tzinfo=UTC)
        _auth(db, key, org.id, now=t0)
        assert credential.last_used_at == t0
        _auth(db, key, org.id, now=t0 + timedelta(seconds=30))
        assert credential.last_used_at == t0, "updated again inside the resolution window"
        _auth(db, key, org.id, now=t0 + timedelta(seconds=61))
        assert credential.last_used_at == t0 + timedelta(seconds=61)


# ------------------------------------------------------------- through the app

def _packet(drone_id: str) -> dict:
    return {
        "drone_id": drone_id, "latitude": 34.0, "longitude": -118.0, "altitude": 100.0,
        "speed": 15.0, "heading": 90.0, "battery": 90.0, "flight_mode": "AUTO",
        "armed_status": True, "satellites": 12, "packet_sequence": 1,
    }


@pytest.fixture
def as_role(org):
    def _as(role: str, organization_id: int | None = None):
        app.dependency_overrides[get_tenant_context] = lambda: TenantContext(
            user_id=1, username=f"pytest.{role}", organization_id=organization_id or org.id, role=role,
        )
        return TestClient(app)

    yield _as
    app.dependency_overrides.pop(get_tenant_context, None)


def _audit(org_id: int, action: str) -> list[models.AuditLog]:
    fresh = TestingSessionLocal()
    try:
        return fresh.query(models.AuditLog).filter_by(organization_id=org_id, action=action).all()
    finally:
        fresh.close()


class TestTheRoutes:
    def test_issue_use_list_revoke_end_to_end(self, as_role, org):
        client = as_role("admin")
        drone = f"pytest-{uuid.uuid4().hex[:6]}"

        issued = client.post(f"/drones/{drone}/credentials", json={"label": "airframe 7"})
        assert issued.status_code == 201, issued.text
        body = issued.json()
        key = body["key"]
        assert key.startswith("sgd_") and body["key_prefix"] == key[:12] and body["label"] == "airframe 7"
        assert _audit(org.id, "DEVICE_CREDENTIAL_ISSUED")

        before = DEVICE_AUTH.labels("device_key")._value.get()
        ok = client.post("/telemetry/ingest", json=_packet(drone), headers={"X-Drone-API-Key": key})
        assert ok.status_code == 200, ok.text
        assert DEVICE_AUTH.labels("device_key")._value.get() == before + 1

        listed = client.get(f"/drones/{drone}/credentials")
        assert listed.status_code == 200
        (row,) = listed.json()
        assert "key" not in row and "key_hash" not in row, "a listing must never carry the key or its digest"
        assert row["last_used_at"] is not None, "the successful ingest should have marked it used"

        revoked = client.delete(f"/drones/{drone}/credentials/{body['id']}")
        assert revoked.status_code == 200 and revoked.json()["revoked_at"] is not None
        assert _audit(org.id, "DEVICE_CREDENTIAL_REVOKED")

        refused = client.post("/telemetry/ingest", json=_packet(drone), headers={"X-Drone-API-Key": key})
        assert refused.status_code == 403
        reasons = [r.reason for r in _audit(org.id, "TELEMETRY_DEVICE_AUTH_FAILED")]
        assert dc.REVOKED in reasons

    def test_every_rejection_gets_the_same_answer(self, as_role, org):
        """Which reason applied is in the audit log, not in the response."""
        client = as_role("admin")
        drone = f"pytest-{uuid.uuid4().hex[:6]}"
        key = client.post(f"/drones/{drone}/credentials", json={}).json()["key"]
        answers = {
            client.post("/telemetry/ingest", json=_packet("someone-else"), headers={"X-Drone-API-Key": key}).json()["detail"].split("'")[0],
            client.post("/telemetry/ingest", json=_packet(drone), headers={"X-Drone-API-Key": "sgd_unknown"}).json()["detail"].split("'")[0],
            client.post("/telemetry/ingest", json=_packet(drone), headers={"X-Drone-API-Key": "wrong-shared"}).json()["detail"].split("'")[0],
            client.post("/telemetry/ingest", json=_packet(drone)).json()["detail"].split("'")[0],
        }
        assert len(answers) == 1, answers
        reasons = {r.reason for r in _audit(org.id, "TELEMETRY_DEVICE_AUTH_FAILED")}
        assert {dc.WRONG_DRONE, dc.UNKNOWN, dc.SHARED_MISMATCH, dc.MISSING} <= reasons

    def test_only_an_admin_may_issue_list_or_revoke(self, as_role, org):
        for role in ("commander", "analyst", "operator", "observer"):
            client = as_role(role)
            assert client.post("/drones/D1/credentials", json={}).status_code == 403, role
            assert client.get("/drones/D1/credentials").status_code == 403, role
            assert client.delete("/drones/D1/credentials/1").status_code == 403, role

    def test_another_tenants_credential_is_a_404(self, as_role, org, other_org):
        theirs = as_role("admin", other_org.id).post("/drones/D1/credentials", json={}).json()
        mine = as_role("admin", org.id)
        assert mine.delete(f"/drones/D1/credentials/{theirs['id']}").status_code == 404
        assert mine.get("/drones/D1/credentials").json() == []

    def test_the_shared_key_can_be_switched_off(self, as_role, org, monkeypatch):
        from routers import telemetry

        client = as_role("admin")
        monkeypatch.setattr(telemetry.settings, "DRONE_API_KEY", SHARED)
        drone = f"pytest-{uuid.uuid4().hex[:6]}"
        assert client.post("/telemetry/ingest", json=_packet(drone), headers={"X-Drone-API-Key": SHARED}).status_code == 200
        monkeypatch.setattr(telemetry.settings, "DEVICE_SHARED_KEY_ENABLED", False)
        assert client.post("/telemetry/ingest", json=_packet(drone), headers={"X-Drone-API-Key": SHARED}).status_code == 403
        assert dc.SHARED_DISABLED in {r.reason for r in _audit(org.id, "TELEMETRY_DEVICE_AUTH_FAILED")}
