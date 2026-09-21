"""Record the device's own sample clock on telemetry.

The kinematic guard divides every rate it checks -- implied ground speed,
climb rate, GNSS/airframe speed disagreement -- by the interval between two
packets, and the only interval it had was created_at: a server-side now() at
insert. That is packet arrival cadence, not flight time. Two nominal packets
delivered in a 50 ms burst implied 540 m/s and filed a CRITICAL spoof; a real
jump whose packets arrived far apart was diluted below the threshold.

This column carries the device's monotonic sample clock (MAVLink
GLOBAL_POSITION_INT.time_boot_ms, or any equivalent). Nullable: rows before
this revision, and devices that never report one, stay NULL and the guard
rates them on created_at as before, recording which clock it used.

telemetry_logs is a TimescaleDB hypertable (9529212d8c6b). ADD COLUMN with
NULL allowed and no default is a catalog-only change that Timescale propagates
to every chunk -- 4ed56aace9c3 and a7b8c9d0e1f2 did exactly this to this
table. Compression is not enabled on the hypertable, so none of the
compressed-chunk restrictions on ALTER TABLE apply. BigInteger because a device
may report epoch milliseconds, which overflow a 32-bit Integer.

Revision ID: g7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-09-21

"""
import sqlalchemy as sa
from alembic import op

revision = "g7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "telemetry_logs",
        sa.Column("sample_time_ms", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("telemetry_logs", "sample_time_ms")
