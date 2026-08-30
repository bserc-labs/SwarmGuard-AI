"""Make an unowned row impossible at the schema level.

`organization_id` was nullable on every tenant-scoped table. A NULL there is
invisible to every tenant-scoped query and still present in the table: data that
exists and nobody owns, that no operator can see, review or delete through the
product. Convention was the only thing keeping it from happening, and convention
had already failed 39 times in this database.

Two decisions worth stating.

**audit_logs stays nullable, deliberately.** Every orphaned audit row in this
database is a LOGIN_FAILED for a username that does not exist -- 18 of 19 are for
actors with no matching user. There is no organization to attribute a failed
login for an unknown account to, and dropping those records to satisfy a
constraint would remove exactly the evidence a credential-stuffing attempt
leaves behind. The column keeps its NULL, and a CHECK constrains *which* rows may
use it, so the exception cannot silently widen.

**Unattributable rows are quarantined, not deleted.** They move to an
organization that has no users, so they stay invisible to every tenant exactly as
before, but remain inspectable by an operator with database access. Deleting
telemetry to satisfy a constraint would be destroying evidence to tidy a schema.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
"""

import sqlalchemy as sa
from alembic import op

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None

QUARANTINE_SLUG = "system-quarantine"
QUARANTINE_NAME = "Quarantined (no owning organization)"

# Tables whose organization_id becomes mandatory.
SCOPED_TABLES = [
    "incidents",
    "telemetry_logs",
    "geofence_zones",
    "system_settings",
    "drones",
    "command_requests",
    "users",
]

# Tables carrying a drone_id, so an orphan can be attributed to whoever owns the
# drone rather than going straight to quarantine.
ATTRIBUTABLE_VIA_DRONE = ["incidents", "telemetry_logs", "command_requests"]

AUDIT_NULL_ORG_CHECK = "ck_audit_logs_null_org_only_for_failed_login"


def upgrade() -> None:
    conn = op.get_bind()

    # An organization with no members. Nothing can log into it, so quarantined
    # rows stay as invisible as they were while NULL.
    quarantine_id = conn.execute(
        sa.text("SELECT id FROM organizations WHERE slug = :slug"),
        {"slug": QUARANTINE_SLUG},
    ).scalar()
    if quarantine_id is None:
        # a7b8c9d0e1f2 inserted the default organization with an explicit id, which
        # does not advance the serial sequence. Realign it before relying on it,
        # otherwise the INSERT below hands back id 1 and collides.
        conn.execute(
            sa.text(
                "SELECT setval(pg_get_serial_sequence('organizations', 'id'), "
                "COALESCE((SELECT MAX(id) FROM organizations), 0) + 1, false)"
            )
        )
        quarantine_id = conn.execute(
            sa.text(
                "INSERT INTO organizations (name, slug, status) "
                "VALUES (:name, :slug, 'QUARANTINE') RETURNING id"
            ),
            {"name": QUARANTINE_NAME, "slug": QUARANTINE_SLUG},
        ).scalar()

    # Attribute what can be attributed: a row about a drone belongs to whoever
    # owns that drone.
    for table in ATTRIBUTABLE_VIA_DRONE:
        conn.execute(
            sa.text(
                f"UPDATE {table} AS t SET organization_id = d.organization_id "
                "FROM drones AS d "
                "WHERE t.drone_id = d.drone_id "
                "  AND t.organization_id IS NULL "
                "  AND d.organization_id IS NOT NULL"
            )
        )

    # Whatever is left has no discoverable owner.
    for table in SCOPED_TABLES:
        conn.execute(
            sa.text(
                f"UPDATE {table} SET organization_id = :qid "
                "WHERE organization_id IS NULL"
            ),
            {"qid": quarantine_id},
        )

    for table in SCOPED_TABLES:
        op.alter_column(table, "organization_id", existing_type=sa.Integer(), nullable=False)

    # audit_logs keeps its NULL, bounded to the one case that needs it.
    op.create_check_constraint(
        AUDIT_NULL_ORG_CHECK,
        "audit_logs",
        "organization_id IS NOT NULL OR action = 'LOGIN_FAILED'",
    )


def downgrade() -> None:
    op.drop_constraint(AUDIT_NULL_ORG_CHECK, "audit_logs", type_="check")
    for table in SCOPED_TABLES:
        op.alter_column(table, "organization_id", existing_type=sa.Integer(), nullable=True)
    # Quarantined rows are intentionally left attributed. Restoring them to NULL
    # would recreate the ownerless rows this migration existed to remove.
