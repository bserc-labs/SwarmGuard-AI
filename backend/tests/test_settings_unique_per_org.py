"""system_settings holds exactly one row per organization.

The model has declared this since sprint 7; the database did not enforce it
until migration i9d0e1f2a3b4. That mattered more than a tidy-schema point:
resolve_thresholds reads this row with .first() and no ORDER BY to decide an
incident's severity, so with two rows a tenant's detections were graded against
whichever one the planner returned.

Requires PostgreSQL: pg_indexes, and a foreign key that is actually enforced.
"""

import uuid

import pytest
from sqlalchemy import insert, text
from sqlalchemy.exc import IntegrityError

import models
from routers.settings import get_or_create_settings
from tests.conftest import TestingSessionLocal, engine

INDEX_NAME = "ix_system_settings_organization_id"

pytestmark = pytest.mark.skipif(
    not engine.url.drivername.startswith("postgresql"),
    reason="schema-level constraints are only enforced on PostgreSQL",
)


@pytest.fixture
def organization(db_session):
    suffix = uuid.uuid4().hex[:8]
    org = models.Organization(name=f"pytest settings {suffix}", slug=f"pytest-set-{suffix}")
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)

    yield org

    db_session.rollback()
    db_session.query(models.SystemSettings).filter(
        models.SystemSettings.organization_id == org.id
    ).delete(synchronize_session=False)
    db_session.commit()
    db_session.query(models.Organization).filter(
        models.Organization.id == org.id
    ).delete(synchronize_session=False)
    db_session.commit()


def _count(org_id: int) -> int:
    session = TestingSessionLocal()
    try:
        return (
            session.query(models.SystemSettings)
            .filter(models.SystemSettings.organization_id == org_id)
            .count()
        )
    finally:
        session.close()


def test_the_unique_index_exists_by_name():
    with engine.connect() as conn:
        definition = conn.execute(
            text("SELECT indexdef FROM pg_indexes WHERE tablename = 'system_settings' AND indexname = :n"),
            {"n": INDEX_NAME},
        ).scalar()

    assert definition is not None, f"{INDEX_NAME} is missing; the model declares it and nothing created it"
    assert "UNIQUE" in definition.upper()
    assert "(organization_id)" in definition


def test_a_second_settings_row_for_one_organization_is_rejected(db_session, organization):
    db_session.add(models.SystemSettings(organization_id=organization.id))
    db_session.commit()

    db_session.add(models.SystemSettings(organization_id=organization.id))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_get_or_create_returns_the_same_row_every_time(db_session, organization):
    first = get_or_create_settings(db_session, organization.id)
    second = get_or_create_settings(db_session, organization.id)
    assert first.id == second.id
    assert _count(organization.id) == 1


def test_a_lost_insert_race_adopts_the_winners_row(db_session, organization, monkeypatch):
    """Two first requests for one organization both miss the SELECT.

    The index lets exactly one INSERT through. The loser must come back with
    the winner's row -- not a 500, and not a second row.
    """
    original_add = db_session.add

    def add_after_the_other_request_commits(instance):
        # The competing request wins between our SELECT and our INSERT.
        other = TestingSessionLocal()
        try:
            other.execute(
                insert(models.SystemSettings).values(
                    organization_id=organization.id, critical_threshold=0.5, high_threshold=0.3
                )
            )
            other.commit()
        finally:
            other.close()
        original_add(instance)

    monkeypatch.setattr(db_session, "add", add_after_the_other_request_commits)

    settings = get_or_create_settings(db_session, organization.id)
    assert settings.critical_threshold == 0.5, "must return the row that won the race"
    assert _count(organization.id) == 1


def test_a_foreign_key_failure_is_not_mistaken_for_the_race(db_session):
    """The race handler re-selects; finding nothing, it must re-raise rather than return None."""
    with pytest.raises(IntegrityError):
        get_or_create_settings(db_session, -1)
    db_session.rollback()
