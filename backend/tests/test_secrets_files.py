"""Secrets arrive as mounted files, not as environment variables.

A secret in the environment is printed by `docker inspect`, inherited by every
child process and captured in crash dumps. Under compose the three secrets are
mounted at /run/secrets and the matching environment variables are passed
*empty* on purpose: `environment:` beats `env_file:`, and an empty value means
"unset" to the application, so even a .env that still holds the secrets cannot
put them into the container's environment.

These tests reproduce that arrangement: blank variables, real values in files.
"""

import warnings

import pytest
from pydantic import ValidationError

import config
from config import Settings, _db_password

STRONG = "0123456789abcdef0123456789abcdef0123456789abcdef"
OTHER = "fedcba9876543210fedcba9876543210fedcba9876543210"
URL_NO_PASSWORD = "postgresql://swarm@postgres:5432/swarmguard"


@pytest.fixture
def secrets(tmp_path, monkeypatch):
    """A /run/secrets stand-in, with the environment blanked as compose does."""
    for name in ("SECRET_KEY", "DRONE_API_KEY", "DATABASE_PASSWORD"):
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("DATABASE_URL", URL_NO_PASSWORD)

    def write(**files: str) -> str:
        for name, value in files.items():
            (tmp_path / name).write_text(value)
        return str(tmp_path)

    return write


def load(secrets_dir: str) -> Settings:
    return Settings(_env_file=None, _secrets_dir=secrets_dir)  # type: ignore[call-arg]


class TestSecretsComeFromFiles:
    def test_a_blank_variable_falls_through_to_the_file(self, secrets):
        settings = load(secrets(secret_key=STRONG, drone_api_key=OTHER))
        assert settings.SECRET_KEY == STRONG
        assert settings.DRONE_API_KEY == OTHER

    def test_a_trailing_newline_is_not_part_of_the_secret(self, secrets):
        """`openssl rand -hex 32 > file` writes one; a JWT signed with it would not verify elsewhere."""
        settings = load(secrets(secret_key=STRONG + "\n", drone_api_key=OTHER + "\n"))
        assert settings.SECRET_KEY == STRONG

    def test_the_environment_still_wins(self, secrets, monkeypatch):
        """Native runs, CI and this suite configure by environment and must not change."""
        directory = secrets(secret_key=STRONG, drone_api_key=OTHER)
        monkeypatch.setenv("SECRET_KEY", OTHER)
        assert load(directory).SECRET_KEY == OTHER

    def test_a_file_is_held_to_the_same_rules_as_a_variable(self, secrets):
        with pytest.raises(ValidationError, match="publicly known"):
            load(secrets(secret_key="CHANGE_ME", drone_api_key=OTHER))

    def test_a_missing_secret_is_still_fatal(self, secrets):
        with pytest.raises(ValidationError, match="SECRET_KEY"):
            load(secrets(drone_api_key=OTHER))


class TestTheDatabasePasswordIsSuppliedApart:
    def test_it_is_joined_into_a_url_that_has_none(self, secrets):
        settings = load(secrets(secret_key=STRONG, drone_api_key=OTHER, database_password="s3cret-value"))
        assert settings.DATABASE_URL == "postgresql://swarm:s3cret-value@postgres:5432/swarmguard"

    def test_reserved_characters_survive_the_round_trip(self, secrets):
        awkward = "p@ss:w/rd#1?&="
        settings = load(secrets(secret_key=STRONG, drone_api_key=OTHER, database_password=awkward))
        assert _db_password(settings.DATABASE_URL) == awkward
        assert "@postgres:5432/swarmguard" in settings.DATABASE_URL

    def test_a_url_with_its_own_password_is_left_alone(self, secrets, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://swarm:from-the-url@postgres:5432/swarmguard")
        settings = load(secrets(secret_key=STRONG, drone_api_key=OTHER, database_password="from-the-file"))
        assert _db_password(settings.DATABASE_URL) == "from-the-url"

    def test_a_weak_password_from_a_file_warns_like_one_in_the_url(self, secrets):
        directory = secrets(secret_key=STRONG, drone_api_key=OTHER, database_password="password")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            load(directory)
        assert any("weak" in str(w.message) for w in caught)

    def test_a_url_that_cannot_be_parsed_is_a_clear_error(self, secrets, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "not a url at all")
        with pytest.raises(ValidationError, match="not a valid database URL"):
            load(secrets(secret_key=STRONG, drone_api_key=OTHER, database_password="anything"))


class TestTheSecretsDirectory:
    def test_it_is_used_only_when_it_exists(self, tmp_path, monkeypatch):
        """pydantic warns on every start about a directory that is not there."""
        monkeypatch.setattr(config, "SECRETS_DIR", tmp_path / "absent")
        assert config._secrets_dir() is None
        monkeypatch.setattr(config, "SECRETS_DIR", tmp_path)
        assert config._secrets_dir() == str(tmp_path)

    def test_the_default_is_where_docker_mounts_them(self):
        assert str(config.SECRETS_DIR) == "/run/secrets" or "SECRETS_DIR" in __import__("os").environ
