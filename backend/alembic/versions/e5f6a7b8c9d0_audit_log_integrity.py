"""Make the audit log actually immutable, and stop paying for it twice.

Three defects in one table, all found against a live database rather than by
reading the model.

1. **"Immutable" was a claim, not a control.** `docs/SECURITY.md` names
   "Immutable `AuditLog` database entries" as the mitigation for Unauthorized
   Action Repudiation. There were no triggers and no rules on the table:

       SELECT tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
        WHERE c.relname = 'audit_logs' AND NOT tgisinternal;
       -- (0 rows)

   Any UPDATE or DELETE succeeded. A tamper-evident log that anything holding
   the application's own credentials can rewrite is not evidence of anything.

2. **A duplicate index.** `ix_audit_logs_username` and `ix_audit_logs_actor`
   were both `btree(actor)`. The first is a fossil: the initial migration
   created it on a column named `username`, a later migration renamed that
   column to `actor`, and PostgreSQL carried the index across under its old
   name -- then a fresh index was added on the new name. Two identical B-trees,
   both maintained on every insert, on the table this change is about to make
   busier.

3. **Two timestamp columns.** `created_at` (initial migration) and `timestamp`
   (sprint 7), both defaulting to `now()`. Only `created_at` is read by the
   application (`routers/incidents.py`). `timestamp` carried the index, so
   dropping it moves that index to the column that is actually queried.

Deletion stays possible, deliberately: `audit_logs` will need a retention
policy, and a table that can only ever grow is its own outage. It is gated
behind an explicit session flag so it cannot happen by accident:

    SET LOCAL swarmguard.audit_maintenance = 'on';
    DELETE FROM audit_logs WHERE created_at < now() - interval '2 years';

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-09-21

"""
import sqlalchemy as sa
from alembic import op

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


IMMUTABILITY_FUNCTION = """
CREATE OR REPLACE FUNCTION swarmguard_audit_logs_immutable()
RETURNS TRIGGER AS $$
BEGIN
    IF (TG_OP = 'UPDATE') THEN
        RAISE EXCEPTION
            'audit_logs is append-only: UPDATE is not permitted (row id=%)', OLD.id
            USING ERRCODE = 'restrict_violation';
    END IF;

    -- DELETE is permitted only for a deliberate retention pass, which must
    -- announce itself on the session first.
    IF (TG_OP = 'DELETE') THEN
        IF coalesce(current_setting('swarmguard.audit_maintenance', true), 'off') <> 'on' THEN
            RAISE EXCEPTION
                'audit_logs is append-only: DELETE requires '
                '"SET LOCAL swarmguard.audit_maintenance = ''on''" (row id=%)', OLD.id
                USING ERRCODE = 'restrict_violation';
        END IF;
        RETURN OLD;
    END IF;

    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    # --- 1. Preserve the data before dropping the redundant column ----------
    # Both columns default to now(), so they agree for every row written since
    # `timestamp` was added. Rows predating it have created_at set and
    # timestamp NULL; rows written by anything that set only timestamp would
    # have the reverse. Backfill in that direction, then drop.
    op.execute(
        "UPDATE audit_logs SET created_at = timestamp "
        "WHERE created_at IS NULL AND timestamp IS NOT NULL"
    )

    # --- 2. Move the index to the column the application actually reads -----
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"], unique=False)
    op.drop_column("audit_logs", "timestamp")  # drops ix_audit_logs_timestamp with it

    # --- 3. Drop the duplicate btree(actor) --------------------------------
    op.execute("DROP INDEX IF EXISTS ix_audit_logs_username")

    # --- 4. Enforce append-only --------------------------------------------
    op.execute(IMMUTABILITY_FUNCTION)
    op.execute(
        "CREATE TRIGGER audit_logs_immutable "
        "BEFORE UPDATE OR DELETE ON audit_logs "
        "FOR EACH ROW EXECUTE FUNCTION swarmguard_audit_logs_immutable()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_logs_immutable ON audit_logs")
    op.execute("DROP FUNCTION IF EXISTS swarmguard_audit_logs_immutable()")

    op.execute("CREATE INDEX IF NOT EXISTS ix_audit_logs_username ON audit_logs (actor)")

    op.add_column(
        "audit_logs",
        sa.Column("timestamp", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
    )
    op.execute("UPDATE audit_logs SET timestamp = created_at")
    op.create_index("ix_audit_logs_timestamp", "audit_logs", ["timestamp"], unique=False)
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
