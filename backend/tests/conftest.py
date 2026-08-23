import os

import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Load env variables for testing if not set
load_dotenv()

from database import DATABASE_URL, get_db
from main import app

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
