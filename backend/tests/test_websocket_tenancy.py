"""WebSocket tenant isolation and handshake authentication.

The socket is the one delivery path that carries no Authorization header and no
tenant-scoped SQL query, so `test_route_tenancy` exempts it from the layer-3
source check and points here instead. This file is that promise.

Two properties:

  1. A frame published for one organization reaches only that organization's
     sockets. The manager keyed connections by organization precisely so a
     worker never even receives another tenant's payloads.

  2. The handshake resolves a live user, with an organization, holding a current
     token version. A socket that outlives the session it was issued for is a
     session-revocation hole that the HTTP path would have closed.
"""

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from services.ws_manager import ConnectionManager, channel_for

ORG_A = 1
ORG_B = 2


class FakeSocket:
    """Records what it was sent. Enough surface for the manager's delivery path."""

    def __init__(self, name):
        self.name = name
        self.sent = []
        self.closed = False

    async def send_json(self, message):
        if self.closed:
            raise RuntimeError("socket is closed")
        self.sent.append(message)


def run(coro):
    return asyncio.run(coro)


def manager_with(*registrations):
    """A manager with sockets already registered, and no broker.

    Built directly rather than via `connect()`, which would reach for Redis and
    turn a unit test of the routing rule into an integration test of the broker.
    With `_connected` False, `broadcast` delivers locally -- which is the path
    whose scoping this test is about.
    """
    manager = ConnectionManager()
    for organization_id, socket in registrations:
        manager._connections[organization_id].add(socket)
    return manager


# ------------------------------------------------------------- isolation

class TestDeliveryIsScopedToOneOrganization:
    def test_a_broadcast_reaches_only_the_named_organization(self):
        a, b = FakeSocket("org-a"), FakeSocket("org-b")
        manager = manager_with((ORG_A, a), (ORG_B, b))

        run(manager.broadcast({"drone_id": "A-1", "latitude": 1.0}, ORG_A))

        assert len(a.sent) == 1
        assert b.sent == [], "Org B received a frame published for Org A"

    def test_every_socket_of_the_named_organization_receives_it(self):
        first, second = FakeSocket("a1"), FakeSocket("a2")
        other = FakeSocket("b1")
        manager = manager_with((ORG_A, first), (ORG_A, second), (ORG_B, other))

        run(manager.broadcast({"event_type": "AI_DETECTION"}, ORG_A))

        assert len(first.sent) == 1 and len(second.sent) == 1
        assert other.sent == []

    def test_broadcasting_to_an_organization_with_no_listeners_is_harmless(self):
        b = FakeSocket("org-b")
        manager = manager_with((ORG_B, b))
        run(manager.broadcast({"x": 1}, ORG_A))
        assert b.sent == []

    def test_there_is_no_all_tenant_broadcast(self):
        """A caller must not be able to fan out by omitting the organization."""
        a = FakeSocket("org-a")
        manager = manager_with((ORG_A, a))
        with pytest.raises(ValueError, match="organization_id is required"):
            run(manager.broadcast({"x": 1}, None))
        assert a.sent == []

    def test_channels_are_namespaced_per_organization(self):
        """Cross-worker fan-out is per-organization at the broker too."""
        assert channel_for(ORG_A) != channel_for(ORG_B)
        assert str(ORG_A) in channel_for(ORG_A)

    def test_a_dead_socket_is_dropped_without_affecting_others(self):
        healthy, dead = FakeSocket("healthy"), FakeSocket("dead")
        dead.closed = True
        manager = manager_with((ORG_A, healthy), (ORG_A, dead))

        run(manager.broadcast({"x": 1}, ORG_A))

        assert len(healthy.sent) == 1
        assert dead not in manager._connections.get(ORG_A, set())

    def test_disconnecting_the_last_socket_clears_the_organization(self):
        a = FakeSocket("org-a")
        manager = manager_with((ORG_A, a))
        run(manager.disconnect(a, ORG_A))
        assert ORG_A not in manager._connections
        assert manager.client_count(ORG_A) == 0


# -------------------------------------------------------- handshake auth

class TestHandshakeAuthentication:
    """`_resolve_user` is the socket's entire authorization decision."""

    def test_a_garbage_token_is_rejected(self):
        from routers.websocket import _resolve_user

        assert _resolve_user("not-a-jwt") is None

    def test_an_empty_token_is_rejected(self):
        from routers.websocket import _resolve_user

        assert _resolve_user("") is None

    def test_a_token_for_an_unknown_user_is_rejected(self):
        """Signed correctly, but the account does not exist."""
        from routers.websocket import _resolve_user
        from services.auth_service import create_access_token

        token = create_access_token(
            data={"sub": "nobody.at.all", "role": "admin", "org_id": 1, "tv": 0}
        )
        assert _resolve_user(token) is None

    def test_a_token_without_a_subject_is_rejected(self):
        from routers.websocket import _resolve_user
        from services.auth_service import create_access_token

        token = create_access_token(data={"role": "admin", "org_id": 1, "tv": 0})
        assert _resolve_user(token) is None
