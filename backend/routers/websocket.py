import json
from datetime import UTC, datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session

import models
from database import SessionLocal
from services import ws_tickets
from services.ws_manager import ws_manager
from utils.logger import logger

router = APIRouter(prefix="/ws", tags=["websocket"])

# Policy violation. Used for every rejection so an unauthenticated client cannot
# distinguish a bad token from a disabled account.
CLOSE_POLICY = status.WS_1008_POLICY_VIOLATION

# Application-level keepalive. The browser sends {"type": "ping"} every 15 s and
# closes the socket itself if no frame arrives within 30 s
# (frontend/src/services/websocket.ts). Protocol-level PING/PONG never reaches
# browser JavaScript, so the answer has to be a data frame, in the one shape the
# client already treats as liveness and discards without forwarding.
PONG = {"type": "pong"}

# The keepalive is 15 bytes. Anything larger is not one and is not worth parsing.
MAX_KEEPALIVE_BYTES = 256


def _now() -> float:
    """Wall clock as a POSIX timestamp. Indirect so a test can move it."""
    return datetime.now(UTC).timestamp()


def _is_ping(raw: str) -> bool:
    if len(raw) > MAX_KEEPALIVE_BYTES:
        return False
    try:
        message = json.loads(raw)
    except json.JSONDecodeError:
        return False
    return isinstance(message, dict) and message.get("type") == "ping"


def _resolve_user(ticket: str) -> tuple[models.User, float] | None:
    """
    Redeem a ticket and resolve it to a live user record and a session expiry.

    This used to take the session JWT straight from the query string, which put
    a long-lived credential in proxy logs and browser history. It takes a
    single-use ticket now (services/ws_tickets.py); the checks below are the
    same ones the token got.

    An earlier version only decoded the credential: it never loaded the user, so
    one for a deleted account still opened a subscription, and the connection
    carried no organization to scope delivery by.
    """
    payload = ws_tickets.redeem(ticket)
    if not payload:
        return None

    username = payload.get("sub")
    if not username:
        return None

    db: Session = SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.username == username).first()
        if user is None or user.organization_id is None:
            return None

        # Same revocation check the HTTP dependency performs. Without it a ticket
        # minted before a password change would still open a live telemetry
        # subscription — the socket outliving the session it came from.
        if payload.get("tv") != user.token_version:
            return None

        # Detach the values we need; the session closes before the socket loop.
        db.expunge(user)
        return user, float(payload["sess_exp"])
    finally:
        db.close()


@router.websocket("/telemetry")
async def telemetry_socket(websocket: WebSocket, ticket: str | None = None):
    if not ticket:
        await websocket.close(code=CLOSE_POLICY, reason="Authentication required")
        return

    resolved = await run_in_threadpool_safe(ticket)
    if resolved is None:
        await websocket.close(code=CLOSE_POLICY, reason="Authentication failed")
        return

    user, session_expires_at = resolved
    organization_id = user.organization_id
    await ws_manager.connect(websocket, organization_id)

    try:
        while True:
            # Inbound content is ignored except the keepalive, which is answered.
            # It never was: on an idle feed -- no drones reporting, the normal
            # state between sorties -- nothing arrived within the client's 30 s
            # stale window, so it tore the socket down and reconnected every
            # ~31 s, forever.
            raw = await websocket.receive_text()
            if not _is_ping(raw):
                continue

            # That reconnect loop was also, by accident, the only thing that
            # re-validated the session: every reconnect re-ran the handshake.
            # A socket that stays up must not outlive the session it was opened
            # from, so its expiry -- carried in the ticket, not the ticket's own
            # half-minute -- is re-checked on each ping. No database, just a
            # comparison. This close is post-accept, so the browser really does
            # see 1008 and the client stops retrying instead of looping.
            if _now() >= session_expires_at:
                await websocket.close(code=CLOSE_POLICY, reason="Session expired")
                break

            await websocket.send_json(PONG)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning(f"WebSocket closed unexpectedly (org={organization_id}): {exc}")
    finally:
        # In a finally block so a non-disconnect exception cannot leak the
        # connection into the manager's registry.
        await ws_manager.disconnect(websocket, organization_id)


async def run_in_threadpool_safe(ticket: str) -> tuple[models.User, float] | None:
    """Run the blocking redemption and user lookup off the event loop."""
    import anyio

    return await anyio.to_thread.run_sync(_resolve_user, ticket)
