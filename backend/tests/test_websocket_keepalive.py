"""Application-level keepalive, session expiry, and token redaction on /ws/telemetry.

The browser client sends {"type": "ping"} every 15 s and closes the socket
itself if no frame arrives within 30 s (frontend/src/services/websocket.ts).
Protocol-level PING/PONG never reaches browser JavaScript, so the server has to
answer with a data frame -- and it never did. On an idle feed the dashboard tore
its socket down and reconnected every ~31 s, forever.

That loop was also, by accident, the only thing re-validating the session, so
fixing it without a replacement would have let a socket outlive its token.
"""

import json
import logging
import uuid

import pytest
from starlette.websockets import WebSocketDisconnect

import models
from main import RedactQueryToken
from routers import websocket as websocket_router
from services.auth_service import create_access_token
from services.ws_manager import ConnectionManager, ws_manager
from tests.conftest import TestingSessionLocal

PING = json.dumps({"type": "ping"})


@pytest.fixture
def ws_operator(db_session):
    """A throwaway organization and user the handshake can resolve."""
    suffix = uuid.uuid4().hex[:8]
    org = models.Organization(name=f"pytest ws {suffix}", slug=f"pytest-ws-{suffix}")
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)

    user = models.User(
        username=f"pytest.ws.{suffix}", email=f"pytest.ws.{suffix}@example.test",
        role="operator", organization_id=org.id,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    yield user

    # The socket writes no audit rows, so a plain delete is enough.
    db_session.rollback()
    db_session.query(models.User).filter(models.User.id == user.id).delete(synchronize_session=False)
    db_session.commit()
    db_session.query(models.Organization).filter(
        models.Organization.id == org.id
    ).delete(synchronize_session=False)
    db_session.commit()


@pytest.fixture
def socket_env(monkeypatch):
    """Point the handshake at the test database and keep the broker out of it.

    `_resolve_user` opens `database.SessionLocal` directly -- there is no request
    to take `get_db` from. The broker is bypassed because this exercises the
    receive loop, not fan-out, and must not need Redis.
    """
    monkeypatch.setattr(websocket_router, "SessionLocal", TestingSessionLocal)

    async def no_broker(self):
        return None

    monkeypatch.setattr(ConnectionManager, "_ensure_broadcaster", no_broker)


def token_for(user: models.User) -> str:
    return create_access_token(
        data={"sub": user.username, "role": user.role,
              "org_id": user.organization_id, "tv": user.token_version}
    )


class TestKeepalive:
    def test_a_ping_is_answered_with_a_pong(self, client, ws_operator, socket_env):
        with client.websocket_connect(f"/ws/telemetry?token={token_for(ws_operator)}") as ws:
            ws.send_text(PING)
            assert ws.receive_json() == {"type": "pong"}

    def test_only_a_ping_is_answered(self, client, ws_operator, socket_env):
        with client.websocket_connect(f"/ws/telemetry?token={token_for(ws_operator)}") as ws:
            # None of these may close the socket or produce a reply...
            ws.send_text("not json")
            ws.send_text(json.dumps([1, 2, 3]))
            ws.send_text(json.dumps({"type": "subscribe"}))
            ws.send_text("x" * 5000)
            # ...so the first frame back is the answer to the ping.
            ws.send_text(PING)
            assert ws.receive_json() == {"type": "pong"}

    def test_the_socket_stays_registered_across_pings(self, client, ws_operator, socket_env):
        org = ws_operator.organization_id
        with client.websocket_connect(f"/ws/telemetry?token={token_for(ws_operator)}") as ws:
            for _ in range(3):
                ws.send_text(PING)
                assert ws.receive_json() == {"type": "pong"}
            assert ws_manager.client_count(org) == 1
        assert ws_manager.client_count(org) == 0, "the finally-block disconnect did not run"


class TestSessionExpiry:
    def test_an_expired_token_closes_the_socket_on_the_next_ping(
        self, client, ws_operator, socket_env, monkeypatch
    ):
        """Post-accept, so this is a real 1008 on the wire and the client stops retrying."""
        with client.websocket_connect(f"/ws/telemetry?token={token_for(ws_operator)}") as ws:
            ws.send_text(PING)
            assert ws.receive_json() == {"type": "pong"}

            # The token expires while the socket is open.
            monkeypatch.setattr(websocket_router, "decode_access_token", lambda token: None)

            ws.send_text(PING)
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_json()
            assert closed.value.code == 1008


class TestHandshake:
    """These pin the ASGI close code.

    Both rejections happen before `accept`, and uvicorn renders a pre-accept
    close as HTTP 403 -- which a browser surfaces as close code 1006, not 1008.
    So the client's do-not-retry branch is reached by the post-accept close in
    TestSessionExpiry, not by these. Neither touches the database, which is why
    `socket_env` is deliberately not requested.
    """

    def test_a_missing_token_is_refused(self, client):
        with pytest.raises(WebSocketDisconnect) as closed:
            with client.websocket_connect("/ws/telemetry"):
                pass
        assert closed.value.code == 1008

    def test_a_garbage_token_is_refused(self, client):
        with pytest.raises(WebSocketDisconnect) as closed:
            with client.websocket_connect("/ws/telemetry?token=not-a-jwt"):
                pass
        assert closed.value.code == 1008


class TestTokenRedaction:
    """nginx was told not to log /ws/. uvicorn's access log is the second sink."""

    def _record(self, *args) -> logging.LogRecord:
        return logging.LogRecord(
            "uvicorn.access", logging.INFO, __file__, 0, '%s - "WebSocket %s" [accepted]', args, None
        )

    def test_the_token_is_redacted_from_the_logged_path(self):
        record = self._record("172.28.0.10:5000", "/ws/telemetry?token=eyJhbGciOi.payload.sig")
        assert RedactQueryToken().filter(record) is True
        line = record.getMessage()
        assert "eyJhbGciOi" not in line
        assert "token=[redacted]" in line
        assert "/ws/telemetry" in line

    def test_other_query_parameters_survive(self):
        record = self._record("h", "/x?limit=5&token=secret.value&skip=2")
        RedactQueryToken().filter(record)
        assert record.getMessage().endswith('"WebSocket /x?limit=5&token=[redacted]&skip=2" [accepted]')

    def test_non_string_arguments_are_left_alone(self):
        record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 0, "%s %d", ("GET /health", 200), None)
        RedactQueryToken().filter(record)
        assert record.getMessage() == "GET /health 200"

    def test_the_filter_is_installed_on_the_access_logger(self):
        filters = logging.getLogger("uvicorn.access").filters
        assert any(isinstance(f, RedactQueryToken) for f in filters)
