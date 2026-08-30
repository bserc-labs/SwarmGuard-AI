from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session

import models
from database import SessionLocal
from services.auth_service import decode_access_token
from services.ws_manager import ws_manager
from utils.logger import logger

router = APIRouter(prefix="/ws", tags=["websocket"])

# Policy violation. Used for every rejection so an unauthenticated client cannot
# distinguish a bad token from a disabled account.
CLOSE_POLICY = status.WS_1008_POLICY_VIOLATION


def _resolve_user(token: str) -> models.User | None:
    """
    Resolve the token to a live user record.

    The previous implementation only decoded the token: it never loaded the
    user, so a token for a deleted account still opened a subscription, and the
    connection carried no organization to scope delivery by.
    """
    payload = decode_access_token(token)
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

        # Same revocation check the HTTP dependency performs. Without it a token
        # invalidated by a password change would still open a live telemetry
        # subscription — the socket outliving the session it was issued for.
        if payload.get("tv") != user.token_version:
            return None

        # Detach the values we need; the session closes before the socket loop.
        db.expunge(user)
        return user
    finally:
        db.close()


@router.websocket("/telemetry")
async def telemetry_socket(websocket: WebSocket, token: str | None = None):
    if not token:
        await websocket.close(code=CLOSE_POLICY, reason="Authentication required")
        return

    user = await run_in_threadpool_safe(token)
    if user is None:
        await websocket.close(code=CLOSE_POLICY, reason="Authentication failed")
        return

    organization_id = user.organization_id
    await ws_manager.connect(websocket, organization_id)

    try:
        while True:
            # The client sends only keepalive pings; inbound content is ignored.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning(f"WebSocket closed unexpectedly (org={organization_id}): {exc}")
    finally:
        # In a finally block so a non-disconnect exception cannot leak the
        # connection into the manager's registry.
        await ws_manager.disconnect(websocket, organization_id)


async def run_in_threadpool_safe(token: str) -> models.User | None:
    """Run the blocking user lookup off the event loop."""
    import anyio

    return await anyio.to_thread.run_sync(_resolve_user, token)
