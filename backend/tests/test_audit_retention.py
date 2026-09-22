"""audit_logs gets the retention policy telemetry has, without weakening immutability.

The table is append-only at the database level: UPDATE is refused outright and
DELETE only with a maintenance flag set on the session. The retention pass is
the one place in the application that sets the flag, for one statement, and
only when a retention is configured.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

import models
from services.audit_service import purge_expired_audit_logs
from tests.conftest import TestingSessionLocal, purge_audit_logs

ORG_NAME = "retention-test-org"


@pytest.fixture
def org_with_old_and_new_rows():
    db = TestingSessionLocal()
    org = models.Organization(name=ORG_NAME, slug="retention-test-org")
    db.add(org)
    db.commit()
    now = datetime.utcnow()
    rows = [
        models.AuditLog(organization_id=org.id, actor="t", action="OLD", resource="x", created_at=now - timedelta(days=400)),
        models.AuditLog(organization_id=org.id, actor="t", action="OLD", resource="x", created_at=now - timedelta(days=366)),
        models.AuditLog(organization_id=org.id, actor="t", action="NEW", resource="x", created_at=now - timedelta(days=10)),
    ]
    db.add_all(rows)
    db.commit()
    try:
        yield db, org.id
    finally:
        db.rollback()
        purge_audit_logs(db, org.id)
        db.query(models.Organization).filter(models.Organization.id == org.id).delete()
        db.commit()
        db.close()


def _count(db, org_id: int, action: str) -> int:
    return db.query(models.AuditLog).filter_by(organization_id=org_id, action=action).count()


def test_rows_older_than_the_retention_are_removed_and_newer_ones_kept(org_with_old_and_new_rows):
    db, org_id = org_with_old_and_new_rows
    assert _count(db, org_id, "OLD") == 2 and _count(db, org_id, "NEW") == 1
    deleted = purge_expired_audit_logs(db, retention_days=365)
    assert deleted >= 2
    assert _count(db, org_id, "OLD") == 0 and _count(db, org_id, "NEW") == 1


def test_a_retention_of_zero_keeps_everything(org_with_old_and_new_rows):
    db, org_id = org_with_old_and_new_rows
    assert purge_expired_audit_logs(db, retention_days=0) == 0
    assert _count(db, org_id, "OLD") == 2


def test_the_flag_does_not_outlive_the_pass(org_with_old_and_new_rows):
    """SET LOCAL: a later DELETE on the same session, without the flag, is still refused."""
    db, org_id = org_with_old_and_new_rows
    purge_expired_audit_logs(db, retention_days=365)
    with pytest.raises(Exception, match="append-only"):
        db.execute(text("DELETE FROM audit_logs WHERE organization_id = :o"), {"o": org_id})
        db.commit()
    db.rollback()
