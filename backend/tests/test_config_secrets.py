"""Startup validation of secrets and credentials.

`config.py` is the only place that can refuse to start on a bad secret, so the
rules it enforces are worth pinning. A regression here is silent: the service
comes up happily with a known-public key.
"""

import os
import sys
import warnings

import pytest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from config import (
    KNOWN_PUBLIC_SECRETS,
    MIN_SECRET_LENGTH,
    WEAK_DB_PASSWORDS,
    _db_password,
    _validate_secret,
)

STRONG = "0123456789abcdef0123456789abcdef0123456789abcdef"


class TestSecretValidation:
    def test_a_strong_secret_is_accepted(self):
        assert _validate_secret(STRONG, "SECRET_KEY") == STRONG

    @pytest.mark.parametrize("value", ["", "   ", None])
    def test_an_absent_secret_is_refused(self, value):
        with pytest.raises(ValueError, match="must be set"):
            _validate_secret(value, "SECRET_KEY")

    def test_a_short_secret_is_refused(self):
        with pytest.raises(ValueError, match="at least"):
            _validate_secret("a" * (MIN_SECRET_LENGTH - 1), "SECRET_KEY")

    @pytest.mark.parametrize("value", sorted(KNOWN_PUBLIC_SECRETS))
    def test_every_known_placeholder_is_refused(self, value):
        """These have appeared in committed examples, compose files or CI."""
        with pytest.raises(ValueError, match=r"publicly known|at least|must be set"):
            _validate_secret(value, "SECRET_KEY")

    def test_the_denylist_still_covers_the_values_that_leaked_before(self):
        for value in (
            "CHANGE_ME",
            "SWARMGUARD_DEFENSE_PRODUCTION_SECRET_KEY_2026",
            "SWARMGUARD_DRONE_DEFENSE_SECRET_2026",
            "test_ci_secret_key",
        ):
            assert value in KNOWN_PUBLIC_SECRETS


class TestDatabasePassword:
    def test_the_password_is_extracted_from_a_url(self):
        assert _db_password("postgresql://user:hunter2@host:5432/db") == "hunter2"

    def test_a_percent_encoded_password_is_decoded(self):
        assert _db_password("postgresql://user:p%40ss@host:5432/db") == "p@ss"

    def test_a_url_without_a_password_yields_none(self):
        assert _db_password("postgresql://host:5432/db") is None

    def test_a_malformed_url_does_not_raise(self):
        """Validation must never be the reason startup crashes."""
        assert _db_password("not a url at all") is None

    def test_a_weak_password_warns(self):
        from config import Settings

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            Settings(
                DATABASE_URL="postgresql://postgres:password@localhost:5432/db",
                SECRET_KEY=STRONG,
                DRONE_API_KEY=STRONG,
            )
        assert any("weak, guessable password" in str(w.message) for w in caught), (
            "A dictionary-word database password produced no warning."
        )

    def test_a_strong_password_does_not_warn(self):
        from config import Settings

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            Settings(
                DATABASE_URL=f"postgresql://postgres:{STRONG}@localhost:5432/db",
                SECRET_KEY=STRONG,
                DRONE_API_KEY=STRONG,
            )
        assert not any("weak, guessable" in str(w.message) for w in caught)

    def test_a_weak_password_does_not_prevent_startup(self):
        """Deliberate: this is a warning, not a failure. See the validator."""
        from config import Settings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            settings = Settings(
                DATABASE_URL="postgresql://postgres:password@localhost:5432/db",
                SECRET_KEY=STRONG,
                DRONE_API_KEY=STRONG,
            )
        assert settings.DATABASE_URL.endswith("/db")

    def test_the_credentials_this_repo_actually_ships_with_are_covered(self):
        """CI and the sample .env both use postgres/password."""
        assert "password" in WEAK_DB_PASSWORDS
        assert "postgres" in WEAK_DB_PASSWORDS


class TestDefaultsAreSafe:
    def test_the_ml_tier_is_disabled_by_default(self):
        from config import Settings

        settings = Settings(
            DATABASE_URL=f"postgresql://u:{STRONG}@h:5432/db",
            SECRET_KEY=STRONG,
            DRONE_API_KEY=STRONG,
        )
        assert settings.AI_INCIDENTS_ENABLED is False, (
            "Tier 2 measures F1 0.086 at a 0.862 false-positive rate under "
            "leave-one-flight-out. It must not become enabled by default."
        )

    def test_mavlink_is_disabled_by_default(self):
        from config import Settings

        settings = Settings(
            DATABASE_URL=f"postgresql://u:{STRONG}@h:5432/db",
            SECRET_KEY=STRONG,
            DRONE_API_KEY=STRONG,
        )
        assert settings.MAVLINK_ENABLED is False
        assert settings.GUARD_ENABLED is True
