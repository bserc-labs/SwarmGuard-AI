"""Sprint 7: Multi-tenancy, CommandRequest, AuditLog expansion

Revision ID: a7b8c9d0e1f2
Revises: 4dc1c0a003a7
Create Date: 2026-08-08 20:24:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, None] = '4dc1c0a003a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create organizations table
    op.create_table(
        'organizations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('slug', sa.String(), nullable=True),
        sa.Column('status', sa.String(), server_default='ACTIVE', nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_organizations_id'), 'organizations', ['id'], unique=False)
    op.create_index(op.f('ix_organizations_name'), 'organizations', ['name'], unique=False)
    op.create_index(op.f('ix_organizations_slug'), 'organizations', ['slug'], unique=True)

    # 2. Insert default organization for existing data
    op.execute(
        "INSERT INTO organizations (id, name, slug, status) VALUES (1, 'SwarmGuard Default', 'swarmguard-default', 'ACTIVE')"
    )

    # 3. Add organization_id to users
    op.add_column('users', sa.Column('organization_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_users_org', 'users', 'organizations', ['organization_id'], ['id'])
    op.execute("UPDATE users SET organization_id = 1")

    # 4. Add organization_id to telemetry_logs
    op.add_column('telemetry_logs', sa.Column('organization_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_telemetry_org', 'telemetry_logs', 'organizations', ['organization_id'], ['id'])
    op.create_index('ix_telemetry_logs_organization_id', 'telemetry_logs', ['organization_id'], unique=False)
    op.execute("UPDATE telemetry_logs SET organization_id = 1")

    # 5. Add organization_id to incidents
    op.add_column('incidents', sa.Column('organization_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_incidents_org', 'incidents', 'organizations', ['organization_id'], ['id'])
    op.create_index('ix_incidents_organization_id', 'incidents', ['organization_id'], unique=False)
    op.execute("UPDATE incidents SET organization_id = 1")

    # 6. Add organization_id to drones
    op.add_column('drones', sa.Column('organization_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_drones_org', 'drones', 'organizations', ['organization_id'], ['id'])
    op.create_index('ix_drones_organization_id', 'drones', ['organization_id'], unique=False)
    op.execute("UPDATE drones SET organization_id = 1")

    # 7. Create command_requests table (replacing drone_commands)
    op.create_table(
        'command_requests',
        sa.Column('command_id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=True),
        sa.Column('drone_id', sa.String(), nullable=True),
        sa.Column('requested_by', sa.String(), nullable=True),
        sa.Column('command_type', sa.String(), nullable=True),
        sa.Column('reason', sa.String(), nullable=True),
        sa.Column('status', sa.String(), server_default='PENDING', nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('approved_by', sa.String(), nullable=True),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
        sa.PrimaryKeyConstraint('command_id')
    )
    op.create_index(op.f('ix_command_requests_command_id'), 'command_requests', ['command_id'], unique=False)
    op.create_index(op.f('ix_command_requests_drone_id'), 'command_requests', ['drone_id'], unique=False)
    op.create_index(op.f('ix_command_requests_organization_id'), 'command_requests', ['organization_id'], unique=False)

    # 8. Expand audit_logs
    op.add_column('audit_logs', sa.Column('organization_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_audit_org', 'audit_logs', 'organizations', ['organization_id'], ['id'])
    op.create_index('ix_audit_logs_organization_id', 'audit_logs', ['organization_id'], unique=False)
    op.add_column('audit_logs', sa.Column('resource', sa.String(), nullable=True))
    op.add_column('audit_logs', sa.Column('resource_id', sa.String(), nullable=True))
    op.add_column('audit_logs', sa.Column('correlation_id', sa.String(), nullable=True))
    op.add_column('audit_logs', sa.Column('timestamp', sa.DateTime(), server_default=sa.text('now()'), nullable=True))
    # Rename previous_status -> previous_state, new_status -> new_state
    op.alter_column('audit_logs', 'previous_status', new_column_name='previous_state')
    op.alter_column('audit_logs', 'new_status', new_column_name='new_state')
    op.execute("UPDATE audit_logs SET organization_id = 1")

    # 9. Add organization_id to geofence_zones
    op.add_column('geofence_zones', sa.Column('organization_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_geofence_org', 'geofence_zones', 'organizations', ['organization_id'], ['id'])
    op.create_index('ix_geofence_zones_organization_id', 'geofence_zones', ['organization_id'], unique=False)
    op.execute("UPDATE geofence_zones SET organization_id = 1")

    # 10. Add organization_id to system_settings
    op.add_column('system_settings', sa.Column('organization_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_settings_org', 'system_settings', 'organizations', ['organization_id'], ['id'])
    op.execute("UPDATE system_settings SET organization_id = 1")


def downgrade() -> None:
    op.drop_column('system_settings', 'organization_id')
    op.drop_column('geofence_zones', 'organization_id')
    op.alter_column('audit_logs', 'previous_state', new_column_name='previous_status')
    op.alter_column('audit_logs', 'new_state', new_column_name='new_status')
    op.drop_column('audit_logs', 'timestamp')
    op.drop_column('audit_logs', 'correlation_id')
    op.drop_column('audit_logs', 'resource_id')
    op.drop_column('audit_logs', 'resource')
    op.drop_column('audit_logs', 'organization_id')
    op.drop_table('command_requests')
    op.drop_column('drones', 'organization_id')
    op.drop_column('incidents', 'organization_id')
    op.drop_column('telemetry_logs', 'organization_id')
    op.drop_column('users', 'organization_id')
    op.drop_table('organizations')
