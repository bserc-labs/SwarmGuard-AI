"""Sprint_5_Incident_Management

Revision ID: 4dc1c0a003a7
Revises: 4ed56aace9c3
Create Date: 2026-08-06 03:56:56.398102

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '4dc1c0a003a7'
down_revision: Union[str, Sequence[str], None] = '4ed56aace9c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # incidents table additions
    op.add_column('incidents', sa.Column('mission_id', sa.String(), nullable=True))
    op.add_column('incidents', sa.Column('threat_score', sa.Float(), server_default='0.0'))
    op.add_column('incidents', sa.Column('priority', sa.Integer(), server_default='0'))
    op.add_column('incidents', sa.Column('explanation_summary', sa.JSON(), nullable=True))
    op.add_column('incidents', sa.Column('recommended_action', sa.String(), nullable=True))
    op.add_column('incidents', sa.Column('model_version', sa.String(), nullable=True))
    op.add_column('incidents', sa.Column('feature_version', sa.String(), nullable=True))
    op.add_column('incidents', sa.Column('assigned_analyst', sa.String(), nullable=True))
    op.add_column('incidents', sa.Column('detection_time', sa.DateTime(), server_default=sa.text('now()'), nullable=True))
    op.add_column('incidents', sa.Column('resolution_time', sa.DateTime(), nullable=True))
    
    op.create_index(op.f('ix_incidents_mission_id'), 'incidents', ['mission_id'], unique=False)
    op.create_index(op.f('ix_incidents_priority'), 'incidents', ['priority'], unique=False)
    op.create_index(op.f('ix_incidents_detection_time'), 'incidents', ['detection_time'], unique=False)
    
    # audit_logs table additions
    op.alter_column('audit_logs', 'username', new_column_name='actor')
    op.add_column('audit_logs', sa.Column('previous_status', sa.String(), nullable=True))
    op.add_column('audit_logs', sa.Column('new_status', sa.String(), nullable=True))
    op.add_column('audit_logs', sa.Column('reason', sa.String(), nullable=True))
    op.create_index(op.f('ix_audit_logs_actor'), 'audit_logs', ['actor'], unique=False)

def downgrade() -> None:
    op.drop_index(op.f('ix_audit_logs_actor'), table_name='audit_logs')
    op.drop_column('audit_logs', 'reason')
    op.drop_column('audit_logs', 'new_status')
    op.drop_column('audit_logs', 'previous_status')
    op.alter_column('audit_logs', 'actor', new_column_name='username')
    
    op.drop_index(op.f('ix_incidents_detection_time'), table_name='incidents')
    op.drop_index(op.f('ix_incidents_priority'), table_name='incidents')
    op.drop_index(op.f('ix_incidents_mission_id'), table_name='incidents')
    
    op.drop_column('incidents', 'resolution_time')
    op.drop_column('incidents', 'detection_time')
    op.drop_column('incidents', 'assigned_analyst')
    op.drop_column('incidents', 'feature_version')
    op.drop_column('incidents', 'model_version')
    op.drop_column('incidents', 'recommended_action')
    op.drop_column('incidents', 'explanation_summary')
    op.drop_column('incidents', 'priority')
    op.drop_column('incidents', 'threat_score')
    op.drop_column('incidents', 'mission_id')
