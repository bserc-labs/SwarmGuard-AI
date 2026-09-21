"""Two organizations may both operate a drone called "UAV-001".

`ix_drones_drone_id` was globally unique. "UAV-001", "DRONE-ALPHA-01" and the
rest are exactly the identifiers two operators independently pick, so the
collision was a matter of time rather than of malice -- and its effects were
worse than the geofence-name case migration c3d4e5f6a7b8 already fixed:

  * telemetry_service looks the drone up scoped to the caller's organization,
    misses, and inserts. The insert violated the global index, so
    /telemetry/ingest returned 500 for that airframe and kept doing so on
    every subsequent packet. Whichever tenant registered the identifier first
    silently grounded the other's telemetry.

  * The failure disclosed that some other organization already held that
    drone_id -- the fact tenancy exists to hide.

Fixed by migration f6a7b8c9d0e1.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

import models
from tests.conftest import purge_audit_logs


@pytest.fixture
def two_organizations(db_session):
    suffix = uuid.uuid4().hex[:8]
    a = models.Organization(name=f"tenancy A {suffix}", slug=f"tenancy-a-{suffix}")
    b = models.Organization(name=f"tenancy B {suffix}", slug=f"tenancy-b-{suffix}")
    db_session.add_all([a, b])
    db_session.commit()
    db_session.refresh(a)
    db_session.refresh(b)

    yield a, b

    # Children first, and each step committed before the next. purge_audit_logs
    # opens with a rollback(), so anything merely staged when it is called is
    # silently discarded -- interleaving it with the drone deletes dropped them
    # and left the organizations un-deletable behind fk_drones_org.
    db_session.rollback()
    db_session.query(models.Drone).filter(
        models.Drone.organization_id.in_([a.id, b.id])
    ).delete(synchronize_session=False)
    db_session.commit()

    for org in (a, b):
        purge_audit_logs(db_session, org.id)

    db_session.query(models.Organization).filter(
        models.Organization.id.in_([a.id, b.id])
    ).delete(synchronize_session=False)
    db_session.commit()


def test_two_tenants_can_fly_the_same_drone_id(db_session, two_organizations):
    org_a, org_b = two_organizations
    shared_id = f"UAV-{uuid.uuid4().hex[:6]}"

    db_session.add(models.Drone(organization_id=org_a.id, drone_id=shared_id, status="ACTIVE"))
    db_session.commit()

    # Before f6a7b8c9d0e1 this raised IntegrityError on ix_drones_drone_id and
    # every ingest for org B's airframe became a 500.
    db_session.add(models.Drone(organization_id=org_b.id, drone_id=shared_id, status="ACTIVE"))
    db_session.commit()

    rows = (
        db_session.query(models.Drone)
        .filter(models.Drone.drone_id == shared_id)
        .all()
    )
    assert {r.organization_id for r in rows} == {org_a.id, org_b.id}


def test_one_tenant_still_cannot_register_the_same_drone_twice(db_session, two_organizations):
    """Per-organization uniqueness is still uniqueness."""
    org_a, _ = two_organizations
    drone_id = f"UAV-{uuid.uuid4().hex[:6]}"

    db_session.add(models.Drone(organization_id=org_a.id, drone_id=drone_id, status="ACTIVE"))
    db_session.commit()

    db_session.add(models.Drone(organization_id=org_a.id, drone_id=drone_id, status="ACTIVE"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_the_constraint_is_scoped_to_the_organization():
    """Guard against a future migration quietly restoring the global index."""
    from tests.conftest import TestingSessionLocal

    session = TestingSessionLocal()
    try:
        rows = list(
            session.execute(
                text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'drones'")
            )
        )
    finally:
        session.close()

    by_name = {name: definition for name, definition in rows}

    assert "uq_drones_org_drone_id" in by_name, "per-organization constraint is missing"
    assert "organization_id" in by_name["uq_drones_org_drone_id"]

    global_unique = [
        name
        for name, definition in by_name.items()
        if "UNIQUE" in definition.upper()
        and "drone_id" in definition
        and "organization_id" not in definition
    ]
    assert not global_unique, (
        f"drone_id carries a globally unique index again: {global_unique}. "
        "That is a cross-tenant denial of service, not a data-integrity win."
    )
