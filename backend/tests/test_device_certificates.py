"""Client certificates on ingest: the API's half of mTLS.

nginx verifies the certificate on port 8443 and refuses anyone without one
(tests/test_nginx_config.py pins that, and that 443 cannot forge the headers).
What nginx cannot know is which drone a packet claims to be. These tests pin
the API's half: a certificate for one drone cannot carry another's telemetry,
and with DEVICE_MTLS_REQUIRED a device key alone is no longer enough.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

import models
from main import app
from middleware.auth_middleware import TenantContext, get_tenant_context
from services import device_certificates as certs
from tests.conftest import TestingSessionLocal, purge_audit_logs
from utils.metrics import DEVICE_CERT

SHARED = "s" * 64


class TestParseDn:
    def test_nginx_rfc2253_form(self):
        assert certs.parse_dn("CN=drone-7,O=org:3") == {"CN": ["drone-7"], "O": ["org:3"]}

    def test_an_escaped_comma_is_part_of_the_value(self):
        # Otherwise `CN=drone-7\,O=org:1` would smuggle in a second O.
        assert certs.parse_dn(r"CN=drone-7\,O=org:1,O=org:3") == {"CN": ["drone-7,O=org:1"], "O": ["org:3"]}

    def test_repeated_attributes_are_all_kept(self):
        assert certs.parse_dn("CN=a+CN=b,O=org:3")["CN"] == ["a", "b"]


def _headers(subject: str | None, verify: str = "SUCCESS") -> dict[str, str]:
    headers = {"X-Device-Cert-Verify": verify, "X-Device-Cert-Serial": "1000"}
    if subject is not None:
        headers["X-Device-Cert-Subject"] = subject
    return headers


class TestCheck:
    def _check(self, headers, org=3, drone="drone-7"):
        # Starlette lower-cases header names; so does this.
        return certs.check({k.lower(): v for k, v in headers.items()}, organization_id=org, drone_id=drone)

    def test_the_drones_own_certificate(self):
        result = self._check(_headers("CN=drone-7,O=org:3"))
        assert result.outcome == certs.VERIFIED and result.serial == "1000"

    def test_another_drones_certificate(self):
        assert self._check(_headers("CN=drone-8,O=org:3")).outcome == certs.MISMATCH

    def test_another_organizations_certificate(self):
        assert self._check(_headers("CN=drone-7,O=org:4")).outcome == certs.MISMATCH

    def test_two_common_names_are_not_one_drone(self):
        assert self._check(_headers("CN=drone-7+CN=drone-8,O=org:3")).outcome == certs.MISMATCH

    def test_no_headers_is_absent(self):
        assert self._check({}).outcome == certs.ABSENT

    def test_anything_but_success_is_absent_not_a_softer_yes(self):
        for verify in ("NONE", "FAILED:certificate revoked", ""):
            assert self._check(_headers("CN=drone-7,O=org:3", verify)).outcome == certs.ABSENT


# ------------------------------------------------------------- through the app
@pytest.fixture
def org():
    db = TestingSessionLocal()
    suffix = uuid.uuid4().hex[:8]
    o = models.Organization(name=f"pytest mtls {suffix}", slug=f"pytest-mtls-{suffix}")
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
    db.close()


@pytest.fixture
def client(org, monkeypatch):
    from routers import telemetry

    monkeypatch.setattr(telemetry.settings, "DRONE_API_KEY", SHARED)
    monkeypatch.setattr(telemetry.settings, "DEVICE_SHARED_KEY_ENABLED", True)
    monkeypatch.setattr(telemetry.settings, "DEVICE_MTLS_REQUIRED", False)
    app.dependency_overrides[get_tenant_context] = lambda: TenantContext(
        user_id=1, username="pytest.operator", organization_id=org.id, role="admin",
    )
    yield TestClient(app)
    app.dependency_overrides.pop(get_tenant_context, None)


def _send(client, drone: str, headers: dict[str, str] | None = None):
    packet = {
        "drone_id": drone, "latitude": 34.0, "longitude": -118.0, "altitude": 100.0,
        "speed": 15.0, "heading": 90.0, "battery": 90.0, "flight_mode": "AUTO",
        "armed_status": True, "satellites": 12, "packet_sequence": 1,
    }
    return client.post("/telemetry/ingest", json=packet, headers={"X-Drone-API-Key": SHARED, **(headers or {})})


def _audit_reasons(org_id: int) -> list[str]:
    db = TestingSessionLocal()
    try:
        rows = db.query(models.AuditLog).filter_by(organization_id=org_id, action="TELEMETRY_DEVICE_AUTH_FAILED")
        return [r.reason for r in rows]
    finally:
        db.close()


class TestTheRoute:
    def test_a_verified_certificate_for_the_drone_is_accepted_and_counted(self, client, org):
        drone = f"mtls-{uuid.uuid4().hex[:6]}"
        before = DEVICE_CERT.labels(certs.VERIFIED)._value.get()
        response = _send(client, drone, _headers(f"CN={drone},O=org:{org.id}"))
        assert response.status_code == 200, response.text
        assert DEVICE_CERT.labels(certs.VERIFIED)._value.get() == before + 1

    def test_a_certificate_for_another_drone_is_refused_and_audited_even_when_not_required(self, client, org):
        drone = f"mtls-{uuid.uuid4().hex[:6]}"
        response = _send(client, drone, _headers(f"CN=someone-else,O=org:{org.id}"))
        assert response.status_code == 403
        assert certs.FOR_OTHER_DRONE in _audit_reasons(org.id)

    def test_without_a_certificate_a_device_key_is_enough_until_it_is_required(self, client, org, monkeypatch):
        from routers import telemetry

        drone = f"mtls-{uuid.uuid4().hex[:6]}"
        before = DEVICE_CERT.labels(certs.ABSENT)._value.get()
        assert _send(client, drone).status_code == 200
        assert DEVICE_CERT.labels(certs.ABSENT)._value.get() == before + 1, "the migration metric must move"

        monkeypatch.setattr(telemetry.settings, "DEVICE_MTLS_REQUIRED", True)
        refused = _send(client, drone)
        assert refused.status_code == 403
        assert "client certificate" in refused.json()["detail"]
        assert certs.REQUIRED in _audit_reasons(org.id)

        # Through the device port it still works.
        assert _send(client, drone, _headers(f"CN={drone},O=org:{org.id}")).status_code == 200

    def test_a_certificate_does_not_replace_the_device_key(self, client, org):
        # mTLS is added to the key, not swapped for it: a stolen certificate
        # alone is not enough either.
        drone = f"mtls-{uuid.uuid4().hex[:6]}"
        headers = {**_headers(f"CN={drone},O=org:{org.id}"), "X-Drone-API-Key": "wrong"}
        packet = {
            "drone_id": drone, "latitude": 34.0, "longitude": -118.0, "altitude": 100.0,
            "speed": 15.0, "heading": 90.0, "battery": 90.0, "flight_mode": "AUTO",
            "armed_status": True, "satellites": 12, "packet_sequence": 1,
        }
        assert client.post("/telemetry/ingest", json=packet, headers=headers).status_code == 403
