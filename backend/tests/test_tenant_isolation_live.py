"""Behavioural proof that one organization cannot observe another's rows.

test_route_tenancy.py proves structurally that every tenant-scoped route
resolves a tenant and mentions organization_id. That is a strong guard against
whole categories of mistake, but it is still a proxy: a route could reference
organization_id and use it wrongly.

These tests do the real thing. Two organizations, data seeded in both, requests
made as each, and an assertion that neither can count or read the other's rows.
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
from middleware.auth_middleware import (
    TenantContext,
    get_current_user,
    get_operator_user,
    get_tenant_context,
)
from models import Drone, GeofenceZone, Incident, Organization, User

ORG_A = 1
ORG_B = 2

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Composite primary key SQLite cannot autoincrement; nothing here needs it.
if "telemetry_logs" in Base.metadata.tables:
    Base.metadata.remove(Base.metadata.tables["telemetry_logs"])

client = TestClient(app)

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


def override_get_current_user():
    return User(
        id=1,
        username=_acting_as["username"],
        role=_acting_as["role"],
        organization_id=_acting_as["organization_id"],
        token_version=0,
    )


def act_as(organization_id, role="admin", username=None):
    _acting_as.update(
        {
            "organization_id": organization_id,
            "role": role,
            "username": username or f"admin.{organization_id}",
        }
    )


@pytest.fixture(autouse=True)
def two_organizations():
    """Org A with a large fleet, Org B with a single drone and no incidents.

    The asymmetry is the point: if a count leaks, B's numbers will carry A's.
    """
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    db.add(Organization(id=ORG_A, name="Org A", slug="org-a"))
    db.add(Organization(id=ORG_B, name="Org B", slug="org-b"))

    for index in range(5):
        db.add(Drone(organization_id=ORG_A, drone_id=f"A-{index}", status="ACTIVE"))
    db.add(Drone(organization_id=ORG_B, drone_id="B-0", status="ACTIVE"))

    for index in range(3):
        db.add(
            Incident(
                organization_id=ORG_A,
                drone_id=f"A-{index}",
                attack_type="GPS_SPOOFING",
                threat_score=95.0,
                anomaly_score=95.0,
                threat_level=4,
                severity="CRITICAL",
                priority=90,
                explanation="seeded",
                status="NEW",
            )
        )

    db.add(
        GeofenceZone(
            organization_id=ORG_A,
            name="a-only",
            zone_type="CIRCLE",
            coordinates={"center": [0, 0], "radius": 100},
            severity="CRITICAL",
            is_active=True,
        )
    )
    db.commit()
    db.close()

    act_as(ORG_A)

    previous = {
        dep: app.dependency_overrides.get(dep)
        for dep in (get_db, get_tenant_context, get_current_user, get_operator_user)
    }
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_tenant_context] = override_get_tenant_context
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_operator_user] = override_get_current_user
    try:
        yield
    finally:
        for dep, original in previous.items():
            if original is None:
                app.dependency_overrides.pop(dep, None)
            else:
                app.dependency_overrides[dep] = original


# ---------------------------------------------------------- system health

class TestSystemHealthCounters:
    """The dashboard's headline numbers.

    Every count here was global: `db.query(Drone).count()` with no filter. An
    operator in Org B saw Org A's fleet size, incident total and critical count
    on the first screen after signing in.
    """

    def test_each_organization_sees_only_its_own_fleet_size(self):
        act_as(ORG_A)
        a = client.get("/system/health").json()
        act_as(ORG_B)
        b = client.get("/system/health").json()

        assert a["total_drones"] == 5
        assert b["total_drones"] == 1, (
            f"Org B sees {b['total_drones']} drones but owns 1 -- "
            "the fleet counter is not scoped to the organization."
        )

    def test_each_organization_sees_only_its_own_incident_counts(self):
        act_as(ORG_A)
        a = client.get("/system/health").json()
        act_as(ORG_B)
        b = client.get("/system/health").json()

        assert a["total_incidents"] == 3
        assert a["critical_incidents"] == 3
        assert b["total_incidents"] == 0, (
            f"Org B sees {b['total_incidents']} incidents but has none."
        )
        assert b["critical_incidents"] == 0

    def test_active_and_silent_counts_are_scoped(self):
        act_as(ORG_B)
        b = client.get("/system/health").json()
        assert b["active_drones"] == 1
        assert b["silent_drones"] == 0

    def test_health_percentage_is_derived_from_the_callers_own_data(self):
        """A tenant with no incidents must not be told its health is degraded."""
        act_as(ORG_B)
        b = client.get("/system/health").json()
        assert b["system_health_pct"] == 100, (
            "Org B has no silent drones and no critical incidents, so its health "
            f"should read 100, not {b['system_health_pct']} -- which would mean "
            "another tenant's incidents are dragging it down."
        )


# ------------------------------------------------------------- collections

class TestCollectionsAreScoped:
    def test_drone_roster(self):
        act_as(ORG_B)
        rows = client.get("/drones").json()
        assert {d["drone_id"] for d in rows} == {"B-0"}

    def test_incident_list(self):
        act_as(ORG_B)
        assert client.get("/incidents/?limit=1000").json() == []

    def test_incident_stats(self):
        act_as(ORG_B)
        assert client.get("/incidents/stats").json()["total"] == 0

    def test_geofence_zones(self):
        act_as(ORG_B)
        assert client.get("/geofence/zones").json() == []

    def test_user_roster(self):
        act_as(ORG_A)
        client.post(
            "/users/",
            json={"username": "a.analyst", "password": "a-password-1234", "role": "analyst"},
        )
        act_as(ORG_B)
        assert "a.analyst" not in {u["username"] for u in client.get("/users/").json()}


# ------------------------------------------------------------------- IDOR

class TestDirectObjectAccess:
    def test_an_incident_id_from_another_organization_is_not_readable(self):
        db = TestingSessionLocal()
        incident_id = db.query(Incident).filter(Incident.organization_id == ORG_A).first().id
        db.close()

        act_as(ORG_A)
        assert client.get(f"/incidents/{incident_id}").status_code == 200

        act_as(ORG_B)
        assert client.get(f"/incidents/{incident_id}").status_code == 404, (
            "Guessing an incident id must not expose another organization's row. "
            "404 rather than 403, so the response does not confirm it exists."
        )

    def test_transitions_on_another_organizations_incident_are_refused(self):
        db = TestingSessionLocal()
        incident_id = db.query(Incident).filter(Incident.organization_id == ORG_A).first().id
        db.close()

        act_as(ORG_B)
        for action in ("acknowledge", "investigate", "contain", "resolve", "close"):
            assert client.post(f"/incidents/{incident_id}/{action}").status_code == 404, (
                f"{action} reached another organization's incident"
            )

    def test_commands_cannot_target_another_organizations_drone(self):
        act_as(ORG_B)
        res = client.post(
            "/drones/A-0/command",
            json={"command_type": "RETURN_TO_HOME", "reason": "cross-tenant probe"},
        )
        assert res.status_code == 404

    def test_a_zone_belonging_to_another_organization_cannot_be_deleted(self):
        db = TestingSessionLocal()
        zone_id = db.query(GeofenceZone).filter(GeofenceZone.organization_id == ORG_A).first().id
        db.close()

        act_as(ORG_B)
        assert client.delete(f"/geofence/zones/{zone_id}").status_code == 404

        db = TestingSessionLocal()
        still_active = db.query(GeofenceZone).filter(GeofenceZone.id == zone_id).first().is_active
        db.close()
        assert still_active is True, "Org A's zone was deactivated by Org B"
