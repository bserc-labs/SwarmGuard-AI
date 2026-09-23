"""Per-device credentials for telemetry ingest.

One shared DRONE_API_KEY authenticated every drone in every organization. This
table holds a key per drone -- as a SHA-256 digest, never the key -- bound to an
organization and a drone id, individually revocable. See
services/device_credentials.py.

No foreign key to drones: a credential is issued before a drone's first flight,
which is when the drones row is created.

Revision ID: l2a3b4c5d6e7
Revises: k1f2a3b4c5d6
Create Date: 2026-09-22

"""
import sqlalchemy as sa
from alembic import op

revision = "l2a3b4c5d6e7"
down_revision = "k1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "device_credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("drone_id", sa.String(), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("key_prefix", sa.String(16), nullable=False),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_by", sa.String(), nullable=True),
    )
    # Ingest looks a presented key up by its digest: one indexed probe.
    op.create_index("ux_device_credentials_key_hash", "device_credentials", ["key_hash"], unique=True)
    # Listing a drone's keys, and "which drones have a live key".
    op.create_index(
        "ix_device_credentials_org_drone", "device_credentials", ["organization_id", "drone_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_device_credentials_org_drone", table_name="device_credentials")
    op.drop_index("ux_device_credentials_key_hash", table_name="device_credentials")
    op.drop_table("device_credentials")
