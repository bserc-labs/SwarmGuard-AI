"""Two migrators starting together must both succeed.

`alembic upgrade head` reads the current revision, then applies what is
missing. Started together against an empty database, every migrator reads
"nothing applied" and runs the same CREATE TABLE; all but one die on "relation
already exists", at a point decided by timing. That is what happened whenever
two backend replicas started at once, because the container entrypoint migrated
on every start.

alembic/env.py now takes a PostgreSQL advisory lock for the length of a run.
This test starts several real `alembic upgrade head` processes against a scratch
database at the same instant and requires every one of them to exit 0.

It was run against env.py without the lock before the lock was written:
3 migrators, 1 survivor. See the commit message.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from database import DATABASE_URL
from utils.schema_check import expected_heads

BACKEND = Path(__file__).resolve().parents[1]
MIGRATORS = 3
SCRATCH_DB = f"sg_migrace_{os.getpid()}"


def _admin_engine():
    url = make_url(os.getenv("TEST_DATABASE_URL", DATABASE_URL))
    return create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")


@pytest.fixture
def scratch_database_url():
    """An empty database on the test server, dropped afterwards."""
    admin = _admin_engine()
    try:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}"'))
            connection.execute(text(f'CREATE DATABASE "{SCRATCH_DB}"'))
    except OperationalError as exc:
        pytest.skip(f"cannot create a scratch database on the test server: {exc}")
    url = make_url(os.getenv("TEST_DATABASE_URL", DATABASE_URL)).set(database=SCRATCH_DB)
    try:
        yield url.render_as_string(hide_password=False)
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}" WITH (FORCE)'))
        admin.dispose()


def _start_migrator(database_url: str) -> subprocess.Popen:
    env = {**os.environ, "DATABASE_URL": database_url}
    return subprocess.Popen(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def test_concurrent_migrators_all_succeed(scratch_database_url):
    migrators = [_start_migrator(scratch_database_url) for _ in range(MIGRATORS)]
    # A generous bound: a migrator that deadlocks must fail the test, not hang CI.
    outputs = [m.communicate(timeout=180)[0] for m in migrators]
    failures = [
        f"migrator {i} exited {m.returncode}:\n{out[-1200:]}"
        for i, (m, out) in enumerate(zip(migrators, outputs, strict=True))
        if m.returncode != 0
    ]
    assert not failures, "\n\n".join(failures)

    engine = create_engine(scratch_database_url)
    try:
        with engine.connect() as connection:
            applied = set(connection.execute(text("SELECT version_num FROM alembic_version")).scalars())
            hypertables = connection.execute(
                text("SELECT count(*) FROM timescaledb_information.hypertables "
                     "WHERE hypertable_name = 'telemetry_logs'")
            ).scalar()
    finally:
        engine.dispose()
    assert applied == expected_heads(), "the schema must end exactly at head, applied once"
    assert hypertables == 1


def test_the_lock_is_released_after_a_run(scratch_database_url):
    """A second, later run must not wait on a lock the first one leaked."""
    first = _start_migrator(scratch_database_url)
    assert first.communicate(timeout=180) and first.returncode == 0
    second = _start_migrator(scratch_database_url)
    out, _ = second.communicate(timeout=60)
    assert second.returncode == 0, out[-1200:]
