"""Scope geofence zone names to their organization.

`name` carried a globally unique index, which is a tenancy defect in two ways.
An organization could not create a zone whose name another organization had
already used -- "Restricted airspace" is exactly the sort of name two tenants
would both pick -- and the 400 it received was an existence oracle for a row it
must not be able to observe at all.

The uniqueness that was intended is per organization, so that is what the index
now expresses.

Revision ID: c3d4e5f6a7b8
Revises: b1c2d3e4f5a6
"""

from alembic import op

revision = "c3d4e5f6a7b8"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_geofence_zones_name", table_name="geofence_zones")

    # Non-unique, for lookups by name within a tenant.
    op.create_index("ix_geofence_zones_name", "geofence_zones", ["name"], unique=False)

    # The constraint that was actually meant. organization_id is nullable, and
    # PostgreSQL treats NULLs as distinct in a unique index, so rows with no
    # organization are not constrained against each other -- acceptable, since
    # such a row is already invisible to every tenant and the application never
    # creates one through this route.
    op.create_index(
        "uq_geofence_zone_org_name",
        "geofence_zones",
        ["organization_id", "name"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_geofence_zone_org_name", table_name="geofence_zones")
    op.drop_index("ix_geofence_zones_name", table_name="geofence_zones")
    op.create_index("ix_geofence_zones_name", "geofence_zones", ["name"], unique=True)
