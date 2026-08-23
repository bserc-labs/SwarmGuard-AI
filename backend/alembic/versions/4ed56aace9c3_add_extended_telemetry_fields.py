"""Add extended telemetry fields

Revision ID: 4ed56aace9c3
Revises: 9529212d8c6b
Create Date: 2026-08-06 03:15:26.151060

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '4ed56aace9c3'
down_revision: Union[str, Sequence[str], None] = '9529212d8c6b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('telemetry_logs', sa.Column('heading', sa.Float(), nullable=True))
    op.add_column('telemetry_logs', sa.Column('flight_mode', sa.String(), nullable=True))
    op.add_column('telemetry_logs', sa.Column('armed_status', sa.Boolean(), nullable=True))
    op.add_column('telemetry_logs', sa.Column('satellites', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('telemetry_logs', 'heading')
    op.drop_column('telemetry_logs', 'flight_mode')
    op.drop_column('telemetry_logs', 'armed_status')
    op.drop_column('telemetry_logs', 'satellites')
