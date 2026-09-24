"""Accounts can be disabled.

Revision ID: n4c5d6e7f8a9
Revises: m3b4c5d6e7f8
Create Date: 2026-09-23

Until now the only way to stop someone signing in was to delete their row,
which also removes the account an audit trail refers to. An operator who leaves
should be disabled: the audit history keeps naming a real account, and the
decision is reversible if they come back.

Existing accounts are active, which is what they were before this column.
"""

import sqlalchemy as sa

from alembic import op

revision = "n4c5d6e7f8a9"
down_revision = "m3b4c5d6e7f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("users", "is_active")
