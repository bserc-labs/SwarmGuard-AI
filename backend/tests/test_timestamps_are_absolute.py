"""Every timestamp is an absolute instant, in the database and in the models.

Until migration m3b4c5d6e7f8 every datetime column was `timestamp without time
zone` holding UTC by convention: Python wrote datetime.utcnow(), PostgreSQL
wrote now() in a UTC session, and nothing enforced either half. These tests
enforce it, and fail on the next column or clock call that does not.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import DateTime, inspect, text

import models
from database import SessionLocal


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


class TestTheDatabase:
    def test_no_datetime_column_is_naive(self, db):
        naive = db.execute(
            text(
                "SELECT table_name || '.' || column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND data_type = 'timestamp without time zone' "
                "ORDER BY 1"
            )
        ).scalars().all()
        assert naive == [], f"naive datetime columns: {naive}"

    def test_the_schema_still_has_the_columns_it_converted(self, db):
        aware = db.execute(
            text(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_schema = 'public' AND data_type = 'timestamp with time zone'"
            )
        ).scalar()
        # 17 at the migration; a new one only ever adds to this.
        assert aware >= 17

    def test_a_connection_speaks_utc_whatever_the_server_prefers(self, db):
        assert db.execute(text("SHOW timezone")).scalar().lower() in {"utc", "etc/utc"}

    def test_now_comes_back_with_an_offset(self, db):
        stamped = db.execute(text("SELECT now()")).scalar()
        assert stamped.tzinfo is not None
        assert abs(stamped - datetime.now(UTC)) < timedelta(minutes=5)


class TestTheModels:
    def test_every_datetime_column_declares_a_time_zone(self):
        naive = []
        for mapper in models.Base.registry.mappers:
            for column in inspect(mapper.class_).columns:
                if isinstance(column.type, DateTime) and not column.type.timezone:
                    naive.append(f"{column.table.name}.{column.name}")
        assert naive == [], f"models declaring a naive DateTime: {naive}"

    def test_the_models_cover_what_the_database_has(self):
        declared = sum(
            1
            for mapper in models.Base.registry.mappers
            for column in inspect(mapper.class_).columns
            if isinstance(column.type, DateTime)
        )
        # drone_commands.created_at has no model, hence the database's 17.
        assert declared == 16


class TestWhatIsStored:
    def test_a_row_written_now_reads_back_aware_and_current(self, db):
        organization = models.Organization(name=f"tz-probe-{datetime.now(UTC).timestamp()}")
        db.add(organization)
        db.flush()
        db.refresh(organization)

        assert organization.created_at.tzinfo is not None
        assert abs(organization.created_at - datetime.now(UTC)) < timedelta(minutes=5)

    def test_a_naive_value_written_to_a_column_is_read_as_utc(self, db):
        # The session is pinned to UTC, so code or a client that still hands
        # over a bare timestamp means the instant it always meant.
        moment = datetime(2026, 9, 23, 12, 0, 0, tzinfo=UTC)
        organization = models.Organization(
            name=f"tz-naive-{datetime.now(UTC).timestamp()}",
            created_at=moment.replace(tzinfo=None),
        )
        db.add(organization)
        db.flush()
        db.expire(organization, ["created_at"])

        assert organization.created_at == moment
