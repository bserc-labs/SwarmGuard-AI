"""Telemetry retention as a TimescaleDB policy, on one-day chunks.

The application deleted telemetry older than three days itself: once an hour,
one unbatched DELETE over a hypertable that at the ingest cap holds about 13
million rows. On a hypertable that is a long transaction holding locks, and
millions of dead tuples for autovacuum to chase afterwards, every hour.

TimescaleDB does this by dropping whole chunks, which is a metadata operation:
near instant, no dead rows. Two things have to change together for that to
mean "three days":

  * The chunk interval. telemetry_logs was created with the default 7-day
    chunks. A retention policy drops a chunk only when *all* of it is older
    than the cutoff, so "3 days" on 7-day chunks really keeps up to ten. One-day
    chunks make the window 3-4 days, which is what the deleting loop delivered.
    set_chunk_time_interval applies to chunks created from now on; the existing
    chunk keeps its size and is dropped when the whole of it has aged out.

  * The policy itself: drop_after 3 days, checked hourly (the loop's cadence),
    run by TimescaleDB's background workers rather than the API.

Compression is deliberately not enabled. With three days of retention the
saving is small, and a compressed hypertable restricts later schema changes.

The API keeps a supervised "telemetry-retention" loop, but it now only checks
that this policy exists and ran successfully (services/retention.py): a policy
someone removed by hand, or a restore into a database that never had one, is
reported rather than silently letting the table grow.

Revision ID: k1f2a3b4c5d6
Revises: j0e1f2a3b4c5
Create Date: 2026-09-22

"""
from alembic import op

revision = "k1f2a3b4c5d6"
down_revision = "j0e1f2a3b4c5"
branch_labels = None
depends_on = None

TABLE = "telemetry_logs"


def upgrade() -> None:
    op.execute(f"SELECT set_chunk_time_interval('{TABLE}', INTERVAL '1 day')")
    op.execute(
        f"SELECT add_retention_policy('{TABLE}', INTERVAL '3 days', "
        "if_not_exists => TRUE, schedule_interval => INTERVAL '1 hour')"
    )


def downgrade() -> None:
    op.execute(f"SELECT remove_retention_policy('{TABLE}', if_exists => TRUE)")
    op.execute(f"SELECT set_chunk_time_interval('{TABLE}', INTERVAL '7 days')")
