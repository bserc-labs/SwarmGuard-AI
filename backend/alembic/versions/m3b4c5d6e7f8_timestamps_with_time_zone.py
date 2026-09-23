"""Store every timestamp as timestamptz.

Revision ID: m3b4c5d6e7f8
Revises: l2a3b4c5d6e7
Create Date: 2026-09-23

Every datetime column was `timestamp without time zone` holding UTC by
convention: Python wrote `datetime.utcnow()`, PostgreSQL wrote `now()` in a UTC
session. Nothing enforced the convention. A deployment whose server TimeZone
was not UTC would have written local time from `now()` into the same columns as
UTC from `utcnow()`, indistinguishably. And every value left the API without an
offset, so the frontend had to guess one (it appends "Z" -- see
frontend/src/lib/format.ts).

timestamptz stores an absolute instant, so neither guess is needed again.

The conversion reads each existing value in the session's time zone, set to UTC
below, which is how they were written. PostgreSQL 12 and later perform
timestamp -> timestamptz under a UTC session *without rewriting the table*, so
even `telemetry_logs` -- a hypertable whose partitioning column this is --
converts in place, keeping its chunks, its indexes and its retention policy.

It refuses to run where that reading would be wrong: if the server's default
TimeZone is not UTC, values written by `now()` are local time, and reading them
as UTC would shift them silently. Convert those by hand with
`USING col AT TIME ZONE '<that zone>'` and stamp this revision.
"""

from alembic import op
from sqlalchemy import text

revision = "m3b4c5d6e7f8"
down_revision = "l2a3b4c5d6e7"
branch_labels = None
depends_on = None

# Every datetime column in the schema, including drone_commands, which has no
# model. Checked against information_schema, not against models.py.
COLUMNS = [
    ("audit_logs", "created_at"),
    ("command_requests", "approved_at"),
    ("command_requests", "created_at"),
    ("device_credentials", "created_at"),
    ("device_credentials", "last_used_at"),
    ("device_credentials", "revoked_at"),
    ("drone_commands", "created_at"),
    ("drones", "last_seen"),
    ("geofence_zones", "created_at"),
    ("incidents", "created_at"),
    ("incidents", "detection_time"),
    ("incidents", "resolution_time"),
    ("incidents", "updated_at"),
    ("organizations", "created_at"),
    ("organizations", "updated_at"),
    ("telemetry_logs", "created_at"),
    ("users", "created_at"),
]

# PostgreSQL spells UTC several ways; all of them mean the same offset.
UTC_NAMES = {
    "UTC", "UCT", "Universal", "Zulu", "GMT", "GMT0", "GMT+0", "GMT-0", "Greenwich",
    "Etc/UTC", "Etc/UCT", "Etc/Universal", "Etc/Zulu", "Etc/GMT", "Etc/Greenwich",
}


def _require_a_utc_server() -> None:
    default = op.get_bind().execute(
        text("SELECT reset_val FROM pg_settings WHERE name = 'TimeZone'")
    ).scalar()
    if default not in UTC_NAMES:
        raise RuntimeError(
            f"This server's default TimeZone is {default!r}, not UTC, so the values "
            "written by now() are local time and reading them as UTC would shift them. "
            "Convert each column by hand with "
            "ALTER TABLE ... ALTER COLUMN ... TYPE timestamptz USING col AT TIME ZONE "
            f"'{default}', then stamp revision {revision}."
        )


def _convert(to: str) -> None:
    # SET LOCAL: the session zone decides how the existing values are read, and
    # it is also what lets PostgreSQL skip the table rewrite.
    op.execute("SET LOCAL timezone = 'UTC'")
    for table, column in COLUMNS:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} TYPE {to}")


def upgrade() -> None:
    _require_a_utc_server()
    _convert("timestamptz")


def downgrade() -> None:
    _convert("timestamp")
