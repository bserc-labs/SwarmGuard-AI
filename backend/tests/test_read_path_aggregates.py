"""GET /telemetry/latest and GET /incidents/stats against the real database.

Both used to read the tenant's entire table: /latest sorted every telemetry row
it held for a DISTINCT ON, /stats loaded every incident into Python. They now
use an index lookup per drone and SQL aggregates. These tests seed throwaway
organizations and assert the responses are the ones the old code produced --
for /latest, literally, by running the old DISTINCT ON statement as the oracle.

Telemetry is seeded relative to *now*, never a fixed date. The `client` fixture
runs the application's startup, which starts the retention sweep (main.py
periodic_database_cleanup); it deletes telemetry older than three days, and
would silently empty a test seeded in the past. Seeded drones keep the default
last_seen, so the heartbeat loop the same fixture starts never turns them into
incidents.
"""

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

import models
from main import app
from middleware.auth_middleware import TenantContext, get_tenant_context
from tests.conftest import engine, legacy_incident_stats, purge_audit_logs

pytestmark = pytest.mark.skipif(
    not engine.url.drivername.startswith("postgresql"),
    reason="LATERAL and pg_indexes are PostgreSQL",
)

# Read at request time, so one test can act as more than one organization.
_acting_as: dict = {"organization_id": None}


def _tenant():
    return TenantContext(
        user_id=1, username="pytest.agg", organization_id=_acting_as["organization_id"], role="admin"
    )


@pytest.fixture
def organizations(db_session):
    suffix = uuid.uuid4().hex[:8]
    orgs = [
        models.Organization(name=f"pytest agg {n} {suffix}", slug=f"pytest-agg-{n}-{suffix}")
        for n in ("a", "b")
    ]
    db_session.add_all(orgs)
    db_session.commit()
    for org in orgs:
        db_session.refresh(org)
    ids = [org.id for org in orgs]

    previous = app.dependency_overrides.get(get_tenant_context)
    app.dependency_overrides[get_tenant_context] = _tenant
    _acting_as["organization_id"] = ids[0]
    try:
        yield orgs
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_tenant_context, None)
        else:
            app.dependency_overrides[get_tenant_context] = previous

        # Children first, committed before purge_audit_logs, which opens with a rollback.
        db_session.rollback()
        for model in (models.TelemetryLog, models.Incident, models.Drone):
            db_session.query(model).filter(model.organization_id.in_(ids)).delete(
                synchronize_session=False
            )
        db_session.commit()
        for org_id in ids:
            purge_audit_logs(db_session, org_id)
        db_session.query(models.Organization).filter(models.Organization.id.in_(ids)).delete(
            synchronize_session=False
        )
        db_session.commit()


def _recent() -> datetime:
    return datetime.utcnow().replace(microsecond=0) - timedelta(minutes=10)


def _packet(org_id: int, drone_id: str, created_at: datetime, seq: int) -> models.TelemetryLog:
    return models.TelemetryLog(
        organization_id=org_id, drone_id=drone_id, latitude=1.0, longitude=2.0, altitude=10.0,
        speed=1.0, battery=90.0, packet_sequence=seq, created_at=created_at,
    )


def _seed_fleet(db_session, org_id: int, prefix: str) -> dict[str, datetime]:
    """Three reporting drones and one that never has. Returns each drone's newest timestamp."""
    base = _recent()
    names = [f"{prefix}-{n}" for n in (1, 2, 3, 4)]
    for name in names:
        db_session.add(models.Drone(organization_id=org_id, drone_id=name, status="ACTIVE"))
    newest: dict[str, datetime] = {}
    for k, name in enumerate(names[:3]):
        # The newest timestamp is inserted FIRST, so id order != time order and
        # a query that leaned on insertion order would return the wrong row.
        for i in (4, 0, 1, 2, 3):
            ts = base + timedelta(seconds=k * 10 + i)
            db_session.add(_packet(org_id, name, ts, i))
            newest[name] = max(newest.get(name, ts), ts)
    db_session.commit()
    return newest


class TestLatest:
    def test_the_newest_row_per_drone(self, db_session, client, organizations):
        org = organizations[0]
        prefix = f"UAV{uuid.uuid4().hex[:5]}"
        newest = _seed_fleet(db_session, org.id, prefix)

        body = client.get("/telemetry/latest").json()

        assert [row["drone_id"] for row in body] == sorted(newest), (
            "one row per reporting drone, in drone_id order; the drone that never "
            "reported must be absent"
        )
        for row in body:
            assert datetime.fromisoformat(row["created_at"]) == newest[row["drone_id"]]
            assert row["organization_id"] == org.id
            assert set(row) == {c.name for c in models.TelemetryLog.__table__.columns}

    def test_it_matches_the_old_distinct_on_query(self, db_session, client, organizations):
        org = organizations[0]
        _seed_fleet(db_session, org.id, f"UAV{uuid.uuid4().hex[:5]}")

        body = client.get("/telemetry/latest").json()
        oracle = db_session.execute(
            text(
                "SELECT DISTINCT ON (drone_id) id, drone_id FROM telemetry_logs "
                "WHERE organization_id = :org ORDER BY drone_id, created_at DESC, id DESC"
            ),
            {"org": org.id},
        ).fetchall()

        assert [(row["id"], row["drone_id"]) for row in body] == [tuple(r) for r in oracle]

    def test_it_is_scoped_to_the_organization(self, db_session, client, organizations):
        """Two tenants may fly the same drone_id (migration f6a7b8c9d0e1)."""
        org_a, org_b = organizations
        shared = f"SHARED{uuid.uuid4().hex[:5]}"
        base = _recent()
        for org, seq in ((org_a, 1), (org_b, 2)):
            db_session.add(models.Drone(organization_id=org.id, drone_id=shared, status="ACTIVE"))
            db_session.add(_packet(org.id, shared, base + timedelta(seconds=seq), seq))
        db_session.commit()

        for org, seq in ((org_a, 1), (org_b, 2)):
            _acting_as["organization_id"] = org.id
            rows = [r for r in client.get("/telemetry/latest").json() if r["drone_id"] == shared]
            assert len(rows) == 1
            assert rows[0]["organization_id"] == org.id
            assert rows[0]["packet_sequence"] == seq

    def test_the_composite_index_exists(self):
        with engine.connect() as conn:
            definition = conn.execute(
                text(
                    "SELECT indexdef FROM pg_indexes WHERE tablename = 'telemetry_logs' "
                    "AND indexname = 'ix_telemetry_logs_org_drone_created_at'"
                )
            ).scalar()
        assert definition is not None, "migration j0e1f2a3b4c5 has not been applied"
        assert "(organization_id, drone_id, created_at DESC)" in definition


class TestStats:
    def _incident(self, org_id: int, **fields) -> models.Incident:
        return models.Incident(**{
            "organization_id": org_id, "drone_id": "D1", "attack_type": "GPS_SPOOFING",
            "status": "NEW", "anomaly_score": 50.0, "threat_score": 50.0, "threat_level": 1,
            "severity": "MEDIUM", "priority": 50, "explanation": "seeded", **fields,
        })

    def test_the_body_matches_the_old_aggregation_with_subsecond_precision(
        self, db_session, client, organizations
    ):
        org = organizations[0]
        detected = datetime(2026, 9, 21, 10, 0, 0, 250_000)
        rows = [
            self._incident(org.id, severity="CRITICAL", status="RESOLVED", detection_time=detected,
                           resolution_time=detected + timedelta(seconds=200, milliseconds=500)),
            self._incident(org.id, drone_id="D2", severity="HIGH", detection_time=detected),
        ]
        db_session.add_all(rows)
        db_session.commit()

        body = client.get("/incidents/stats").json()
        assert body == legacy_incident_stats(rows)
        assert body["avg_resolution_time_seconds"] == 200.5

    def test_a_tenant_with_no_incidents(self, client, organizations):
        assert client.get("/incidents/stats").json() == {"total": 0}
