"""The database must refuse a row that no organization owns.

These assert against the live schema, not against application code. Every
tenant-scoped query filters on organization_id, so a NULL there produces a row
that is invisible to every tenant and still occupies the table -- and no amount
of care in the routers prevents it if the column permits it. The point of this
file is that the guarantee survives someone forgetting.

Requires PostgreSQL: SQLite does not expose information_schema and does not
enforce a CHECK the same way.
"""

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from database import DATABASE_URL

# Mandatory on every table that carries tenant-owned data.
SCOPED_TABLES = [
    "incidents",
    "telemetry_logs",
    "geofence_zones",
    "system_settings",
    "drones",
    "command_requests",
    "users",
]

AUDIT_NULL_ORG_CHECK = "ck_audit_logs_null_org_only_for_failed_login"

engine = create_engine(
    os.getenv("TEST_DATABASE_URL", DATABASE_URL), pool_pre_ping=True
)

pytestmark = pytest.mark.skipif(
    not engine.url.drivername.startswith("postgresql"),
    reason="schema-level constraints are only enforced on PostgreSQL",
)


def nullability(conn, table, column="organization_id"):
    return conn.execute(
        text(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).scalar()


@pytest.mark.parametrize("table", SCOPED_TABLES)
def test_organization_id_is_mandatory(table):
    """Declared NOT NULL, per table.

    Parametrised so a regression names the table that lost the constraint
    instead of failing as one opaque assertion.
    """
    with engine.connect() as conn:
        assert nullability(conn, table) == "NO", (
            f"{table}.organization_id is nullable again: a row written without "
            "an owner would be invisible to every tenant and still present."
        )


def test_an_ownerless_row_is_rejected_by_the_database():
    """The property itself, not the declaration of it.

    An INSERT that omits organization_id must fail. This is what makes the
    guarantee independent of every code path that writes an incident.
    """
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            with pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        "INSERT INTO incidents "
                        "(drone_id, attack_type, threat_score, anomaly_score, "
                        " threat_level, severity, priority, explanation, status) "
                        "VALUES ('NULL-ORG-PROBE', 'TEST', 1.0, 1.0, 1, 'LOW', 0, 'probe', 'NEW')"
                    )
                )
        finally:
            trans.rollback()


def test_audit_logs_still_accepts_a_failed_login_with_no_organization():
    """The deliberate exception.

    A LOGIN_FAILED for a username that does not exist has no organization to
    attribute it to. Forcing NOT NULL here would mean either fabricating an
    owner or dropping the record -- and that record is the evidence a
    credential-stuffing attempt leaves behind.
    """
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(
                text(
                    "INSERT INTO audit_logs (actor, action, organization_id) "
                    "VALUES ('probe-unknown-user', 'LOGIN_FAILED', NULL)"
                )
            )
        finally:
            trans.rollback()


def test_audit_logs_rejects_any_other_ownerless_action():
    """The exception is bounded, so it cannot quietly widen.

    Without the CHECK, "audit_logs is nullable" would license any action to be
    written without an owner, and the one justified case would become a general
    hole.
    """
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            with pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        "INSERT INTO audit_logs (actor, action, organization_id) "
                        "VALUES ('probe', 'STATUS_TRANSITION', NULL)"
                    )
                )
        finally:
            trans.rollback()


def test_the_audit_check_constraint_exists_by_name():
    with engine.connect() as conn:
        found = conn.execute(
            text(
                "SELECT COUNT(*) FROM pg_constraint "
                "WHERE conname = :name AND contype = 'c'"
            ),
            {"name": AUDIT_NULL_ORG_CHECK},
        ).scalar()
        assert found == 1, f"{AUDIT_NULL_ORG_CHECK} is missing"


def test_no_ownerless_rows_remain():
    """The migration's data half, not just its schema half."""
    with engine.connect() as conn:
        for table in SCOPED_TABLES:
            orphans = conn.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE organization_id IS NULL")
            ).scalar()
            assert orphans == 0, f"{table} still has {orphans} ownerless rows"


def test_quarantined_rows_belong_to_an_organization_with_no_members():
    """Quarantine must not become a tenant someone can log into.

    Rows that could not be attributed were moved rather than deleted. That is
    only safe while nobody can authenticate into the organization holding them,
    which would otherwise turn a quarantine into a readable account.
    """
    with engine.connect() as conn:
        quarantine_id = conn.execute(
            text("SELECT id FROM organizations WHERE slug = 'system-quarantine'")
        ).scalar()
        if quarantine_id is None:
            pytest.skip("no quarantine organization: nothing needed quarantining")

        members = conn.execute(
            text("SELECT COUNT(*) FROM users WHERE organization_id = :oid"),
            {"oid": quarantine_id},
        ).scalar()
        assert members == 0, (
            "the quarantine organization has members, so rows moved there are "
            "readable by a real account"
        )
