"""Rotating SECRET_KEY must not log every user out at the same instant.

If it does, the key is never rotated. So tokens are always signed with the
current key and verified against the current key and then the one it replaced.
The previous key stops verifying as soon as it is cleared, and an emergency
rotation clears it immediately -- which is the point when the key has leaked.
"""

import shutil
import stat
import subprocess
from datetime import timedelta
from pathlib import Path

import pytest
from jose import JWTError, jwt
from pydantic import ValidationError

from config import Settings
from services import auth_service

OLD = "0ld0ld0ld0ld0ld0ld0ld0ld0ld0ld0ld0ld0ld0ld0ld0ld"
NEW = "newnewnewnewnewnewnewnewnewnewnewnewnewnewnewnew"
STRANGER = "xyzxyzxyzxyzxyzxyzxyzxyzxyzxyzxyzxyzxyzxyzxyzxyz"
SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "rotate-secret-key.sh"


def signed_with(key: str, **claims) -> str:
    return jwt.encode({"sub": "alice", **claims}, key, algorithm=auth_service.ALGORITHM)


@pytest.fixture
def rotating(monkeypatch):
    """The API as it runs mid-rotation: NEW is current, OLD is previous."""
    monkeypatch.setattr(auth_service, "SECRET_KEY", NEW)
    monkeypatch.setattr(auth_service, "VERIFICATION_KEYS", (NEW, OLD))


class TestDuringARotation:
    def test_a_session_from_before_the_rotation_survives_it(self, rotating):
        assert auth_service.decode_access_token(signed_with(OLD))["sub"] == "alice"

    def test_new_tokens_are_signed_with_the_new_key_only(self, rotating):
        token = auth_service.create_access_token({"sub": "alice"})
        assert jwt.decode(token, NEW, algorithms=[auth_service.ALGORITHM])["sub"] == "alice"
        with pytest.raises(JWTError):
            jwt.decode(token, OLD, algorithms=[auth_service.ALGORITHM])

    def test_a_key_that_is_neither_still_verifies_nothing(self, rotating):
        assert auth_service.decode_access_token(signed_with(STRANGER)) is None

    def test_an_expired_token_is_not_rescued_by_the_previous_key(self, rotating):
        expired = auth_service.create_access_token({"sub": "alice"}, timedelta(minutes=-5))
        assert auth_service.decode_access_token(expired) is None
        old_and_expired = jwt.encode(
            {"sub": "alice", "exp": 1}, OLD, algorithm=auth_service.ALGORITHM
        )
        assert auth_service.decode_access_token(old_and_expired) is None


def test_once_the_rotation_is_finished_the_old_key_is_dead(monkeypatch):
    monkeypatch.setattr(auth_service, "VERIFICATION_KEYS", (NEW,))
    assert auth_service.decode_access_token(signed_with(OLD)) is None


def test_the_running_api_verifies_with_its_current_key_first():
    assert auth_service.VERIFICATION_KEYS[0] == auth_service.SECRET_KEY
    assert all(auth_service.VERIFICATION_KEYS), "an empty key would verify unsigned garbage"


class TestTheSetting:
    def build(self, **overrides):
        values = {
            "DATABASE_URL": "postgresql://u:long-enough-pw@h/db",
            "SECRET_KEY": NEW,
            "DRONE_API_KEY": STRANGER,
            **overrides,
        }
        return Settings(_env_file=None, _secrets_dir=None, **values)  # type: ignore[call-arg]

    def test_it_is_off_unless_set(self):
        assert self.build().SECRET_KEY_PREVIOUS is None

    @pytest.mark.parametrize("blank", ["", "   ", "\n"])
    def test_the_empty_file_compose_always_mounts_means_not_rotating(self, blank):
        assert self.build(SECRET_KEY_PREVIOUS=blank).SECRET_KEY_PREVIOUS is None

    def test_a_previous_key_is_held_to_the_same_rules_as_a_current_one(self):
        with pytest.raises(ValidationError, match="at least"):
            self.build(SECRET_KEY_PREVIOUS="too-short")

    def test_the_same_key_twice_is_not_a_rotation(self):
        with pytest.raises(ValidationError, match="not a rotation"):
            self.build(SECRET_KEY_PREVIOUS=NEW)


class TestTheScript:
    @pytest.fixture
    def run(self, tmp_path):
        shell = shutil.which("sh")
        if shell is None or shutil.which("openssl") is None:
            pytest.skip("needs a POSIX shell and openssl")
        (tmp_path / "secret_key").write_text(OLD)
        (tmp_path / "secret_key_previous").write_text("")

        def _run(*args: str):
            return subprocess.run(  # noqa: S603 - fixed argv, resolved executable
                [shell, str(SCRIPT), *args],
                env={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
                     "SWARMGUARD_SECRETS_DIR": str(tmp_path)},
                capture_output=True, text=True, timeout=30,
            )

        return _run, tmp_path

    def test_starting_keeps_the_old_key_as_previous(self, run):
        script, secrets = run
        done = script()
        assert done.returncode == 0, done.stderr
        assert (secrets / "secret_key_previous").read_text() == OLD
        fresh = (secrets / "secret_key").read_text()
        assert fresh != OLD and len(fresh) == 64 and not fresh.endswith("\n")
        assert OLD not in done.stdout and fresh not in done.stdout, "keys must never be printed"
        assert stat.S_IMODE((secrets / "secret_key").stat().st_mode) == 0o444

    def test_a_second_start_is_refused(self, run):
        """It would drop a key that live tokens may still be signed with."""
        script, secrets = run
        script()
        mid_rotation = (secrets / "secret_key").read_text()
        done = script()
        assert done.returncode == 1
        assert "already in progress" in done.stderr
        assert (secrets / "secret_key").read_text() == mid_rotation
        assert (secrets / "secret_key_previous").read_text() == OLD

    def test_finishing_clears_the_previous_key_and_keeps_the_current_one(self, run):
        script, secrets = run
        script()
        current = (secrets / "secret_key").read_text()
        assert script("--finish").returncode == 0
        assert (secrets / "secret_key_previous").read_text() == ""
        assert (secrets / "secret_key").read_text() == current

    def test_an_emergency_rotation_leaves_no_grace_period(self, run):
        script, secrets = run
        assert script("--emergency").returncode == 0
        assert (secrets / "secret_key").read_text() != OLD
        assert (secrets / "secret_key_previous").read_text() == ""
