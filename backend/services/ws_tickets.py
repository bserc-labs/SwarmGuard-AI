"""Single-use tickets for opening a telemetry socket.

A browser cannot set headers on a WebSocket handshake, so the credential has to
travel in the URL, and the client sent the session JWT itself:
`/ws/telemetry?token=<jwt>`. Query strings are written to proxy access logs,
kept in browser history, and handed to whatever the page navigates to next.
Phase 0b stopped nginx and uvicorn logging this one, which shrank the exposure
without changing what it is: a long-lived credential in a URL.

A ticket is the same idea with the damage removed. It is minted by an
authenticated HTTPS request, lives about half a minute, opens exactly one
socket, and grants nothing else: replaying it opens nothing, and reading it out
of a log after the fact is worthless.

It carries the session it was minted from -- the username, the organization, the
token version, and the original token's expiry -- so the socket enforces exactly
what the session did, including outliving neither it nor a password change.
"""

import uuid
from datetime import UTC, datetime, timedelta

from services.auth_service import create_access_token, decode_access_token
from utils.shared_store import redis_client

TICKET_TYPE = "ws_ticket"
TICKET_LIFETIME = timedelta(seconds=30)

# Redis key prefix for spent tickets. The value is irrelevant; presence is what
# says "already used".
_SPENT = "swarmguard:ws-ticket-spent:"


def issue(*, username: str, organization_id: int, token_version: int, session_expires_at: int) -> str:
    """Mint a ticket for a session that has already been authenticated."""
    return create_access_token(
        {
            "typ": TICKET_TYPE,
            "sub": username,
            "org": organization_id,
            "tv": token_version,
            # The socket must not outlive the session it came from, and a ticket
            # is deliberately far shorter-lived than that session.
            "sess_exp": session_expires_at,
            "jti": uuid.uuid4().hex,
        },
        expires_delta=TICKET_LIFETIME,
    )


# Fallback when Redis is not configured: one process, one set. It is not shared
# across workers, which is exactly why Redis is preferred.
_spent_here: set[str] = set()


def _claim(jti: str) -> bool:
    """Mark a ticket spent. False if it was already."""
    store = redis_client()
    if store is None:
        if jti in _spent_here:
            return False
        _spent_here.add(jti)
        return True
    # SET NX with the ticket's own lifetime: after it expires the key is no
    # longer needed, because the ticket itself will not verify.
    claimed = store.set(_SPENT + jti, "1", nx=True, ex=int(TICKET_LIFETIME.total_seconds()) + 5)
    return bool(claimed)


def redeem(ticket: str) -> dict | None:
    """Verify a ticket and spend it. Returns its claims, or None."""
    payload = decode_access_token(ticket)
    if not payload or payload.get("typ") != TICKET_TYPE:
        # A session token is not a ticket. Without this check the URL would
        # still accept the credential this exists to keep out of it.
        return None

    session_expires_at = payload.get("sess_exp")
    if not isinstance(session_expires_at, int | float):
        return None
    if datetime.now(UTC).timestamp() >= session_expires_at:
        return None

    jti = payload.get("jti")
    if not jti or not _claim(str(jti)):
        return None

    return payload
