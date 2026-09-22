"""CORS origins are configuration, HTTPS-aware, and never a wildcard.

The list was hardcoded to three http:// origins. Once nginx served the app over
HTTPS, a page on https://localhost calling the loopback API was refused by its
own backend. The deployed frontend never notices -- it is same-origin through
nginx -- which is exactly why a wrong list survives until someone develops
against it.

A wildcard is refused outright: the API allows credentials, so `*` would let any
website a signed-in operator visits drive the API as them.
"""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from config import Settings
from main import app

STRONG = "0123456789abcdef0123456789abcdef0123456789abcdef"


def build(**overrides) -> Settings:
    values = {
        "DATABASE_URL": "postgresql://u:long-enough-pw@h/db",
        "SECRET_KEY": STRONG,
        "DRONE_API_KEY": STRONG[::-1],
        **overrides,
    }
    return Settings(_env_file=None, _secrets_dir=None, **values)  # type: ignore[call-arg]


class TestTheSetting:
    def test_the_default_covers_the_https_frontend_and_the_dev_server(self):
        origins = build().cors_origins
        assert "https://localhost" in origins
        assert "http://localhost:5173" in origins

    def test_it_is_parsed_forgivingly(self):
        settings = build(CORS_ALLOWED_ORIGINS=" https://a.example/ , https://b.example ,, ")
        assert settings.cors_origins == ["https://a.example", "https://b.example"]

    @pytest.mark.parametrize("value", ["*", "https://a.example,*", " * "])
    def test_a_wildcard_is_refused(self, value):
        with pytest.raises(ValidationError, match="must not contain"):
            build(CORS_ALLOWED_ORIGINS=value)


class TestTheRunningApp:
    def preflight(self, origin: str):
        return TestClient(app).options(
            "/auth/login",
            headers={"Origin": origin, "Access-Control-Request-Method": "POST"},
        )

    def test_an_allowed_https_origin_is_answered(self):
        res = self.preflight("https://localhost")
        assert res.headers.get("access-control-allow-origin") == "https://localhost"
        assert res.headers.get("access-control-allow-credentials") == "true"

    def test_an_unknown_origin_gets_no_permission(self):
        res = self.preflight("https://evil.example")
        assert "access-control-allow-origin" not in res.headers
