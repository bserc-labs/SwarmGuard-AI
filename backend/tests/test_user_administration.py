"""Administering other people's accounts.

The product could create users and list them, and that was all. An operator who
left could not be removed except in the database, and a role could not be
corrected at all. Both are ordinary administration, and both have to be done
without letting an organization lock itself out of its own console.
"""

import uuid

import pytest
from sqlalchemy import text

import models
from services.auth_service import create_access_token, get_password_hash


@pytest.fixture
def org(db_session):
    suffix = uuid.uuid4().hex[:8]
    organization = models.Organization(name=f"pytest admin {suffix}", slug=f"pytest-adm-{suffix}")
    db_session.add(organization)
    db_session.commit()
    db_session.refresh(organization)

    yield organization

    db_session.rollback()
    # audit_logs is append-only; its maintenance flag is the documented way
    # through, and the retention job uses the same one.
    db_session.execute(text("SET LOCAL swarmguard.audit_maintenance = 'on'"))
    db_session.query(models.AuditLog).filter(
        models.AuditLog.organization_id == organization.id
    ).delete(synchronize_session=False)
    db_session.query(models.User).filter(
        models.User.organization_id == organization.id
    ).delete(synchronize_session=False)
    db_session.query(models.Organization).filter(
        models.Organization.id == organization.id
    ).delete(synchronize_session=False)
    db_session.commit()


def _user(db, organization, *, role="operator", active=True) -> models.User:
    suffix = uuid.uuid4().hex[:8]
    user = models.User(
        username=f"pytest.{role}.{suffix}",
        email=f"pytest.{role}.{suffix}@example.test",
        password=get_password_hash("correct horse battery staple"),
        role=role,
        organization_id=organization.id,
        is_active=active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _headers(user: models.User) -> dict:
    token = create_access_token(
        data={"sub": user.username, "role": user.role,
              "org_id": user.organization_id, "tv": user.token_version}
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin(db_session, org):
    return _user(db_session, org, role="admin")


class TestChangingAnAccount:
    def test_an_admin_can_change_a_role(self, client, db_session, org, admin):
        member = _user(db_session, org, role="observer")

        response = client.patch(
            f"/users/{member.id}", json={"role": "analyst"}, headers=_headers(admin)
        )

        assert response.status_code == 200
        assert response.json()["role"] == "analyst"
        db_session.refresh(member)
        assert member.role == "analyst"

    def test_a_role_change_revokes_the_account_s_sessions(self, client, db_session, org, admin):
        member = _user(db_session, org, role="observer")
        before = member.token_version
        stale = _headers(member)

        client.patch(f"/users/{member.id}", json={"role": "analyst"}, headers=_headers(admin))

        db_session.refresh(member)
        assert member.token_version == before + 1
        # The token issued before the change carries the old version.
        assert client.get("/users/me", headers=stale).status_code == 401

    def test_disabling_stops_the_account_using_a_token_it_already_holds(
        self, client, db_session, org, admin
    ):
        member = _user(db_session, org, role="operator")
        held = _headers(member)
        assert client.get("/users/me", headers=held).status_code == 200

        response = client.patch(
            f"/users/{member.id}", json={"is_active": False}, headers=_headers(admin)
        )

        assert response.status_code == 200
        assert response.json()["is_active"] is False
        assert client.get("/users/me", headers=held).status_code == 401

    def test_a_disabled_account_cannot_sign_in(self, client, db_session, org):
        member = _user(db_session, org, role="operator", active=False)

        response = client.post(
            "/auth/login",
            data={"username": member.username, "password": "correct horse battery staple"},
        )

        assert response.status_code == 401
        # Same message as a wrong password: the caller learns nothing new.
        assert "Incorrect username or password" in response.json()["detail"]

    def test_re_enabling_restores_the_account(self, client, db_session, org, admin):
        member = _user(db_session, org, role="operator", active=False)

        client.patch(f"/users/{member.id}", json={"is_active": True}, headers=_headers(admin))

        signed_in = client.post(
            "/auth/login",
            data={"username": member.username, "password": "correct horse battery staple"},
        )
        assert signed_in.status_code == 200

    def test_the_change_is_audited(self, client, db_session, org, admin):
        member = _user(db_session, org, role="observer")

        client.patch(f"/users/{member.id}", json={"role": "analyst"}, headers=_headers(admin))

        entry = (
            db_session.query(models.AuditLog)
            .filter(
                models.AuditLog.organization_id == org.id,
                models.AuditLog.action == "USER_UPDATED",
            )
            .one()
        )
        assert entry.resource_id == member.username
        assert "observer" in (entry.previous_state or "")
        assert "analyst" in (entry.new_state or "")


class TestDeleting:
    def test_an_admin_can_delete_an_account(self, client, db_session, org, admin):
        member = _user(db_session, org, role="operator")

        response = client.delete(f"/users/{member.id}", headers=_headers(admin))

        assert response.status_code == 204
        assert db_session.query(models.User).filter(models.User.id == member.id).first() is None

    def test_the_deletion_is_audited(self, client, db_session, org, admin):
        member = _user(db_session, org, role="operator")
        username = member.username

        client.delete(f"/users/{member.id}", headers=_headers(admin))

        entry = (
            db_session.query(models.AuditLog)
            .filter(
                models.AuditLog.organization_id == org.id,
                models.AuditLog.action == "USER_DELETED",
            )
            .one()
        )
        assert entry.resource_id == username


class TestAnOrganizationCannotLockItselfOut:
    """The invariant, and the one rule that produces it.

    Only an administrator can reach these routes, and no administrator can act
    on their own account, so whoever makes a change is still an administrator
    afterwards. An organization therefore always keeps at least one.
    """

    def test_the_last_admin_survives_disabling_every_other_one(
        self, client, db_session, org, admin
    ):
        colleague = _user(db_session, org, role="admin")

        # The last remaining administrator disables the other one...
        assert client.patch(
            f"/users/{colleague.id}", json={"is_active": False}, headers=_headers(admin)
        ).status_code == 200
        # ...and cannot then disable themselves.
        assert client.patch(
            f"/users/{admin.id}", json={"is_active": False}, headers=_headers(admin)
        ).status_code == 400

        db_session.refresh(admin)
        assert admin.is_active is True
        assert admin.role == "admin"

    def test_a_disabled_admin_cannot_administer_anyone(self, client, db_session, org, admin):
        colleague = _user(db_session, org, role="admin")
        held = _headers(colleague)

        client.patch(f"/users/{colleague.id}", json={"is_active": False}, headers=_headers(admin))

        # Disabling revoked its sessions, so the token it held is worthless.
        assert client.patch(
            f"/users/{admin.id}", json={"is_active": False}, headers=held
        ).status_code == 401

    def test_an_admin_cannot_change_their_own_account_here(self, client, org, admin):
        response = client.patch(
            f"/users/{admin.id}", json={"role": "observer"}, headers=_headers(admin)
        )

        assert response.status_code == 400
        assert "another administrator" in response.json()["detail"]

    def test_an_admin_cannot_delete_themselves(self, client, org, admin):
        response = client.delete(f"/users/{admin.id}", headers=_headers(admin))

        assert response.status_code == 400


class TestTheRoutesDoNotShadowEachOther:
    def test_me_is_not_read_as_a_user_id(self, client, org, admin):
        # FastAPI matches in declaration order, so "/{user_id}" declared first
        # swallows "/me" and tries to parse it as an id. It did, briefly.
        assert client.get("/users/me", headers=_headers(admin)).status_code == 200
        assert client.patch(
            "/users/me", json={"email": None}, headers=_headers(admin)
        ).status_code == 200


class TestTenancyAndPermission:
    def test_an_account_in_another_organization_is_not_found(self, client, db_session, org, admin):
        elsewhere = models.Organization(
            name=f"pytest other {uuid.uuid4().hex[:8]}", slug=f"pytest-other-{uuid.uuid4().hex[:8]}"
        )
        db_session.add(elsewhere)
        db_session.commit()
        stranger = _user(db_session, elsewhere, role="operator")

        try:
            response = client.patch(
                f"/users/{stranger.id}", json={"role": "analyst"}, headers=_headers(admin)
            )
            assert response.status_code == 404

            deleted = client.delete(f"/users/{stranger.id}", headers=_headers(admin))
            assert deleted.status_code == 404
        finally:
            db_session.query(models.User).filter(models.User.id == stranger.id).delete(
                synchronize_session=False
            )
            db_session.query(models.Organization).filter(
                models.Organization.id == elsewhere.id
            ).delete(synchronize_session=False)
            db_session.commit()

    def test_an_operator_cannot_administer_anyone(self, client, db_session, org, admin):
        member = _user(db_session, org, role="operator")
        target = _user(db_session, org, role="observer")

        assert client.patch(
            f"/users/{target.id}", json={"role": "analyst"}, headers=_headers(member)
        ).status_code == 403
        assert client.delete(f"/users/{target.id}", headers=_headers(member)).status_code == 403
