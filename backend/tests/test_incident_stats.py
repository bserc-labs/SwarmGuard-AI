"""GET /incidents/stats aggregates in SQL; the JSON must not have moved.

The route used to load every incident of the organization -- shap_values JSON,
explanation text and all -- and count in a Python loop. Incidents are never
deleted, so that request grew without bound. It now runs five aggregate
queries. Every assertion compares the whole body against the old loop, kept
verbatim as an oracle in conftest.legacy_incident_stats.

On in-memory SQLite, creating only the one table it needs (see
test_incident_suppression.py for why the shared metadata is left alone). This
is also the proof that the new SQL is portable: `extract("epoch")` must compile
on SQLite because other SQLite-backed modules reach this route.
"""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import get_db
from main import app
from middleware.auth_middleware import TenantContext, get_tenant_context
from tests.conftest import legacy_incident_stats

ORG = 1
TABLES = [models.Incident.__table__]

engine = create_engine(
    "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _db():
    session = Session()
    try:
        yield session
    finally:
        session.close()


def _tenant():
    return TenantContext(user_id=1, username="pytest.stats", organization_id=ORG, role="admin")


@pytest.fixture
def client():
    models.Base.metadata.drop_all(bind=engine, tables=TABLES)
    models.Base.metadata.create_all(bind=engine, tables=TABLES)

    # Installed per-test and restored afterwards: `app` is shared by every test
    # module, and conftest has already pointed get_db at PostgreSQL.
    overrides = {get_db: _db, get_tenant_context: _tenant}
    previous = {dep: app.dependency_overrides.get(dep) for dep in overrides}
    app.dependency_overrides.update(overrides)
    try:
        yield TestClient(app)
    finally:
        for dep, original in previous.items():
            if original is None:
                app.dependency_overrides.pop(dep, None)
            else:
                app.dependency_overrides[dep] = original


def seed(**fields) -> models.Incident:
    session = Session()
    incident = models.Incident(**{
        "organization_id": ORG, "attack_type": "GPS_SPOOFING", "status": "NEW",
        "anomaly_score": 50.0, "threat_score": 50.0, "threat_level": 1,
        "severity": "MEDIUM", "priority": 50, "explanation": "seeded", **fields,
    })
    session.add(incident)
    session.commit()
    session.refresh(incident)
    session.expunge(incident)
    session.close()
    return incident


def at(hour: int, minute: int = 0, second: int = 0) -> datetime:
    # Whole seconds: SQLite's epoch extraction is integral.
    return datetime(2026, 9, 21, hour, minute, second)


def test_the_body_matches_the_old_python_aggregation(client):
    mine = [
        seed(drone_id="DRONE_A", severity="CRITICAL", status="RESOLVED",
             detection_time=at(10), resolution_time=at(10, 5)),          # 300 s
        seed(drone_id="DRONE_A", severity="HIGH", status="CLOSED",
             detection_time=at(11), resolution_time=at(11, 0, 45)),      # 45 s
        seed(drone_id="DRONE_B", severity="MEDIUM", status="NEW",
             attack_type="SIGNAL_JAMMING", detection_time=at(12)),
        # A severity outside the four tiers is appended after them, as before.
        seed(drone_id="DRONE_C", severity="INFO", status="ACKNOWLEDGED",
             attack_type="GEOFENCE_BREACH", detection_time=at(13)),
    ]
    # Another tenant's incident must not be counted.
    seed(organization_id=ORG + 1, drone_id="OTHER", severity="CRITICAL", status="RESOLVED",
         detection_time=at(10), resolution_time=at(20))

    body = client.get("/incidents/stats").json()

    assert body == legacy_incident_stats(mine)
    assert list(body) == [
        "total", "by_severity", "by_status", "by_threat_type", "by_drone",
        "avg_resolution_time_seconds",
    ]
    assert body["total"] == 4
    assert body["by_severity"] == {"CRITICAL": 1, "HIGH": 1, "MEDIUM": 1, "LOW": 0, "INFO": 1}
    assert body["by_drone"] == {"DRONE_A": 2, "DRONE_B": 1, "DRONE_C": 1}
    assert body["avg_resolution_time_seconds"] == 172.5


def test_an_empty_tenant_gets_only_the_total(client):
    assert client.get("/incidents/stats").json() == {"total": 0}


def test_nothing_resolved_reports_zero_seconds(client):
    """Integer 0, not null: the dashboard tests this value for falsiness."""
    mine = [seed(drone_id="DRONE_A", status="NEW", detection_time=at(10))]
    body = client.get("/incidents/stats").json()
    assert body["avg_resolution_time_seconds"] == 0
    assert body == legacy_incident_stats(mine)


def test_an_incident_missing_one_timestamp_is_left_out_of_the_average(client):
    mine = [
        seed(drone_id="DRONE_A", status="RESOLVED", detection_time=at(10), resolution_time=at(10, 1)),
        seed(drone_id="DRONE_B", status="RESOLVED", detection_time=at(11), resolution_time=None),
    ]
    body = client.get("/incidents/stats").json()
    assert body["avg_resolution_time_seconds"] == 60.0
    assert body == legacy_incident_stats(mine)
