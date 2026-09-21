"""An account in one organization must not be able to shadow a username in another.

users.username and users.email are each unique, but nothing stopped one
account's email equalling another account's username. /auth/login resolved
`username = :x OR email = :x` with LIMIT 1 and no ORDER BY, so whichever row the
heap returned first won. An operator in Org B sets their email to "admin"; Org
A's administrator types "admin", the query hands back the operator's row, the
password does not match, and the administrator is locked out -- with every
failed attempt audited against the wrong organization.

Closed twice over: login resolves an exact username before it consults email,
and an email must now be shaped like one -- usernames cannot contain "@", so a
valid email can never equal a username. The first fix also covers rows that
already collide, which no input validation can.
"""

import uuid

import pytest

import models
from services.auth_service import get_password_hash
from tests.conftest import purge_audit_logs


def _login(client, identifier: str, password: str):
    return client.post("/auth/login", data={"username": identifier, "password": password})


def _token(client, identifier: str, password: str) -> dict:
    res = _login(client, identifier, password)
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture
def colliding_accounts(db_session):
    """Org A's admin, and an Org B operator whose email *is* the admin's username.

    Seeded through the ORM because the API now refuses that email -- which is
    the point: rows like this can already exist, and login must survive them.
    The attacker is inserted first, the best-effort reproduction of the heap
    order in which the old query returned the wrong row.
    """
    suffix = uuid.uuid4().hex[:8]
    org_a = models.Organization(name=f"pytest victim {suffix}", slug=f"pytest-vic-{suffix}")
    org_b = models.Organization(name=f"pytest attacker {suffix}", slug=f"pytest-att-{suffix}")
    db_session.add_all([org_a, org_b])
    db_session.commit()

    acc = {
        "victim_username": f"victim.{suffix}",
        "victim_email": f"victim.{suffix}@example.test",
        "victim_password": f"victim-password-{suffix}",
        "attacker_username": f"attacker.{suffix}",
        "attacker_password": f"attacker-password-{suffix}",
        "victim_org": org_a.id,
        "attacker_org": org_b.id,
    }

    db_session.add(
        models.User(
            username=acc["attacker_username"], email=acc["victim_username"],
            password=get_password_hash(acc["attacker_password"]),
            role="operator", organization_id=org_b.id,
        )
    )
    db_session.commit()
    db_session.add(
        models.User(
            username=acc["victim_username"], email=acc["victim_email"],
            password=get_password_hash(acc["victim_password"]),
            role="admin", organization_id=org_a.id,
        )
    )
    db_session.commit()

    yield acc

    # purge_audit_logs opens with a rollback, so it goes first, before anything
    # is staged. Logins write audit rows that hold fk_audit_org.
    for org_id in (org_a.id, org_b.id):
        purge_audit_logs(db_session, org_id)
    db_session.query(models.User).filter(
        models.User.organization_id.in_([org_a.id, org_b.id])
    ).delete(synchronize_session=False)
    db_session.commit()
    db_session.query(models.Organization).filter(
        models.Organization.id.in_([org_a.id, org_b.id])
    ).delete(synchronize_session=False)
    db_session.commit()


class TestLoginResolution:
    def test_username_login_survives_a_colliding_email(self, client, colliding_accounts):
        acc = colliding_accounts
        res = _login(client, acc["victim_username"], acc["victim_password"])
        assert res.status_code == 200, (
            "the administrator is locked out: login resolved the attacker's row, "
            "whose email equals this username"
        )
        assert res.json()["role"] == "admin"

    def test_login_after_logout_survives_it(self, client, colliding_accounts):
        """The realistic trigger. Logout bumps token_version and rewrites the row;
        which tuple the old `or_(...).first()` returned was a matter of heap order,
        so resolution must not depend on it."""
        acc = colliding_accounts
        headers = _token(client, acc["victim_username"], acc["victim_password"])
        assert client.post("/auth/logout", headers=headers).status_code == 200
        assert _login(client, acc["victim_username"], acc["victim_password"]).status_code == 200

    def test_the_attacker_cannot_log_in_as_the_username_they_squatted(self, client, colliding_accounts):
        acc = colliding_accounts
        assert _login(client, acc["victim_username"], acc["attacker_password"]).status_code == 401

    def test_a_failed_login_is_attributed_to_the_username_holder(self, client, db_session, colliding_accounts):
        acc = colliding_accounts
        assert _login(client, acc["victim_username"], "not-the-password").status_code == 401

        row = (
            db_session.query(models.AuditLog)
            .filter(
                models.AuditLog.action == "LOGIN_FAILED",
                models.AuditLog.resource_id == acc["victim_username"],
            )
            .order_by(models.AuditLog.id.desc())
            .first()
        )
        assert row is not None
        assert row.organization_id == acc["victim_org"], (
            "a failed login for Org A's admin was audited against Org B"
        )

    def test_email_login_still_works(self, client, colliding_accounts):
        """The Login page is labelled 'Username or email'; the fallback must remain."""
        acc = colliding_accounts
        res = _login(client, acc["victim_email"], acc["victim_password"])
        assert res.status_code == 200, res.text
        assert res.json()["role"] == "admin"


class TestEmailInput:
    def test_an_email_must_be_shaped_like_one(self, client, colliding_accounts):
        acc = colliding_accounts
        attacker = _token(client, acc["attacker_username"], acc["attacker_password"])
        # Before: 200, and the collision was stored.
        res = client.patch("/users/me", json={"email": acc["victim_username"]}, headers=attacker)
        assert res.status_code == 422

        admin = _token(client, acc["victim_username"], acc["victim_password"])
        res = client.post(
            "/users/",
            json={"username": f"new.{uuid.uuid4().hex[:6]}", "email": "not-an-email",
                  "password": "long-enough-password", "role": "observer"},
            headers=admin,
        )
        assert res.status_code == 422

    def test_taking_an_email_another_account_holds_is_a_conflict(self, client, colliding_accounts):
        """Previously an unhandled IntegrityError: a 500 and a poisoned session."""
        acc = colliding_accounts
        attacker = _token(client, acc["attacker_username"], acc["attacker_password"])
        res = client.patch("/users/me", json={"email": acc["victim_email"]}, headers=attacker)
        assert res.status_code == 409

    def test_a_blank_email_is_never_stored(self, client, db_session, colliding_accounts):
        """The Profile page sends the trimmed field verbatim, so clearing it sent ""."""
        acc = colliding_accounts
        admin = _token(client, acc["victim_username"], acc["victim_password"])
        res = client.patch("/users/me", json={"email": "   "}, headers=admin)
        assert res.status_code == 200
        assert res.json()["email"] == acc["victim_email"]

        stored = (
            db_session.query(models.User)
            .filter(models.User.username == acc["victim_username"])
            .one()
        )
        db_session.refresh(stored)
        assert stored.email == acc["victim_email"]

    def test_a_valid_email_is_accepted(self, client, colliding_accounts):
        acc = colliding_accounts
        admin = _token(client, acc["victim_username"], acc["victim_password"])
        new_email = f"changed.{uuid.uuid4().hex[:6]}@example.test"
        res = client.patch("/users/me", json={"email": new_email}, headers=admin)
        assert res.status_code == 200
        assert res.json()["email"] == new_email
