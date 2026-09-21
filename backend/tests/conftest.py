import os

import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Load env variables for testing if not set
load_dotenv()

import models
from database import DATABASE_URL, get_db
from main import app
from utils.limiter import limiter

# Rate limiting is off for the unit suite.
#
# /auth/login allows 5 requests per minute, keyed by client address -- which is
# the literal string "testclient" for every test in the process. Any suite with
# more than five logins therefore fails on ordering rather than behaviour, and
# because the limiter is Redis-backed the exhaustion survives the run: a second
# `pytest` within the minute failed tests that had just passed.
#
# The limit itself is still exercised, against a real server over real sockets,
# by test_sprint7_security.test_rate_limiting.
limiter.enabled = False

# Use testing DB or default to the existing DATABASE_URL
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", DATABASE_URL)

engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

@pytest.fixture(scope="session")
def setup_database():
    # We rely on Alembic to manage schemas, but for isolated test db we could run create_all
    # Since we are running against the dev/CI db which is managed by alembic, 
    # we don't recreate tables here to avoid conflicts with TimescaleDB extension creation.
    # We just return the engine.
    yield engine

@pytest.fixture(scope="function")
def db_session():
    """Provides a fresh database session for a test."""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def purge_audit_logs(db, organization_id: int) -> int:
    """Remove a throwaway organization's audit rows during teardown.

    `audit_logs` is append-only at the database level as of migration
    e5f6a7b8c9d0: a trigger rejects UPDATE outright and permits DELETE only
    when the session has announced a maintenance pass. Fixtures still need to
    clean up after themselves -- `fk_audit_org` will not let a throwaway
    organization go while its rows reference it -- so they go through here
    rather than each rediscovering the flag.

    Scoped to one organization on purpose. This must never become a way to
    clear the real audit trail.

    **It opens with a rollback**, so anything the caller has merely staged is
    discarded. Commit your own deletes before calling this, and do not
    interleave it with other teardown steps in a loop -- doing exactly that
    silently dropped a fixture's drone deletions and left its organizations
    un-deletable behind their foreign key.
    """
    db.rollback()
    db.execute(text("SET LOCAL swarmguard.audit_maintenance = 'on'"))
    deleted = (
        db.query(models.AuditLog)
        .filter(models.AuditLog.organization_id == organization_id)
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted
