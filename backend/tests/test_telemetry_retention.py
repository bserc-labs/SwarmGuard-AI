"""Telemetry retention is a TimescaleDB policy on one-day chunks, and the app checks it.

The application used to delete old telemetry itself with one unbatched DELETE
an hour. TimescaleDB drops whole chunks instead. Two facts make that mean
"three days": the policy's drop_after, and a chunk interval of one day -- on the
default 7-day chunks a 3-day policy keeps up to ten. Both are pinned here
against the real test hypertable, and the policy's own job is run to show it
drops the old and keeps the new.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

import models
from services.retention import (
    RetentionPolicyMissing,
    check_retention_policy,
    retention_policy,
)
from tests.conftest import TestingSessionLocal, engine

DRONE = "RETENTION-PROBE"


@pytest.fixture
def db():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _clear_leftovers(db) -> None:
    """A run killed mid-test never reaches its teardown; start from clean regardless."""
    db.execute(text("DELETE FROM telemetry_logs WHERE drone_id = :d"), {"d": DRONE})
    db.execute(text("DELETE FROM organizations WHERE slug = 'retention-probe-org'"))
    db.commit()


@pytest.fixture
def organization(db):
    _clear_leftovers(db)
    org = models.Organization(name="retention-probe-org", slug="retention-probe-org")
    db.add(org)
    db.commit()
    try:
        yield org
    finally:
        db.rollback()
        db.execute(text("DELETE FROM telemetry_logs WHERE drone_id = :d"), {"d": DRONE})
        db.query(models.Organization).filter(models.Organization.id == org.id).delete()
        db.commit()


class TestTheMigration:
    def test_the_policy_exists_with_three_days_checked_hourly(self, db):
        policy = retention_policy(db)
        assert policy is not None, "no retention policy on telemetry_logs"
        assert policy.drop_after == "3 days"
        assert policy.schedule_interval == timedelta(hours=1)

    def test_new_chunks_are_one_day(self, db):
        """On the default 7-day chunks, 'three days' would have meant up to ten."""
        assert retention_policy(db).chunk_interval == timedelta(days=1)

    def test_compression_is_deliberately_off(self, db):
        row = db.execute(
            text("SELECT compression_enabled FROM timescaledb_information.hypertables WHERE hypertable_name = 'telemetry_logs'")
        ).scalar()
        assert row is False


class TestThePolicyItself:
    def _row(self, organization, when: datetime) -> models.TelemetryLog:
        return models.TelemetryLog(
            organization_id=organization.id, drone_id=DRONE,
            latitude=34.0, longitude=-118.0, altitude=100.0, speed=15.0,
            battery=90.0, packet_sequence=1, created_at=when,
        )

    def test_it_drops_a_chunk_that_has_aged_out_and_keeps_the_rest(self, db, organization):
        now = datetime.now(UTC)
        db.add_all([self._row(organization, now - timedelta(days=10)), self._row(organization, now)])
        db.commit()
        assert db.execute(text("SELECT count(*) FROM telemetry_logs WHERE drone_id = :d"), {"d": DRONE}).scalar() == 2

        # The policy's own job, not a hand-written drop_chunks: a procedure with
        # its own transaction control, so it needs an autocommit connection.
        job_id = retention_policy(db).job_id
        # Dropping a chunk takes an exclusive lock on it. This session's open
        # transaction still holds a read lock from the SELECTs above, and the
        # first version of this test hung forever right here -- as would the
        # real policy behind any long-lived reader. End the transaction first,
        # and bound the wait so a lock conflict is a failure, not a hang.
        db.commit()
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.execute(text("SET lock_timeout = '10s'"))
            connection.execute(text(f"CALL run_job({job_id})"))

        remaining = db.execute(
            text("SELECT created_at FROM telemetry_logs WHERE drone_id = :d"), {"d": DRONE}
        ).scalars().all()
        assert len(remaining) == 1
        assert remaining[0] > now - timedelta(minutes=1), "the fresh row must survive"
        # Deliberately no assertion on job_stats: run_job executes the job in
        # this session and does not record a run; only the background scheduler
        # does. An earlier version asserted last_run_status == "Success" and
        # passed only when the scheduler happened to run the policy first --
        # four failures in eight runs. The rows are the proof.


class TestTheApplicationSideCheck:
    def test_it_passes_while_the_policy_is_there(self, db):
        assert check_retention_policy(db).drop_after == "3 days"

    def test_it_raises_the_moment_the_policy_is_gone_and_names_the_fix(self, db):
        """A restore from an old dump, or a hand-run remove_retention_policy."""
        db.execute(text("SELECT remove_retention_policy('telemetry_logs')"))
        db.commit()
        try:
            with pytest.raises(RetentionPolicyMissing, match="add_retention_policy"):
                check_retention_policy(db)
        finally:
            db.execute(text(
                "SELECT add_retention_policy('telemetry_logs', INTERVAL '3 days', "
                "if_not_exists => TRUE, schedule_interval => INTERVAL '1 hour')"
            ))
            db.commit()
        assert check_retention_policy(db).drop_after == "3 days"


def test_the_supervised_loop_runs_the_check_not_a_delete():
    import inspect

    import main

    source = inspect.getsource(main.retention_pass)
    assert "check_retention_policy" in source
    assert ".delete()" not in source
