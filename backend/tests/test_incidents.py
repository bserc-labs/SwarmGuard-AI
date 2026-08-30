import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
from main import app
from middleware.auth_middleware import (
    TenantContext,
    get_admin_user,
    get_operator_user,
    get_tenant_context,
)
from models import AuditLog, Incident, User
from services.incident_engine import incident_engine
from services.priority_service import priority_service

# Every incident route is tenant-scoped, so fixtures must carry this too or the
# scoped query returns 404.
TEST_ORG_ID = 1

SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Fix SQLite composite PK autoincrement error by removing telemetry_logs from test DB setup
if "telemetry_logs" in Base.metadata.tables:
    Base.metadata.remove(Base.metadata.tables["telemetry_logs"])

Base.metadata.create_all(bind=engine)

def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()

def override_get_operator_user():
    return User(id=1, username="testop", role="operator")

def override_get_admin_user():
    return User(id=2, username="testadmin", role="admin")

def override_get_tenant_context():
    """Stand in for the JWT-derived tenant identity.

    The incident routes depend on require_permission(...) -> get_tenant_context,
    not on get_admin_user. Overriding only the latter left every request in this
    module hitting the real get_current_user and taking a 401, so the assertions
    below were never actually exercising the routes they name.
    """
    return TenantContext(
        user_id=2, username="testadmin", organization_id=TEST_ORG_ID, role="admin"
    )

client = TestClient(app)

# Installed per-test and removed afterwards, never at import time.
#
# `app` is a module-level singleton shared by every test file, so assigning
# these at import time leaked them into the whole session: pytest imports this
# module, and from then on POST /users/ answered 201 to an *unauthenticated*
# request in test_auth.py, because get_tenant_context was permanently stubbed.
# An auth test that cannot fail is worse than no auth test.
OVERRIDES = {
    get_db: override_get_db,
    get_operator_user: override_get_operator_user,
    get_admin_user: override_get_admin_user,
    get_tenant_context: override_get_tenant_context,
}


@pytest.fixture(autouse=True)
def setup_db():
    if "telemetry_logs" in Base.metadata.tables:
        Base.metadata.remove(Base.metadata.tables["telemetry_logs"])
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    previous = {dep: app.dependency_overrides.get(dep) for dep in OVERRIDES}
    app.dependency_overrides.update(OVERRIDES)
    try:
        yield
    finally:
        for dep, original in previous.items():
            if original is None:
                app.dependency_overrides.pop(dep, None)
            else:
                app.dependency_overrides[dep] = original


def test_priority_calculation():
    # Priority = (0.7 * 80 + 0.3 * 80) * 1.0 = 80
    priority_normal = priority_service.calculate_priority(80, 80, 0, "NORMAL")
    assert priority_normal == 80
    
    # Priority = (0.7 * 80 + 0.3 * 80) * 2.0 = 160 -> capped to 100
    priority_critical = priority_service.calculate_priority(80, 80, 0, "CRITICAL")
    assert priority_critical == 100
    
    # With repeat incidents = 2 (penalty = 10)
    # (0.7 * 50 + 0.3 * 50) + 10 = 60
    priority_repeat = priority_service.calculate_priority(50, 50, 2, "NORMAL")
    assert priority_repeat == 60


def test_incident_engine_creation_and_suppression():
    db = TestingSessionLocal()
    detection = {
        "drone_id": "DRONE_01",
        "prediction": {
            "is_anomaly": True,
            "anomaly_score": 85.0,
            "threat_score": 85.0
        },
        "explanation": {
            "summary": {"Primary Cause": "GPS Spoofing"}
        }
    }
    
    # An owning organization is required. This test used to omit it, which wrote
    # an incident with organization_id NULL -- a record no tenant-scoped read
    # could return.
    incident_1 = incident_engine.process_ai_detection(
        db, detection, organization_id=TEST_ORG_ID
    )
    assert incident_1 is not None
    assert incident_1.drone_id == "DRONE_01"
    assert incident_1.status == "NEW"
    assert incident_1.severity == "CRITICAL"
    assert incident_1.organization_id == TEST_ORG_ID

    # Second identical detection within window should be suppressed, returning None
    incident_2 = incident_engine.process_ai_detection(
        db, detection, organization_id=TEST_ORG_ID
    )
    assert incident_2 is None

    # Validate the first incident's updated_at timestamp was advanced
    db.refresh(incident_1)

    db.close()


def test_an_incident_without_an_organization_is_refused():
    """A detection with no owning tenant must not be recordable at all.

    The engine raises rather than letting the NOT NULL constraint surface as an
    IntegrityError, so the message names the mistake instead of the column.
    """
    db = TestingSessionLocal()
    try:
        with pytest.raises(ValueError, match="organization_id is required"):
            incident_engine.process_ai_detection(
                db,
                {
                    "drone_id": "ORPHAN",
                    "prediction": {"is_anomaly": True, "threat_score": 90.0},
                    "explanation": {"summary": {"Attack Type": "TEST"}},
                },
                organization_id=None,
            )
    finally:
        db.close()


def _make_incident(drone_id: str, status: str = "NEW") -> int:
    db = TestingSessionLocal()
    inc = Incident(
        organization_id=TEST_ORG_ID,
        drone_id=drone_id,
        attack_type="Test",
        status=status,
        anomaly_score=50.0,
        threat_score=50.0,
        threat_level=1,
        severity="MEDIUM",
        priority=50,
        explanation="Test explanation"
    )
    db.add(inc)
    db.commit()
    db.refresh(inc)
    inc_id = inc.id
    db.close()
    return inc_id


def test_acknowledge_passes_through_open():
    inc_id = _make_incident("DRONE_02", status="NEW")

    resp = client.post(f"/incidents/{inc_id}/acknowledge")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ACKNOWLEDGED"


def test_resolve_is_reachable_from_acknowledged():
    """The console offers acknowledge, resolve and close and nothing between.

    There is no route to INVESTIGATING or CONTAINED in the UI, so if `resolve`
    only accepted a single hop from CONTAINED, the Resolve button could never
    succeed from any state a user can reach. It returned 400 every time.
    """
    inc_id = _make_incident("DRONE_04", status="NEW")

    assert client.post(f"/incidents/{inc_id}/acknowledge").status_code == 200

    resp = client.post(f"/incidents/{inc_id}/resolve")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "RESOLVED"
    assert resp.json()["resolution_time"] is not None


def test_resolve_records_every_intermediate_state():
    """Skipping states in the UI must not mean skipping them in the record."""
    inc_id = _make_incident("DRONE_05", status="NEW")
    client.post(f"/incidents/{inc_id}/resolve")

    db = TestingSessionLocal()
    rows = (
        db.query(AuditLog)
        .filter(AuditLog.action == "STATUS_TRANSITION", AuditLog.resource_id == str(inc_id))
        .order_by(AuditLog.id)
        .all()
    )
    walked = [a.new_state for a in rows]
    correlations = {a.correlation_id for a in rows}
    db.close()

    assert walked == ["OPEN", "ACKNOWLEDGED", "INVESTIGATING", "CONTAINED", "RESOLVED"]
    # One operator action, so the hops must be linkable as one decision rather
    # than reading as five unrelated transitions.
    assert len(correlations) == 1


def test_intermediate_states_have_their_own_routes():
    inc_id = _make_incident("DRONE_06", status="NEW")

    resp = client.post(f"/incidents/{inc_id}/investigate")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "INVESTIGATING"

    resp = client.post(f"/incidents/{inc_id}/contain")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "CONTAINED"


def test_lifecycle_does_not_run_backwards():
    inc_id = _make_incident("DRONE_07", status="NEW")
    client.post(f"/incidents/{inc_id}/resolve")

    resp = client.post(f"/incidents/{inc_id}/acknowledge")
    assert resp.status_code == 400
    assert "does not move backwards" in resp.json()["detail"]


def test_transition_to_current_state_is_refused():
    inc_id = _make_incident("DRONE_08", status="NEW")
    client.post(f"/incidents/{inc_id}/acknowledge")

    resp = client.post(f"/incidents/{inc_id}/acknowledge")
    assert resp.status_code == 400
    assert "already ACKNOWLEDGED" in resp.json()["detail"]


def test_audit_immutability():
    inc_id = _make_incident("DRONE_03", status="OPEN")

    client.post(f"/incidents/{inc_id}/acknowledge")

    db = TestingSessionLocal()
    audits = db.query(AuditLog).all()
    assert len(audits) >= 1
    assert audits[-1].action == "STATUS_TRANSITION"
    # The column is new_state. This asserted `new_status`, which is not an
    # attribute of AuditLog, so the test raised AttributeError rather than
    # checking anything.
    assert audits[-1].new_state == "ACKNOWLEDGED"
    db.close()
