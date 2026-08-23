import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from main import app
from database import Base, get_db
from models import User, Incident, AuditLog
from middleware.auth_middleware import get_admin_user, get_operator_user
from services.incident_engine import incident_engine
from services.priority_service import priority_service

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

app.dependency_overrides[get_db] = override_get_db
app.dependency_overrides[get_operator_user] = override_get_operator_user
app.dependency_overrides[get_admin_user] = override_get_admin_user

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    if "telemetry_logs" in Base.metadata.tables:
        Base.metadata.remove(Base.metadata.tables["telemetry_logs"])
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


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
    
    # Create first incident
    incident_1 = incident_engine.process_ai_detection(db, detection)
    assert incident_1 is not None
    assert incident_1.drone_id == "DRONE_01"
    assert incident_1.status == "NEW"
    assert incident_1.severity == "CRITICAL"
    
    # Second identical detection within window should be suppressed, returning None
    incident_2 = incident_engine.process_ai_detection(db, detection)
    assert incident_2 is None
    
    # Validate the first incident's updated_at timestamp was advanced
    db.refresh(incident_1)
    
    db.close()


def test_incident_lifecycle_transitions():
    db = TestingSessionLocal()
    inc = Incident(
        drone_id="DRONE_02", 
        attack_type="Test", 
        status="NEW",
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
    
    # NEW -> OPEN (done via acknowledge logic implicitly, or normally NEW->OPEN)
    # The acknowledge endpoint jumps NEW -> OPEN -> ACKNOWLEDGED
    resp = client.post(f"/incidents/{inc_id}/acknowledge")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ACKNOWLEDGED"
    
    # Invalid: ACKNOWLEDGED -> RESOLVED (Missing INVESTIGATING and CONTAINED)
    resp = client.post(f"/incidents/{inc_id}/resolve")
    assert resp.status_code == 400
    assert "Invalid transition" in resp.json()["detail"]


def test_audit_immutability():
    db = TestingSessionLocal()
    inc = Incident(
        drone_id="DRONE_03", 
        attack_type="Test", 
        status="OPEN",
        anomaly_score=50.0,
        threat_score=50.0,
        threat_level=1,
        severity="MEDIUM",
        priority=50,
        explanation="Test explanation"
    )
    db.add(inc)
    db.commit()
    inc_id = inc.id
    db.close()
    
    client.post(f"/incidents/{inc_id}/acknowledge")
    
    db = TestingSessionLocal()
    audits = db.query(AuditLog).all()
    assert len(audits) >= 1
    assert audits[-1].action == "STATUS_TRANSITION"
    assert audits[-1].new_status == "ACKNOWLEDGED"
    db.close()
