"""Composite index for per-drone latest-packet reads on telemetry_logs.

GET /telemetry/latest asked for the newest packet per drone with

    SELECT DISTINCT ON (drone_id) ... WHERE organization_id = ?
     ORDER BY drone_id, created_at DESC

telemetry_logs only ever had single-column indexes (9529212d8c6b,
a7b8c9d0e1f2), so the planner fetched every row of the organization and sorted
it. EXPLAIN on the live database: Unique -> Sort -> Seq Scan. The table keeps
three days of packets (main.py periodic_database_cleanup), which at the ingest
cap is about 13 million rows -- sorted on every poll, from three dashboard
pages.

The route now takes one indexed lookup per drone (routers/telemetry.py), and
this is the index it walks: equality on (organization_id, drone_id), then
created_at descending, so the first entry in the newest chunk is the answer. It
also serves every other read shaped the same way: GET /telemetry/{drone_id},
GET /telemetry/{drone_id}/latest and the detection pipeline's history window.

telemetry_logs is a hypertable (9529212d8c6b). CREATE INDEX on a hypertable
creates the index on the hypertable and on every existing chunk, and new chunks
inherit it. CREATE INDEX CONCURRENTLY is not supported on hypertables; the
lock-friendlier form for a large live table is

    CREATE INDEX ix_telemetry_logs_org_drone_created_at
        ON telemetry_logs (organization_id, drone_id, created_at DESC)
        WITH (timescaledb.transaction_per_chunk);

which an operator may run by hand before upgrading -- if_not_exists below makes
this migration a no-op in that case.

Revision ID: j0e1f2a3b4c5
Revises: i9d0e1f2a3b4
Create Date: 2026-09-22

"""
import sqlalchemy as sa
from alembic import op

revision = "j0e1f2a3b4c5"
down_revision = "i9d0e1f2a3b4"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_telemetry_logs_org_drone_created_at"


def upgrade() -> None:
    op.create_index(
        INDEX_NAME,
        "telemetry_logs",
        ["organization_id", "drone_id", sa.text("created_at DESC")],
        unique=False,
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="telemetry_logs", if_exists=True)
