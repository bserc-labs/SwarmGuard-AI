"""One settings row per organization, at the schema level.

models.SystemSettings declares organization_id `unique=True, index=True`.
a7b8c9d0e1f2 added the column with a foreign key and nothing else, and no
migration since created the index. Live schema before this migration:

    SELECT indexname FROM pg_indexes WHERE tablename = 'system_settings';
    -- system_settings_pkey, ix_system_settings_id

So the database accepted any number of settings rows per organization.
routers/settings.get_or_create_settings SELECTs and then INSERTs on a miss; two
concurrent first requests for a new organization both miss and both insert.
Every reader then uses .first() with no ORDER BY, so which row a tenant's
detections were graded against -- its severity thresholds -- was up to the
planner.

Deduplication keeps the lowest id per organization. That is a choice, not a
discovery: the table has no updated_at, and without an index a sequential scan
with LIMIT 1 does not reliably return either row once one has been UPDATEd, so
no survivor is provably "the one that was edited". Lowest id is deterministic
and reviewable, and every removed row is logged in full before it goes.

Revision ID: i9d0e1f2a3b4
Revises: g7b8c9d0e1f2
Create Date: 2026-09-21

"""
import logging

import sqlalchemy as sa
from alembic import op

revision = "i9d0e1f2a3b4"
down_revision = "g7b8c9d0e1f2"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")

# The name SQLAlchemy derives from `index=True, unique=True` on the model
# column, so autogenerate stops reporting system_settings as drifted.
INDEX_NAME = "ix_system_settings_organization_id"

DEDUPE_SQL = """
DELETE FROM system_settings
 WHERE id NOT IN (SELECT MIN(id) FROM system_settings GROUP BY organization_id)
RETURNING id, organization_id, critical_threshold, high_threshold,
          refresh_rate, ui_sound, push_notif, webhooks
"""


def upgrade() -> None:
    removed = op.get_bind().execute(sa.text(DEDUPE_SQL)).fetchall()
    for row in removed:
        log.warning("Removed duplicate system_settings row: %s", dict(row._mapping))
    if removed:
        log.warning(
            "Removed %d duplicate system_settings row(s); the lowest id per "
            "organization was kept.",
            len(removed),
        )

    op.create_index(INDEX_NAME, "system_settings", ["organization_id"], unique=True)


def downgrade() -> None:
    # Rows removed by upgrade() are not restored; they were logged when removed.
    op.drop_index(INDEX_NAME, table_name="system_settings")
