"""Error tracking is off without a DSN, on with one, and never ships a credential."""

import logging

import pytest

from config import Settings
from utils.error_tracking import REDACTED, init_error_tracking, scrub_event

STRONG = "0123456789abcdef0123456789abcdef0123456789abcdef"


class TestScrubbing:
    def test_credential_headers_are_redacted_and_the_rest_kept(self):
        event = {"request": {"headers": {
            "Authorization": "Bearer eyJ.abc.def",
            "Cookie": "session=abc",
            "X-Drone-API-Key": "k" * 64,
            "User-Agent": "curl/8",
        }}}
        out = scrub_event(event, None)
        headers = out["request"]["headers"]
        assert headers["Authorization"] == REDACTED
        assert headers["Cookie"] == REDACTED
        assert headers["X-Drone-API-Key"] == REDACTED
        assert headers["User-Agent"] == "curl/8"

    def test_the_websocket_token_in_the_query_string_is_redacted(self):
        event = {"request": {
            "url": "https://x/ws/telemetry?token=eyJ.secret.sig&x=1",
            "query_string": "token=eyJ.secret.sig&x=1",
        }}
        out = scrub_event(event, None)
        assert "secret" not in out["request"]["url"] and "x=1" in out["request"]["url"]
        assert out["request"]["query_string"] == f"token={REDACTED}&x=1"

    def test_password_fields_in_a_body_are_redacted_at_any_depth(self):
        event = {"request": {"data": {
            "username": "alice",
            "password": "hunter2-long-enough",
            "nested": {"new_password": "x", "keep": 1},
            "items": [{"token": "t"}, {"fine": True}],
        }}}
        out = scrub_event(event, None)
        data = out["request"]["data"]
        assert data["username"] == "alice"
        assert data["password"] == REDACTED
        assert data["nested"] == {"new_password": REDACTED, "keep": 1}
        assert data["items"] == [{"token": REDACTED}, {"fine": True}]

    def test_an_event_without_a_request_passes_through(self):
        assert scrub_event({"message": "boom"}, None) == {"message": "boom"}


class TestInit:
    def test_off_without_a_dsn(self, caplog):
        with caplog.at_level(logging.INFO):
            assert init_error_tracking(None, environment="test", release=None, logger=logging.getLogger("t")) is False
        assert "disabled" in caplog.text

    def test_on_with_a_dsn(self, caplog, monkeypatch):
        sentry_sdk = pytest.importorskip("sentry_sdk")
        calls = {}
        monkeypatch.setattr(sentry_sdk, "init", lambda **kw: calls.update(kw))
        with caplog.at_level(logging.INFO):
            assert init_error_tracking("https://k@o.ingest.sentry.io/1", environment="prod", release="sha-abc",
                                       logger=logging.getLogger("t")) is True
        assert calls["send_default_pii"] is False
        assert calls["before_send"] is scrub_event
        assert calls["environment"] == "prod" and calls["release"] == "sha-abc"
        assert "enabled" in caplog.text


def test_settings_defaults():
    s = Settings(_env_file=None, _secrets_dir=None, DATABASE_URL="postgresql://u:long-enough-pw@h/db",
                 SECRET_KEY=STRONG, DRONE_API_KEY=STRONG[::-1])  # type: ignore[call-arg]
    assert s.SENTRY_DSN is None
    assert s.SWARMGUARD_ENV == "development"
