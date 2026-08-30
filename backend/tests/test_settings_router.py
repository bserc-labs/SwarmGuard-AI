"""The /settings routes: validation, tenancy, and audit.

Complements test_settings_thresholds.py, which covers how thresholds are applied
to a detection. These cover how they get in: what the API accepts, whose row it
writes, and what it records.
"""

import os
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from database import Base, get_db
from main import app
from middleware.auth_middleware import TenantContext, get_tenant_context
from models import AuditLog, Organization, SystemSettings

ORG_A = 1
ORG_B = 2

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

if "telemetry_logs" in Base.metadata.tables:
    Base.metadata.remove(Base.metadata.tables["telemetry_logs"])

client = TestClient(app)

# Which organization the request is authenticated as. Mutated per test rather
# than baked in, so one test can act as Org A and the next as Org B.
_acting_as = {"organization_id": ORG_A, "role": "admin", "username": "admin.a"}


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def override_get_tenant_context():
    return TenantContext(
        user_id=1,
        username=_acting_as["username"],
        organization_id=_acting_as["organization_id"],
        role=_acting_as["role"],
    )


@pytest.fixture(autouse=True)
def isolated_app():
    """Overrides installed and torn down per test.

    `app` is a session-wide singleton; assigning overrides at import time leaks
    them into every other test module and silently disables authentication
    there. See the comment in test_incidents.py.
    """
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    session = TestingSessionLocal()
    session.add(Organization(id=ORG_A, name="Org A", slug="org-a"))
    session.add(Organization(id=ORG_B, name="Org B", slug="org-b"))
    session.commit()
    session.close()

    _acting_as.update({"organization_id": ORG_A, "role": "admin", "username": "admin.a"})

    previous = {
        dep: app.dependency_overrides.get(dep)
        for dep in (get_db, get_tenant_context)
    }
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_tenant_context] = override_get_tenant_context
    try:
        yield
    finally:
        for dep, original in previous.items():
            if original is None:
                app.dependency_overrides.pop(dep, None)
            else:
                app.dependency_overrides[dep] = original


def act_as(organization_id, role="admin", username="admin"):
    _acting_as.update(
        {"organization_id": organization_id, "role": role, "username": username}
    )


class TestValidation:
    def test_a_valid_update_is_accepted(self):
        res = client.patch("/settings/", json={"critical_threshold": 0.7, "high_threshold": 0.4})
        assert res.status_code == 200, res.text
        assert res.json()["critical_threshold"] == 0.7

    @pytest.mark.parametrize(
        "payload",
        [
            {"critical_threshold": 1.5},   # above the 0-1 range
            {"critical_threshold": 0.0},   # zero disables the band entirely
            {"critical_threshold": -0.2},  # negative
            {"high_threshold": 42},        # a 0-100 score, not a fraction
        ],
    )
    def test_out_of_range_values_are_refused(self, payload):
        assert client.patch("/settings/", json=payload).status_code == 422

    def test_an_inverted_pair_is_refused(self):
        res = client.patch(
            "/settings/", json={"critical_threshold": 0.4, "high_threshold": 0.9}
        )
        assert res.status_code == 422

    def test_a_partial_update_that_inverts_the_bands_is_refused(self):
        """The case field-level validation alone would let through.

        Stored critical is 0.85 by default; sending only high=0.9 leaves the
        bands inverted even though 0.9 is a perfectly valid fraction.
        """
        res = client.patch("/settings/", json={"high_threshold": 0.9})
        assert res.status_code == 422
        assert "critical_threshold" in res.text

    def test_a_rejected_update_does_not_partially_apply(self):
        client.patch("/settings/", json={"critical_threshold": 0.7, "high_threshold": 0.4})
        client.patch("/settings/", json={"high_threshold": 0.9, "ui_sound": False})

        after = client.get("/settings/").json()
        assert after["high_threshold"] == 0.4
        assert after["ui_sound"] is True, "an unrelated field must not slip through"

    def test_an_unknown_refresh_rate_is_refused(self):
        assert client.patch("/settings/", json={"refresh_rate": "0.001s"}).status_code == 422


class TestTenantIsolation:
    def test_each_organization_reads_its_own_row(self):
        act_as(ORG_A)
        client.patch("/settings/", json={"critical_threshold": 0.5, "high_threshold": 0.3})

        act_as(ORG_B)
        assert client.get("/settings/").json()["critical_threshold"] == 0.85

        act_as(ORG_A)
        assert client.get("/settings/").json()["critical_threshold"] == 0.5

    def test_writing_as_one_organization_does_not_touch_another(self):
        act_as(ORG_A)
        client.patch("/settings/", json={"critical_threshold": 0.5, "high_threshold": 0.3})
        act_as(ORG_B)
        client.patch("/settings/", json={"critical_threshold": 0.95, "high_threshold": 0.9})

        session = TestingSessionLocal()
        rows = {
            s.organization_id: s.critical_threshold
            for s in session.query(SystemSettings).all()
        }
        session.close()

        assert rows == {ORG_A: 0.5, ORG_B: 0.95}

    def test_the_organization_cannot_be_named_by_the_client(self):
        """organization_id is derived from the token, never read from the body."""
        act_as(ORG_A)
        res = client.patch(
            "/settings/",
            json={"critical_threshold": 0.6, "high_threshold": 0.3, "organization_id": ORG_B},
        )
        assert res.status_code == 200

        session = TestingSessionLocal()
        org_b_row = (
            session.query(SystemSettings)
            .filter(SystemSettings.organization_id == ORG_B)
            .first()
        )
        org_a_row = (
            session.query(SystemSettings)
            .filter(SystemSettings.organization_id == ORG_A)
            .first()
        )
        session.close()

        assert org_b_row is None, "Org B's settings must not be created by Org A"
        assert org_a_row.critical_threshold == 0.6


class TestAuthorization:
    def test_a_reader_cannot_write(self):
        """settings.read without settings.manage must not permit a PATCH."""
        act_as(ORG_A, role="analyst", username="analyst.a")
        assert client.get("/settings/").status_code == 200
        assert client.patch("/settings/", json={"ui_sound": False}).status_code == 403

    def test_an_observer_cannot_write(self):
        act_as(ORG_A, role="observer", username="observer.a")
        assert client.patch("/settings/", json={"ui_sound": False}).status_code == 403


class TestAudit:
    def test_a_threshold_change_is_recorded(self):
        act_as(ORG_A, username="admin.a")
        client.patch("/settings/", json={"critical_threshold": 0.7, "high_threshold": 0.4})

        session = TestingSessionLocal()
        entry = (
            session.query(AuditLog)
            .filter(AuditLog.action == "SETTINGS_UPDATED")
            .order_by(AuditLog.id.desc())
            .first()
        )
        session.close()

        assert entry is not None, "changing detection policy must leave an audit record"
        assert entry.actor == "admin.a"
        assert entry.organization_id == ORG_A
        assert "critical_threshold=0.7" in entry.details
