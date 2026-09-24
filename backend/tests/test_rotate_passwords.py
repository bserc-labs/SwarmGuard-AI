"""scripts/rotate_passwords.py against the real database.

The seed accounts' password hashes are in git history. Rotation is what
actually closes that: the old password must stop working, the new one must
work, and every session the account held must end.
"""

import io
import uuid

import pytest

import models
from scripts import rotate_passwords as rp
from services.auth_service import get_password_hash, verify_password
from tests.conftest import TestingSessionLocal, purge_audit_logs


@pytest.fixture
def db():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def accounts(db):
    suffix = uuid.uuid4().hex[:8]
    org = models.Organization(name=f"pytest rotate {suffix}", slug=f"pytest-rot-{suffix}")
    db.add(org)
    db.commit()
    names = [f"rot-{role}-{suffix}" for role in ("admin", "observer")]
    for name in names:
        db.add(models.User(username=name, password=get_password_hash("old-leaked-password"),
                           role="observer", organization_id=org.id, token_version=3))
    db.commit()
    yield org, names
    db.rollback()
    db.query(models.User).filter(models.User.organization_id == org.id).delete()
    db.commit()
    purge_audit_logs(db, org.id)
    db.query(models.Organization).filter(models.Organization.id == org.id).delete()
    db.commit()


def _user(db, name):
    db.expire_all()
    return db.query(models.User).filter_by(username=name).one()


class _Tty(io.StringIO):
    def isatty(self):
        return True


def test_old_password_stops_working_new_one_works_and_sessions_end(db, accounts):
    _, names = accounts
    out = io.StringIO()
    assert rp.main([*names, "not-on-this-server"], stdout=out, db=db) == 0

    lines = dict(line.split("\t") for line in out.getvalue().splitlines())
    assert set(lines) == set(names), "a missing account is skipped, not printed"
    for name in names:
        user = _user(db, name)
        assert not verify_password("old-leaked-password", user.password)
        assert verify_password(lines[name], user.password)
        assert len(lines[name]) >= 32
        assert user.token_version == 4, "existing sessions must be revoked"
    assert lines[names[0]] != lines[names[1]]


def test_each_rotation_is_audited_without_the_secret(db, accounts):
    org, names = accounts
    out = io.StringIO()
    rp.main(names, stdout=out, db=db)
    rows = db.query(models.AuditLog).filter_by(organization_id=org.id, action=rp.ACTION).all()
    assert {r.resource_id for r in rows} == set(names)
    for password in (line.split("\t")[1] for line in out.getvalue().splitlines()):
        assert all(password not in str(v) for r in rows for v in vars(r).values())


def test_it_refuses_to_print_passwords_to_a_terminal(db, accounts):
    _, names = accounts
    assert rp.main(names, stdout=_Tty(), db=db) == 2
    assert verify_password("old-leaked-password", _user(db, names[0]).password), "nothing may change"


def test_dry_run_changes_nothing(db, accounts):
    _, names = accounts
    assert rp.main(["--dry-run", *names], stdout=_Tty(), db=db) == 0
    assert verify_password("old-leaked-password", _user(db, names[0]).password)
    assert _user(db, names[0]).token_version == 3
