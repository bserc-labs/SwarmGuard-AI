"""The API refuses to serve a schema that is behind, and only that.

Migrations run once, from a dedicated job. That makes it possible for the API
to start before the job has finished or after it failed, and new code on an old
schema does not fail at boot -- it fails an hour later, on whichever request
first touches the missing column. The check at startup moves that failure to
where someone is looking.

"Ahead" deliberately does not refuse: it is what a rollback looks like, and
refusing would turn every rollback into an outage.
"""

import asyncio
import logging
import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

import main
from config import Settings
from database import DATABASE_URL
from tests.conftest import engine as test_engine
from utils.schema_check import (
    AHEAD,
    AT_HEAD,
    BEHIND,
    SchemaOutOfDate,
    assert_schema_current,
    classify,
    expected_heads,
    schema_state,
)

SCRATCH_DB = f"sg_schemacheck_{os.getpid()}"
FIRST_REVISION = "9529212d8c6b"


class TestTheDecision:
    """`classify` is pure, so every branch is covered without a database."""

    def known(self, revision: str) -> bool:
        return revision in {"a", "b", "head"}

    def test_at_head(self):
        assert classify({"head"}, {"head"}, self.known) == AT_HEAD

    def test_an_older_known_revision_is_behind(self):
        assert classify({"a"}, {"head"}, self.known) == BEHIND

    def test_a_database_that_was_never_migrated_is_behind(self):
        assert classify(set(), {"head"}, self.known) == BEHIND

    def test_a_revision_this_build_has_never_heard_of_is_ahead(self):
        assert classify({"from-the-future"}, {"head"}, self.known) == AHEAD


def test_this_build_has_exactly_one_head():
    """Two heads would make "at head" ambiguous and `alembic upgrade head` fail."""
    assert len(expected_heads()) == 1


def test_the_guard_is_on_by_default():
    assert Settings.model_fields["REQUIRE_SCHEMA_AT_HEAD"].default is True


def test_the_migrated_test_database_is_at_head():
    state, current, expected = schema_state(test_engine)
    assert state == AT_HEAD, f"test database is at {current}, build expects {expected}"


@pytest.fixture
def scratch_engine():
    url = make_url(os.getenv("TEST_DATABASE_URL", DATABASE_URL))
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}"'))
            connection.execute(text(f'CREATE DATABASE "{SCRATCH_DB}"'))
    except OperationalError as exc:
        pytest.skip(f"cannot create a scratch database on the test server: {exc}")
    engine = create_engine(url.set(database=SCRATCH_DB))
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}" WITH (FORCE)'))
        admin.dispose()


def _stamp(engine, revision: str) -> None:
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
        connection.execute(text("INSERT INTO alembic_version VALUES (:r)"), {"r": revision})


class TestAgainstARealDatabase:
    def test_a_never_migrated_database_is_refused(self, scratch_engine):
        with pytest.raises(SchemaOutOfDate, match="never migrated"):
            assert_schema_current(scratch_engine, logging.getLogger("test"))

    def test_a_database_that_is_behind_is_refused_and_told_how_to_fix_it(self, scratch_engine):
        _stamp(scratch_engine, FIRST_REVISION)
        with pytest.raises(SchemaOutOfDate) as raised:
            assert_schema_current(scratch_engine, logging.getLogger("test"))
        message = str(raised.value)
        assert FIRST_REVISION in message
        assert next(iter(expected_heads())) in message
        assert "migrate" in message, "the error must say what to run"

    def test_a_database_that_is_ahead_is_served_with_a_warning(self, scratch_engine, caplog):
        """The rollback case: the previous image, a database the newer one migrated."""
        _stamp(scratch_engine, "zz99_from_a_newer_release")
        with caplog.at_level(logging.WARNING):
            state = assert_schema_current(scratch_engine, logging.getLogger("test"))
        assert state == AHEAD
        assert "rollback" in caplog.text

    def test_startup_itself_refuses_a_schema_that_is_behind(self, scratch_engine, monkeypatch):
        """The guard is wired into startup, and fires before anything is started."""
        _stamp(scratch_engine, FIRST_REVISION)
        monkeypatch.setattr(main, "engine", scratch_engine)
        untouched = object()
        monkeypatch.setattr(main.app.state, "background_tasks", untouched, raising=False)
        with pytest.raises(SchemaOutOfDate):
            asyncio.run(main.startup())
        assert main.app.state.background_tasks is untouched, (
            "startup went on to create background tasks after the schema check failed"
        )
