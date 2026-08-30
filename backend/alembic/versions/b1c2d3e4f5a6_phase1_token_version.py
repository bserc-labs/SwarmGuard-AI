"""Phase 1: token_version for session revocation

Adds users.token_version. The claim is embedded in every issued token and
compared on each authenticated request, so incrementing this column invalidates
all of a user's outstanding sessions. Before this, a password change left every
existing token valid until it expired.

Revision ID: b1c2d3e4f5a6
Revises: a7b8c9d0e1f2
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default so existing rows get 0 without a separate backfill; the
    # column is NOT NULL from the start.
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("users", "token_version")
