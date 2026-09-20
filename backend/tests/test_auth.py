"""Authentication and protected-registration tests.

These run against whatever database DATABASE_URL points at, so they must not
assume a particular admin password. They previously hardcoded "admin123": on any
deployment provisioned with a real ADMIN_PASSWORD the login failed, the fallback
tried to INSERT a second row named "admin", and the test died on the unique
constraint rather than reporting a credentials mismatch. The admin used here is
created by the test, uniquely named, and cleaned up.
"""

import os
import uuid

import pytest

from tests.conftest import purge_audit_logs


@pytest.fixture
def seeded_admin(db_session):
    """An admin account this test owns, in its own organization.

    Created rather than borrowed so the test neither depends on the deployment's
    admin password nor mutates the real account. Both the user and the
    organization are removed afterwards, so repeated runs stay green.
    """
    import models
    from services.auth_service import get_password_hash

    suffix = uuid.uuid4().hex[:8]
    username = f"pytest.admin.{suffix}"
    # Comfortably over MIN_PASSWORD_LENGTH, which the create-user route enforces.
    password = f"pytest-password-{suffix}"

    organization = models.Organization(name=f"pytest org {suffix}", slug=f"pytest-{suffix}")
    db_session.add(organization)
    db_session.commit()
    db_session.refresh(organization)

    admin = models.User(
        username=username,
        email=f"{username}@example.test",
        password=get_password_hash(password),
        role="admin",
        organization_id=organization.id,
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)

    yield {"username": username, "password": password, "organization_id": organization.id}

    # Children first. Logging in writes a LOGIN_SUCCESS row into audit_logs, and
    # fk_audit_org refuses to let the organization go while it is referenced.
    # These are this fixture's own rows in its own throwaway organization, so
    # removing them does not touch the real audit trail.
    #
    # The audit rows go through purge_audit_logs because the table is
    # append-only at the database level (migration e5f6a7b8c9d0); a plain
    # DELETE is rejected by a trigger.
    purge_audit_logs(db_session, organization.id)
    db_session.query(models.User).filter(
        models.User.organization_id == organization.id
    ).delete(synchronize_session=False)
    db_session.query(models.Organization).filter(
        models.Organization.id == organization.id
    ).delete(synchronize_session=False)
    db_session.commit()


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_login_and_jwt(client, seeded_admin):
    response = client.post(
        "/auth/login",
        data={"username": seeded_admin["username"], "password": seeded_admin["password"]},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert "access_token" in body
    assert body["role"] == "admin"


def test_login_rejects_a_wrong_password(client, seeded_admin):
    response = client.post(
        "/auth/login",
        data={"username": seeded_admin["username"], "password": "not-the-password"},
    )
    assert response.status_code == 401


def test_protected_registration(client, seeded_admin):
    login_res = client.post(
        "/auth/login",
        data={"username": seeded_admin["username"], "password": seeded_admin["password"]},
    )
    assert login_res.status_code == 200, login_res.text
    token = login_res.json()["access_token"]

    new_username = f"pytest.user.{uuid.uuid4().hex[:8]}"
    payload = {
        "username": new_username,
        "email": f"{new_username}@example.test",
        "password": "SecurePassword123!",
    }

    reg_res = client.post(
        "/users/", json=payload, headers={"Authorization": f"Bearer {token}"}
    )
    assert reg_res.status_code == 201, reg_res.text
    assert reg_res.json()["username"] == new_username
    # Created inside the caller's organization, never one named by the client.
    assert reg_res.json()["organization_id"] == seeded_admin["organization_id"]


def test_registration_requires_authentication(client):
    """An unauthenticated create-user attempt must be refused.

    Previously skipped as "broadcaster not mocked", which this route does not
    touch -- it is a plain DB write behind require_permission. The skip hid the
    single most important assertion in the file.
    """
    payload = {
        "username": f"pytest.anon.{uuid.uuid4().hex[:8]}",
        "email": "anon@example.test",
        "password": "SecurePassword123!",
    }
    reg_res = client.post("/users/", json=payload)
    assert reg_res.status_code == 401


def test_admin_env_credentials_are_not_a_known_placeholder():
    """The provisioning password must not be one config.py would reject."""
    from config import KNOWN_PUBLIC_SECRETS

    password = os.getenv("ADMIN_PASSWORD")
    if not password:
        pytest.skip("ADMIN_PASSWORD is not configured in this environment")
    assert password not in KNOWN_PUBLIC_SECRETS
