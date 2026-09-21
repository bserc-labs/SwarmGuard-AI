"""Scope drone_id to its organization.

The same defect migration c3d4e5f6a7b8 fixed for geofence zone names, in the
table it matters most for. `ix_drones_drone_id` was globally unique, so two
tenants could not both operate an airframe called "UAV-001" -- and "UAV-001",
"DRONE-ALPHA-01" and the rest are exactly the identifiers two operators
independently pick.

Reproduced against a live database before the change:

    INSERT INTO drones (organization_id, drone_id, ...) -- org A, 'SHARED-UAV-001'
    INSERT INTO drones (organization_id, drone_id, ...) -- org B, 'SHARED-UAV-001'
    ERROR:  duplicate key value violates unique constraint "ix_drones_drone_id"

Two consequences, both worse than the geofence case:

* **Cross-tenant denial of service.** `telemetry_service.process_telemetry`
  looks the drone up scoped to the caller's organization, misses, and inserts.
  The insert violates the global index, `/telemetry/ingest` returns 500, and it
  does so for every subsequent packet. Any tenant can permanently block another
  tenant's airframe by registering that identifier first -- and would usually do
  it by accident.

* **An existence oracle.** The failure tells the caller that some other
  organization already owns that drone_id, which is precisely the fact tenancy
  exists to hide.

The uniqueness that was intended is per organization, so that is what the index
now expresses.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-09-21

"""
from alembic import op

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_drones_drone_id", table_name="drones")

    # Non-unique, for lookups by identifier within a tenant -- which is how
    # every query in the application reads this column.
    op.create_index("ix_drones_drone_id", "drones", ["drone_id"], unique=False)

    # The constraint that was actually meant. organization_id is NOT NULL on
    # this table as of d4e5f6a7b8c9, so unlike the geofence case there is no
    # NULL-distinctness caveat: every row is constrained.
    op.create_index(
        "uq_drones_org_drone_id",
        "drones",
        ["organization_id", "drone_id"],
        unique=True,
    )


def downgrade() -> None:
    # Only reversible while no two organizations share a drone_id -- which is
    # the state this migration exists to make reachable. If any do, the global
    # unique index cannot be recreated and this will fail loudly rather than
    # silently discarding a tenant's fleet.
    op.drop_index("uq_drones_org_drone_id", table_name="drones")
    op.drop_index("ix_drones_drone_id", table_name="drones")
    op.create_index("ix_drones_drone_id", "drones", ["drone_id"], unique=True)
