"""The suppression check-then-insert, against a real database and real threads.

Detection runs one thread per ingested packet. Suppression is a SELECT followed
by an INSERT, so two cycles for the same drone could both find nothing and both
insert: one attack, two incidents on the operator's screen.

PostgreSQL only -- the fix is a transaction-scoped advisory lock, which SQLite
neither has nor needs.

Hygiene rules these tests follow, because the failure mode of a locking test is
a hung CI job rather than a red one: every worker thread is a daemon, every
barrier and join has a timeout, and every lock holder releases in a `finally`.
"""

import threading
import time
import uuid

import pytest

import models
from services.alert_service import alert_service
from services.incident_engine import _serialize_incident_writes, incident_engine
from tests.conftest import TestingSessionLocal, engine

_IS_POSTGRES = engine.url.drivername.startswith("postgresql")

# These used to be skipped unless the database session was UTC: the suppression
# cutoff compared a naive `detection_time` against an aware now(), so off UTC
# the window was wrong by the offset. `detection_time` is timestamptz now
# (migration m3b4c5d6e7f8) and both sides are absolute, so the session's zone
# cannot change the answer.
pytestmark = [
    pytest.mark.skipif(not _IS_POSTGRES, reason="advisory locks exist only on PostgreSQL"),
]


@pytest.fixture
def organization(db_session):
    suffix = uuid.uuid4().hex[:8]
    org = models.Organization(name=f"pytest concurrency {suffix}", slug=f"pytest-cc-{suffix}")
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)

    yield org

    db_session.rollback()
    db_session.query(models.Incident).filter(
        models.Incident.organization_id == org.id
    ).delete(synchronize_session=False)
    db_session.commit()
    db_session.query(models.Organization).filter(
        models.Organization.id == org.id
    ).delete(synchronize_session=False)
    db_session.commit()


def _detection(drone_id: str, score: float = 85.0) -> dict:
    return {
        "drone_id": drone_id,
        "prediction": {
            "is_anomaly": True, "anomaly_score": score, "threat_score": score, "threat_level": "HIGH",
        },
        "explanation": {
            "summary": {"Attack Type": "GPS_SPOOFING", "Primary Cause": "position jump"},
            "ranked_features": [],
            "metadata": {},
        },
    }


def _count(org_id: int, drone_id: str) -> int:
    session = TestingSessionLocal()
    try:
        return (
            session.query(models.Incident)
            .filter(models.Incident.organization_id == org_id, models.Incident.drone_id == drone_id)
            .count()
        )
    finally:
        session.close()


def test_two_concurrent_detections_for_one_drone_create_one_incident(organization, monkeypatch):
    drone_id = f"cc-{uuid.uuid4().hex[:6]}"

    # Widen the gap between the suppression SELECT and the INSERT so the race
    # is certain rather than occasional. Without the lock this yields two rows.
    original = alert_service.is_alert_suppressed

    def slow_check(*args, **kwargs):
        result = original(*args, **kwargs)
        time.sleep(0.3)
        return result

    monkeypatch.setattr(alert_service, "is_alert_suppressed", slow_check)

    barrier = threading.Barrier(2, timeout=10)
    errors: list[BaseException] = []

    def worker():
        session = TestingSessionLocal()
        try:
            barrier.wait()
            incident_engine.record_detection(
                session, _detection(drone_id), organization_id=organization.id
            )
        except BaseException as exc:  # surfaced on the main thread below
            errors.append(exc)
        finally:
            session.close()

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    assert not any(t.is_alive() for t in threads), "a detection thread deadlocked"
    assert not errors, errors
    assert _count(organization.id, drone_id) == 1


def test_the_lock_serialises_one_drone_and_not_another(organization):
    holder = TestingSessionLocal()
    other = TestingSessionLocal()
    acquired = threading.Event()

    def contender():
        session = TestingSessionLocal()
        try:
            _serialize_incident_writes(session, organization.id, "D1")
            acquired.set()
        finally:
            session.rollback()
            session.close()

    thread = threading.Thread(target=contender, daemon=True)
    try:
        _serialize_incident_writes(holder, organization.id, "D1")  # transaction left open
        thread.start()
        assert not acquired.wait(0.5), "the same drone was not serialised"

        # A different drone is a different key and must not wait.
        started = time.monotonic()
        _serialize_incident_writes(other, organization.id, "D2")
        assert time.monotonic() - started < 0.5, "an unrelated drone was blocked"

        holder.commit()  # releases the lock
        assert acquired.wait(5), "the lock was not released at commit"
    finally:
        holder.rollback()
        holder.close()
        other.rollback()
        other.close()
        thread.join(timeout=5)


def test_tenants_never_share_a_key(organization, db_session):
    """Same drone_id, different organization: independent critical sections."""
    suffix = uuid.uuid4().hex[:8]
    second = models.Organization(name=f"pytest concurrency b {suffix}", slug=f"pytest-ccb-{suffix}")
    db_session.add(second)
    db_session.commit()
    db_session.refresh(second)

    holder = TestingSessionLocal()
    other = TestingSessionLocal()
    try:
        _serialize_incident_writes(holder, organization.id, "SHARED")
        started = time.monotonic()
        _serialize_incident_writes(other, second.id, "SHARED")
        assert time.monotonic() - started < 0.5
    finally:
        holder.rollback()
        holder.close()
        other.rollback()
        other.close()
        db_session.query(models.Organization).filter(
            models.Organization.id == second.id
        ).delete(synchronize_session=False)
        db_session.commit()


def test_a_resolved_incident_is_followed_by_a_new_one(organization, db_session):
    """The resolved-does-not-suppress rule on the real dialect and its server clock."""
    drone_id = f"cc-{uuid.uuid4().hex[:6]}"
    first = incident_engine.process_ai_detection(
        db_session, _detection(drone_id), organization_id=organization.id
    )
    assert first is not None
    first.status = "RESOLVED"
    db_session.commit()

    second = incident_engine.process_ai_detection(
        db_session, _detection(drone_id), organization_id=organization.id
    )
    assert second is not None and second.id != first.id
    assert _count(organization.id, drone_id) == 2
